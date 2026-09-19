# Phase 10 — Context-Aware AI Financial Assistant

Technical report. Phases 1–9 were left functional; nothing was removed or
redesigned. The assistant was rebuilt as a **chat product** rather than a raw
side console, and the backend layer was finished, made observable, and tested.

---

## 1. AI architecture

```
USER
 │
 ▼
AI CHAT UI            components/ai/*  (dock on desktop, sheet on mobile)
 │
 ▼
AI REQUEST API        /api/ai/stream (SSE) · /api/ai/chat (fallback)
 │
 ▼
INTENT / ROUTER       agents.INTENT_KEYWORDS → AgentTask row (RUNNING)
 │
 ▼
CONTEXT BUILDER       ai/context_builder.ContextBuilder  (one normalized object)
 │
 ▼
DATA SOURCES          provider layer (yfinance quotes) · NewsArticle rows ·
 │                    PSX announcements feed · sentiment scoring · portfolio tables
 ▼
PROMPT BUILDER        ai/prompt_builder.PromptBuilder (system / rules / context / question)
 │
 ▼
AI PROVIDER           ai/providers.AIProvider → OpenAI | OpenRouter | Anthropic
 │
 ▼
VALIDATION            ai/citations · ai/errors (classification) · empty-answer guard
 │
 ▼
STREAM / RESPONSE     persisted message + citations → SSE events → CHAT UI
```

Layer by layer:

| Layer | File | Responsibility |
|---|---|---|
| Controller | `app/ai_controller.py` | HTTP/SSE surface, request ids, observability, task bookkeeping, persistence ordering |
| Agents | `app/ai/agents.py` | Intent routing + 7 specialised agents (market, stock, news, announcement, sentiment, portfolio, comparison) |
| Context | `app/ai/context_builder.py` | One normalized context object per request; concurrent price/news/sentiment fetches |
| Prompting | `app/ai/prompt_builder.py` | Structured prompt assembly, page-aware suggested prompts |
| Conversations | `app/ai/conversation_service.py` | CRUD, context-window trimming, auto-titles, stats |
| Streaming | `app/ai/streaming_service.py` | Structured SSE events (`status`/`chunk`/`complete`/`error`) |
| Providers | `app/ai/providers.py` | `AIProvider` ABC + OpenAI / OpenRouter / Anthropic implementations |
| Citations | `app/ai/citations.py` | Attributable source list built from the context that was sent |
| Errors | `app/ai/errors.py` | Category classification + user-safe messages + HTTP mapping |

The frontend never talks to a model provider. `lib/aiService.ts` is the only
module that knows the endpoints, and the API keys exist only in backend
environment variables.

## 2. Backend endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/ai/chat` | One-shot answer (fallback path) |
| POST | `/api/ai/stream` | Streamed answer, `text/event-stream` |
| GET | `/api/ai/conversations` | Paginated conversation list |
| POST | `/api/ai/conversations` | Create conversation (first turn) |
| GET | `/api/ai/conversations/{id}` | Conversation + stats |
| PUT | `/api/ai/conversations/{id}` | Rename |
| DELETE | `/api/ai/conversations/{id}` | Delete conversation + messages |
| GET | `/api/ai/conversations/{id}/messages` | Full message history |
| POST | `/api/ai/suggested-prompts` | Page-aware prompt ideas |
| GET | `/api/ai/agent-tasks` | Agent task history |
| GET | `/api/ai/status` | Provider/model availability (never a key) |

**SSE event contract**

| Event | Payload |
|---|---|
| `status` | `{status: "thinking"｜"streaming", conversation_id}` |
| `chunk` | `{content}` |
| `complete` | `{full_content, message_id, conversation_id, model, processing_time_ms, citations, stopped}` |
| `error` | `{error, category, error_type, request_id, conversation_id, retryable}` |

Answer rows are **persisted before** the `complete` event is emitted, so the
`message_id` the client receives is the row it can later fetch, rename or cite.

## 3. Context model

One normalized object, built per request by `ContextBuilder.build_context`:

```
{
  timestamp, route, page_type, market_status,
  symbol?, entity_type?, timeframe?,
  stock_context?  { symbol, price, previous_close, change, change_percent, last_date,
                    recent_news[], recent_announcements[], sentiment{...} },
  index_context?  { symbol, price, …, recent_news[], sentiment },
  market_context? { indices{KSE100,KSE30}, market_status, status },
  news_context?   { recent_headlines[], aggregate_sentiment },
  portfolio_context? { positions_count, total_cost_basis, total_value, total_pnl,
                       total_pnl_pct, holdings[], transactions[] }
}
```

