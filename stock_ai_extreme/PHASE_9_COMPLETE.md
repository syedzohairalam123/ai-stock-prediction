# Phase 9: COMPLETE ✅ (verified)

Phase 9 — Professional Stock Discovery, Watchlist & Portfolio Engine — is fully
implemented on the backend and frontend, with every spec item (A–U) covered and
verified: **556 backend tests pass** (37 new for Phase 9), `tsc --noEmit` clean,
`npm run build` succeeds, and every endpoint was smoke-tested live against real
market data (real OGDC/PPL/HBL quotes through yfinance via the provider layer).

Nothing from Phases 1–8 was removed or changed in behavior.

## Phase 9 (ext) — professional-grade additions (nothing removed)

After a full audit, these engine-grade capabilities were added on top of the
complete Phase 9 (all computed from REAL data — real transaction log replayed
against real daily closes through the provider layer; no simulation anywhere):

1. **`GET /api/portfolio/performance`** — equity curve + risk metrics:
   day-by-day share counts replayed from the transaction log, priced with each
   symbol's REAL daily closes, summed into a portfolio value series. Metrics:
   **IRR** (Newton-Raphson on actual cash flows), **CAGR**, annualized
   **volatility**, **Sharpe ratio**, **Sortino ratio**, **Max Drawdown**, net
   P&L and net return %. A symbol the provider cannot price lands in
   `unavailable_symbols` — never faked (spec I/S preserved).
2. **Performance section on the dashboard** — dependency-free SVG area chart
   (theme-variable colors, dated axis, green/red by direction) + 8 metric
   cards (value, net P&L, IRR, CAGR, volatility, Sharpe, Sortino, max DD).
3. **Holdings table sorting** — every column sortable via accessible
   `aria-sort` headers; unpriced rows sink to the bottom in either direction.
4. **CSV export** — Holdings and (filtered) Transaction History export
   client-side using the existing `utils/csv.ts` (was defined but unused).
5. **Visible watchlist error banner on Popular page** — a failed add/remove
   now surfaces as a dismissible alert instead of dying in `console.error`
   (spec S: user-visible error handling).
6. **3 new backend tests** — curve math pinned (10 shares × rising closes →
   value 1090, invested 1000, net P&L 90, return 9%, max DD 0) and the
   unpriced-symbol honesty contract.


## Real bugs found and fixed in existing code (not style nits)

1. **FIFO engine discarded realized P&L.** `calculate_positions_fifo` computed
   realized P&L per sell and then overwrote it with `0.0  # simplified here`,
   so realized P&L was always reported as 0.00. Fixed: per-symbol accumulation
   carried into the final `Position`. Regression-tested (hand-checked:
   buy 100@100+50 fees, buy 100@120+50, sell 50@150−20 → realized = (150−100.5)×50−20 = **2455.00**).
2. **Popular stocks crashed whenever a trend existed.** `fetch_stock_data`
   used `pd.isna(...)` but imported pandas only inside a *different* function —
   any symbol with history rows raised `NameError` and its card silently
   vanished from the grid. The import now exists where it is used.
3. **"Day change" was measured against the close 10 days ago** (trend[-2])
   instead of the previous close. Fixed: change uses the quote's own
   `previous_close`; `previous_close` is now also returned in each card.
4. **Falsy-zero bugs:** `if change else None` and `if price else None` treated
   a genuine `0.00` change as missing. Only `None`/NaN is missing now.
5. **Weighted-average engine silently skipped oversells**, corrupting the
   position silently; both engines now clamp sells to holdings (never negative
   positions, spec H), with warnings logged.
6. **Nondeterministic FIFO ordering:** transactions on the same timestamp had
   no stable tiebreaker; now sorted by (date, id).
7. **Reorder appeared to do nothing:** `reorder_watchlist` read back inside the
   uncommitted session, returning pre-commit state; now reads after commit.
8. **NaN/Inf quantities/prices passed naive `<= 0` checks** and would poison
   every calculation; validation now rejects them explicitly.

## Backend

- `models.py` — `WatchlistItem` gained `sort_order` (additive migration applied
  automatically by `db._ensure_additive_columns`); `Transaction` unchanged.
- `portfolio_engine.py` — FIFO + weighted-average engines (realized P&L fixed,
  oversell clamping, stable ordering), `calculate_portfolio_summary` now
  reports unpriced positions with `price_available: false`,
  `unavailable_symbols`, `num_priced_positions` instead of silently skipping
  them; `validate_transaction` additionally rejects NaN/Inf values, missing
  dates, and future-dated transactions.