The frontend half lives in `hooks/useAIContext.ts`: it reads route, symbol /
index, timeframe and page type, and exposes the same facts the user sees in the
context chips. Portfolio **content** is never collected in the browser.

## 4. Agent / tool architecture

`AgentRouter.detect_intent` classifies the question (comparison → portfolio →
announcement → news → sentiment → context symbol → market) using an ordered
keyword table, and the controller records the corresponding task. Agents are
deliberately narrow and share one `ContextBuilder`, so no agent can reach data
outside its capability:

| Agent | Task type | Data reach |
|---|---|---|
| MarketDataAgent | `MARKET_ANALYSIS` | indices, market status |
| StockAnalysisAgent | `STOCK_ANALYSIS` | one symbol's quote/news/filings/sentiment |
| NewsAgent | `NEWS_SUMMARY` | news corpus (optionally symbol-scoped) |
| AnnouncementAgent | `ANNOUNCEMENT_ANALYSIS` | PSX announcements for one symbol |
| SentimentAgent | `SENTIMENT_ANALYSIS` | headline-derived sentiment |
| PortfolioAgent | `PORTFOLIO_ANALYSIS` | portfolio tables only |
| ComparisonAgent | `STOCK_COMPARISON` | the named symbols only |

Task statuses follow the spec: `PENDING → RUNNING → COMPLETED | FAILED`, with
execution time and a redacted result summary (counts, model, citation count —
never portfolio values or the raw question).

## 5. Conversation storage model

```
conversations(id, user_id, title, context_snapshot, created_at, updated_at)
messages(id, conversation_id, role, content, context_used, citations,
         token_usage, model, processing_time_ms, created_at)
agent_tasks(id, conversation_id, task_type, agent_name, status, input_params,
            result, error, execution_time_ms, created_at, completed_at)
```

Context management: history is trimmed to `AI_MAX_CONVERSATION_MESSAGES`
(default 50) before prompting, and the prompt adds at most 10 prior exchanges
on top of the current context. `context_snapshot` preserves the view the
conversation started from; `citations` is persisted per answer so the source
panel survives a reload.

## 6. Security considerations

- **Keys stay server-side.** `AIProvider` is constructed only inside the
  controller; no endpoint returns a key, and `/status` reports provider names
  only.
- **Input validation.** `question` is `1..2000` chars; `temperature` is bounded
  `0..1`; conversation ids are looked up rather than trusted; `page_size` is
  clamped.
- **Portfolio gating.** Portfolio context is attached only for requests whose
  route requires it (`include_portfolio`) — i.e. a portfolio page. Task logs and
  metrics never contain holdings, P/L or the question text.
- **No prompt leakage.** The system prompt is only ever sent to the provider —
  never echoed to the client or into an error message.
- **User-safe errors.** `errors.public_error_message` never forwards provider
  text (which routinely contains payload fragments or endpoint paths).
- **URL discipline.** `citations.extract_citations` accepts `http(s)` only, so a
  model-influenced or malformed `javascript:` link can never reach an anchor.
- **XSS.** Assistant output is rendered by `lib/aiMarkdown.tsx`, which builds
  React elements from parsed text — no `dangerouslySetInnerHTML` anywhere.

## 7. Environment variables

```ini
# --- Phase 10: AI Financial Assistant ---
AI_PROVIDER=openai                  # openai | openrouter | anthropic
OPENAI_API_KEY=                     # required when AI_PROVIDER=openai
OPENAI_MODEL=gpt-4o-mini
OPENAI_TIMEOUT_SECONDS=60
OPENAI_MAX_TOKENS=4000
OPENROUTER_API_KEY=                 # required when AI_PROVIDER=openrouter
OPENROUTER_MODEL=anthropic/claude-3.5-sonnet
OPENROUTER_URL=https://openrouter.ai/api/v1
OPENROUTER_TIMEOUT_SECONDS=60
ANTHROPIC_API_KEY=                  # required when AI_PROVIDER=anthropic
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
ANTHROPIC_TIMEOUT_SECONDS=60
AI_MAX_CONVERSATION_MESSAGES=50
AI_CONTEXT_WINDOW_TOKENS=8000
AI_ENABLE_STREAMING=true
AI_ENABLE_VOICE=true
```

All optional in the sense that the app runs without them — the assistant then
reports "not configured" and the rest of the terminal is unaffected.