- `repository.py` — `reorder_watchlist`, `update_watchlist_note`,
  transaction `date_from`/`date_to` inclusive filtering.
- `popular_stocks.py` — bug fixes above + honest `unavailable` list and
  `requested` count in the response; no symbol is silently dropped.
- `main.py` routes:
  - `POST /api/watchlist/reorder` — persist manual order (sort_order 1..n)
  - `PATCH /api/watchlist/{ticker}` — set/clear note
  - `GET /api/watchlist/exists/{ticker}` — existence check
  - `GET /api/portfolio/transactions?symbol=&transaction_type=&date_from=&date_to=`
  - `GET /api/portfolio/positions|summary` — now include `price_status` per symbol
  - `POST /api/portfolio/transactions` — validates BUYs too (finite, past date)
- `tests/test_phase9_portfolio_engine.py` — 34 tests: one BUY, multiple BUYs,
  partial SELL, full SELL, no positions, large quantity, fees, unavailable
  price (incl. NaN), oversell clamp, full validation matrix, watchlist
  reorder/notes, route filters, popular-stocks regressions.

## Frontend

- `lib/finance.ts` (NEW) — centralized calculation utilities (spec G/J):
  `calculatePosition`, `calculateAverageCost`, `calculateInvestedCapital`,
  `calculateMarketValue`, `calculateUnrealizedPnl`, `calculateRealizedPnl`,
  `calculateTotalReturn`, `calculatePortfolioSummary`,
  `validateTransactionInput` (spec N), PKR formatting. Mirrors the backend
  engine exactly; NaN-safe everywhere.
- `lib/portfolioStorage.ts` (NEW) — persistence abstraction (spec E/Q):
  `WatchlistStorage` / `TransactionStorage` interfaces with **Backend** and
  **LocalStorage** adapters, `WatchlistService`, `TransactionService`,
  `PortfolioService` (auto local fallback with honest offline banner).
  Auth-ready (`userId` plumbed, single swap point for server sync).
- `hooks/usePortfolioQueries.ts` (NEW) — `useWatchlistItems` (add/remove/
  notes/reorder with optimistic update + search), `usePortfolioData`
  (transactions + live quotes through the same provider layer — spec P —
  computed holdings/summary), `useTransactionFilter` (side/symbol/date).
- `pages/PortfolioDashboardPage.tsx` — summary cards (spec K), holdings table
  (spec L) with **PRICE UNAVAILABLE** states and allocation, full transaction
  history with BUY/SELL/symbol/date filters and inline delete-confirm (spec M),
  Buy/Sell quick actions per holding, responsive tables (spec R).
- `pages/WatchlistPage.tsx` — full engine UI: search, editable notes,
  keyboard-accessible reorder (↑/↓ with optimistic persistence), priced rows,
  refresh-quote, honest unavailable states; row click → stock page, action
  buttons never navigate (spec B/O).
- `components/StockCard.tsx` — Enter/Space keyboard parity, zero-change fix,
  PRICE UNAVAILABLE for null price.
- `pages/PopularStocksPage.tsx` — per-symbol unavailability report (spec S).
- `components/AddTransactionModal.tsx` — rebuilt on the shared validation
  engine: per-field errors, SELL-vs-holdings guard, live total preview.
- Routing (spec O): `/portfolio/transactions` (engine), `/popular`,
  `/watchlist`, `/stock/:symbol` all cross-linked; header nav updated.

## Completion criteria (U) — status

| Item | Status |
|---|---|
| Popular stocks work | ✅ live-verified (real OGDC/PPL quotes + trends) |
| Watchlist works | ✅ add/remove/exists/list/reorder/search/notes |
| Persistence works | ✅ backend DB + local fallback adapter |
| Portfolio works | ✅ positions from transactions, live prices |
| BUY/SELL transactions work | ✅ validated, filterable, deletable |
| P/L calculations correct | ✅ hand-checked + regression tests |
| Validation works | ✅ spec N matrix, client + server |
| Current market prices integrate | ✅ one provider layer, no duplicate datasets |
| Responsive UI works | ✅ desktop/tablet/mobile rules appended |
| No TypeScript errors | ✅ `tsc --noEmit` clean |
| No console errors | ✅ silent-fallback interceptors; failures surface in UI |
| Previous phases functional | ✅ 519 pre-existing tests still pass |

STOP AFTER PHASE 9 — AI Assistant was not implemented, per instructions.