## 8. Provider configuration

- `AI_PROVIDER` selects the implementation in `get_ai_provider()`.
- Adding a provider = one class implementing `chat_completion`,
  `chat_completion_stream` and `get_model_name`, plus one line in the factory.
- OpenRouter uses the OpenAI-compatible client with a different `base_url`;
  Anthropic uses its native `/v1/messages` API, including streamed deltas.
- Errors are normalised by `ai/errors.classify_provider_error`, so provider
  specifics never reach the UI: authentication → `unavailable` (503),
  rate limit → `rate_limit` (429), timeout → `timeout` (504), other → `backend`
  (502).

## 9. Files created / modified

**Created**

```
backend/app/ai/citations.py            attributable source list
backend/app/ai/errors.py              provider error classification
backend/tests/test_phase10_ai_assistant.py   52 tests
frontend/src/lib/aiMarkdown.tsx        safe markdown-lite renderer
frontend/src/hooks/useChat.ts          send / stop / retry engine
frontend/src/hooks/useVoiceInput.ts    browser speech-to-text
frontend/src/utils/marketHours.ts      PSE session clock
frontend/scripts/assistant-audit.mjs   browser audit: dock, expanded, mobile,
                                       streaming, Stop, history, degraded backend
PHASE_10_AI_ASSISTANT.md               this report
```

**Rewritten**

```
backend/app/ai_controller.py           observability, citations, task history,
                                       ordered persistence, disconnect handling
backend/app/ai/prompt_builder.py       defensive context formatting (bug fixes),
                                       comparison section, labels + Sources rules
backend/app/ai/streaming_service.py    structured events instead of raw SSE strings
backend/app/ai/__init__.py             exports
backend/app/ai/agents.py               intent table, portfolio-family detection
backend/app/ai/context_builder.py      PKT session window fix, index price fix
frontend/src/lib/aiService.ts          real SSE reader, cancellation, error classes
frontend/src/store/useAIStore.ts       chat-session state (stop, retry, voice, expand)
frontend/src/hooks/useAIContext.ts     route/selection/page-type context + prompts
frontend/src/components/ai/*.tsx       the whole chat surface
frontend/src/Layout.tsx                docked rail + page gutter
frontend/index.css                     Phase 10 chat design system (~200 rules)
frontend/src/utils/dateFormat.ts       clock time + day grouping helpers
```

**Untouched by design:** every non-AI page, route, provider, news, portfolio and
screening module.

### Bugs found and fixed in the inherited Phase 10 code

1. **The entire chat UI was unstyled.** `components/ai/*` was written in
   Tailwind utility classes, but Tailwind is not part of this project's build
   (no dependency, no config, no PostCSS). Every panel rendered as raw
   flowed HTML — the "terminal" feel. The surface was rebuilt on the app's own
   CSS variables.
2. **Every market prompt failed to build.** `_format_context_data` read
   `idx_data['change_pct']`; the context builder emits `change_percent`. Any
   question asked from a market page raised `KeyError` inside prompt assembly.
3. **Every portfolio prompt failed to build.** Same class of bug:
   `h['value']` was read, holdings carry `market_value`.
4. **Market session was five hours wrong.** `_market_status()` compared the
   *PKT* clock against UTC-based open/close hours, so 02:00 PKT reported the
   exchange as OPEN.
5. **The stream dropped the conversation id.** No event carried
   `conversation_id`, so a client that did not pre-create the conversation could
   never load, rename or delete it.
6. **Stopping generation lost the answer.** There was no client-side abort at
   all (the SSE reader never returned a cancel handle), and the server had no
   partial-save path.
7. **The SSE reader guessed at events.** It ignored `event:` lines and inferred
   the event type from payload keys, so an `error` event whose payload happened
   to contain `content` was mis-treated as a chunk.
8. **`AgentRouter` was dead code.** The intent router and the seven agents were
   imported but never called; there was no task history. Intent classification
   now runs per request and records `agent_tasks` rows.
9. **Voice input was a stub** that always set "Voice input not available".
10. **`GET /ai/conversations/{id}` returned no stats** while the UI read
    `conv.stats`, so every history entry showed no message count.
11. **Every assistant call 404'd.** `VITE_API_URL` is a bare origin in this
    project (`http://127.0.0.1:8000`) and the rest of the app hands full
    `/api/...` paths to the shared axios client, but the AI service resolved
    `/ai/status` against that base. The header sat on "Checking assistant…", the
    provider was reported as unconfigured and every request went to a 404. All AI
    routes now go through one `aiUrl()` helper that adds the `/api` prefix — and
    never doubles it if a base already ends in `/api`. Found in the browser audit
    by asserting the real request log; there is now a check for it.
12. **Stop generating never released the UI.** The abort handle marked the stream
    finished *before* calling `abort()`, which swallowed the single `aborted`
    event the UI resets on: the Stop button stayed forever, no loader was
    cleared and the partial answer was not kept. The handle now aborts only, so
    the one terminal event still lands. Verified on the wire (the stream request
    is observed being aborted) and on screen (partial text kept, marked stopped).
13. **A backend that was down was blamed on a missing key.** The status fallback
    returned `available: false` for every failure, so a stopped API told the user
    to set `AI_PROVIDER`. Transport failures now carry `unreachable`, and the
    header reads "Backend unreachable" with its own notice; a recoverable state
    is re-checked every time the panel opens.

## 10. Test results

```
backend   python -m pytest -q
          609 passed, 4 warnings in 32.43s        (556 pre-existing + 53 new)

frontend  npx tsc --noEmit
          clean
          npx vite build
          ✓ built in 42.80s

browser   node scripts/assistant-audit.mjs
          63/63 checks passed                   (real Chrome, real backend)
```

The browser audit (`frontend/scripts/assistant-audit.mjs`, companion to
`page-audit.mjs`) drives a real Chrome over the DevTools Protocol against a real
backend and asserts what the user actually sees — 63 checks across: the launcher
and docked rail, the page gutter (header/main/footer content must clear the
dock), context chips and the "what is sent" panel, the empty state and suggested
prompts, a real streamed answer (structure, provenance chips, sources), Enter to
send, **Stop** (abort seen on the wire, partial text kept, no loader left),
conversation history loading, an in-place rename that also persists (with a
per-run title so a stale row can never make it pass), expanded reading mode +
backdrop + gutter restore, the mobile full-screen sheet, a **blocked status call**
to prove a down backend is reported as unreachable and then recovers, and console
/ exception / request hygiene. It writes screenshots of every state.

The 52 Phase 10 tests cover, with the provider and the DB session stubbed (no
network, no key):

- prompt assembly — market, portfolio, comparison, missing data, all 12 page
  types, and the regression cases for bugs 2 and 3;
- citation extraction — kinds, de-duplication, `javascript:` URL rejection,
  empty context, unavailable data, log-safe summary;
- error classification and its HTTP mapping, plus the "no provider internals in
  user-facing text" rule;
- the PSE session window pinned at five instants (including the 02:00 PKT case
  from bug 4);
- intent routing for ten questions, including the portfolio-phrasing case that
  the original keyword list missed;
- both answer paths end to end: happy path (with persisted row id + citations
  reaching the client), provider failure, empty answer, and a client **Stop**
  that must keep the partial text.

Manual verification performed during the build: typecheck and production build
of the frontend; import of the whole backend app; end-to-end streaming runs
against a stubbed provider for the happy, error and stop paths; and the browser
audit above run against a live backend with a stubbed model endpoint.

## 11. Known limitations

- **No provider key in this environment**, so no live model call was made here.
  Everything up to and including prompt assembly, provider invocation wiring and
  the response pipeline is exercised against a stubbed OpenAI-compatible
  endpoint (also behind the browser audit); a real key is needed to judge answer
  *quality* and true streaming latency.
- **Market status is a session window, not a feed.** Holidays are not modelled
  (`WEEKEND`/`OPEN`/`CLOSED` come from the 09:30–15:30 PKT weekday window), and
  the UI labels it as the session window rather than live market state.
- **Partial answers on a mid-stream disconnect are best-effort.** The client
  always keeps the text it has already rendered; the server-side recovery save
  can still lose a race if the connection dies at the same instant.
- **Portfolio authorization is single-tenant.** `PortfolioAgent` and
  `ContextBuilder` assume the one tenant the whole app already assumes; the
  `user_id` filter is present but inert until an auth layer lands.
- **Streaming interruption of the provider call itself** cannot be forwarded
  upstream for every provider — Anthropic and OpenAI streams are closed
  client-side when the request is cancelled.
- **Voice input depends on `SpeechRecognition`** (Chrome/Edge/Safari). Firefox
  reports it as unsupported, which the composer states plainly instead of
  failing.
- **Agent tasks log routing facts, not questions.** That is deliberate (privacy),
  but it means the task history is not a transcript — the conversation store is.
