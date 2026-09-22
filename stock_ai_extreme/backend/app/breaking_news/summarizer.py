"""
AI summarization for breaking news (spec §17).

Two rules drive the design:

1. **AI must not invent missing facts.** The model is given only the publisher's
   own headline and lede and is asked for a one-paragraph summary of *that text*.
   Everything factual in the response — entities, numbers, event class — is
   extracted deterministically by regex/analytics from the same text and returned
   alongside the prose, so a reader can check the summary against the evidence.
   The prompt forbids outside knowledge and forbids stating numbers that are not
   in the supplied text.
2. **AI output is always labelled.** Every field carries
   ``is_ai_generated: true`` plus the model name and generation timestamp, and the
   API repeats "AI-generated" in the response. When no provider is configured the
   service reports UNAVAILABLE with the reason — it never falls back to a
   template that reads like a summary.

The provider is the one already configured for Phase 10
(:func:`..ai.providers.get_ai_provider`); no second key or client is introduced.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from ..logging_config import get_logger
from ..news_analytics import detect_event, extract_entities
from .entities import extract_market_entities
from .config import breaking_news_settings
from .timeutil import utcnow

logger = get_logger("neural_market.breaking_news.summarizer")

#: Numbers that matter in financial copy: percentages, basis points, index
#: points, and rounded currency/quantity magnitudes.
_NUMBER_PATTERN = re.compile(
    r"(?P<value>[-+]?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>%|percent|percentage points?|bps|basis points?|points?|"
    r"million|billion|trillion|crore|lakh|bn|mn|"
    r"USD|PKR|EUR|GBP|JPY|dollars?|rupees?)?",
    re.IGNORECASE,
)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)

SYSTEM_PROMPT = (
    "You are a financial news editor. You summarize ONLY the article text you are "
    "given. You never add facts, context, numbers, names or dates that are not "
    "present in that text. You never speculate about market direction or give "
    "investment advice. If the text is too short to summarize, say so plainly.\n\n"
    "Return strict JSON with exactly these keys:\n"
    '{"summary": "<2-3 sentence summary drawn only from the supplied text>", '
    '"event_classification": "<one of: EARNINGS, DIVIDEND, MERGER_ACQUISITION, '
    "RIGHT_ISSUE, REGULATORY, CONTRACT_AWARD, INSIDER, RATING, CAPITAL_INCREASE, "
    "MONETARY_POLICY, MACRO_DATA, MGMT_CHANGE, LEGAL, MARKET_UPDATE, GENERAL>\", "
    '"confidence": <number between 0 and 1>}'
)


@dataclass
class SummaryResult:
    """A labelled AI summary plus the deterministic evidence beside it."""

    status: str  # OK | UNAVAILABLE | DISABLED | SKIPPED
    summary: Optional[str] = None
    model: Optional[str] = None
    generated_at: Optional[Any] = None
    error: Optional[str] = None
    is_ai_generated: bool = True
    event_classification: Optional[str] = None
    key_entities: list[dict] = field(default_factory=list)
    key_numbers: list[dict] = field(default_factory=list)
    confidence: Optional[float] = None
    duration_ms: Optional[float] = None

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "summary": self.summary,
            "model": self.model,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "error": self.error,
            "is_ai_generated": self.is_ai_generated,
            "event_classification": self.event_classification,
            "key_entities": self.key_entities,
            "key_numbers": self.key_numbers,
            "confidence": self.confidence,
            "duration_ms": self.duration_ms,
            "label": "AI-generated summary — verify against the source article.",
        }


def extract_key_numbers(text: str, *, limit: int = 8) -> list[dict]:
    """Real numbers present in the text, with their unit — nothing inferred.

    A number is only returned when it genuinely appears in the supplied string;
    the function has no notion of a "typical" value to fall back on.
    """
    found: list[dict] = []
    seen: set[str] = set()
    for match in _NUMBER_PATTERN.finditer(text or ""):
        raw = match.group("value")
        unit = (match.group("unit") or "").strip()
        # Skip a bare year-like or list-number token with no unit and no
        # decimal, which is almost always prose rather than a datum.
        if not unit and "." not in raw and len(raw.replace(",", "")) > 4:
            continue
        key = f"{raw}|{unit.lower()}"
        if key in seen:
            continue
        seen.add(key)
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        found.append({"value": value, "raw": raw, "unit": unit or None})
        if len(found) >= limit:
            break
    return found


class AISummarizer:
    """Grounded, clearly-labelled summarization over one news event."""

    def __init__(self, settings: Any = None, *, provider: Any = None):
        self.settings = settings or breaking_news_settings
        self._provider = provider
        self._provider_resolved = provider is not None

    # ------------------------------------------------------------------

    def _get_provider(self) -> Any:
        if self._provider_resolved:
            return self._provider
        self._provider_resolved = True
        try:
            from ..ai.providers import get_ai_provider

            self._provider = get_ai_provider()
        except Exception as exc:  # no key configured, or provider misconfigured
            logger.info("AI summarization unavailable: %s", exc)
            self._provider = None
        return self._provider

    @property
    def available(self) -> bool:
        if not self.settings.enable_ai_summarization:
            return False
        return self._get_provider() is not None

    # ------------------------------------------------------------------

    async def summarize(
        self,
        *,
        title: str,
        excerpt: Optional[str] = None,
        publisher: Optional[str] = None,
        published_at: Optional[str] = None,
        breaking_score: Optional[float] = None,
        affected_entities: Optional[list[str]] = None,
    ) -> SummaryResult:
        """Summarize one event, or explain precisely why it was not summarized."""
        text = f"{title or ''}. {excerpt or ''}".strip()

        # Key entities are extracted deterministically — the PSX-validated set
        # plus the curated global instruments — never by the model, so a summary
        # can never introduce an entity that is not in the source text.
        key_entities = [e.as_dict() for e in extract_entities(text)]
        for entry in extract_market_entities(text):
            key_entities.append({
                "type": entry.entity_type,
                "value": entry.entity,
                "label": entry.matched,
            })
        evidence = {
            "event_classification": detect_event(text) or "GENERAL",
            "key_entities": key_entities[:10],
            "key_numbers": extract_key_numbers(text),
        }

        if not self.settings.enable_ai_summarization:
            return SummaryResult(status="DISABLED", error="AI summarization is disabled by configuration.", **evidence)

        if breaking_score is not None and breaking_score < float(self.settings.ai_summary_min_score):
            return SummaryResult(
                status="SKIPPED",
                error=(
                    f"Event score {breaking_score:.1f} is below the AI summarization "
                    f"threshold of {self.settings.ai_summary_min_score:.1f}."
                ),
                **evidence,
            )

        if not (excerpt or "").strip():
            return SummaryResult(
                status="SKIPPED",
                error="The publisher supplied no lede text, so there is nothing to summarize without inventing it.",
                **evidence,
            )

        provider = self._get_provider()
        if provider is None:
            return SummaryResult(
                status="UNAVAILABLE",
                error="No AI provider is configured (set OPENAI_API_KEY / ANTHROPIC_API_KEY, or AI_PROVIDER).",
                **evidence,
            )

        import time

        started = time.perf_counter()
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Headline: {title}\n"
                    f"Publisher: {publisher or 'unknown'}\n"
                    f"Published: {published_at or 'unknown'}\n"
                    f"Lede: {excerpt}\n\n"
                    "Summarize the text above only."
                ),
            },
        ]

        try:
            response = await provider.chat_completion(
                messages=messages,
                temperature=0.2,
                max_tokens=400,
            )
        except Exception as exc:
            logger.warning("AI summarization failed: %s", exc)
            return SummaryResult(
                status="UNAVAILABLE",
                error=f"AI provider error: {str(exc)[:300]}",
                duration_ms=(time.perf_counter() - started) * 1000.0,
                **evidence,
            )

        content = (response or {}).get("content") or ""
        parsed = self._parse(content)
        summary = (parsed.get("summary") or "").strip()
        if not summary:
            return SummaryResult(
                status="UNAVAILABLE",
                error="AI provider returned no usable summary.",
                model=response.get("model") if isinstance(response, dict) else None,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                **evidence,
            )

        # The event class is always the deterministic one from
        # ``news_analytics.detect_event``. The model's own label is deliberately
        # ignored rather than merged: a classification that a reader can
        # reproduce from the text must not be overridable by prose.
        classification = evidence["event_classification"]

        confidence = parsed.get("confidence")
        try:
            confidence = max(0.0, min(float(confidence), 1.0)) if confidence is not None else None
        except (TypeError, ValueError):
            confidence = None

        return SummaryResult(
            status="OK",
            summary=summary[: self.settings.ai_summary_max_length * 4],
            model=(response or {}).get("model") or getattr(provider, "get_model_name", lambda: None)(),
            generated_at=utcnow(),
            event_classification=classification,
            key_entities=evidence["key_entities"],
            key_numbers=evidence["key_numbers"],
            confidence=confidence,
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )

    @staticmethod
    def _parse(content: str) -> dict:
        """Parse the model's JSON, tolerating the prose/markdown models add."""
        if not content:
            return {}
        try:
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass
        match = _JSON_BLOCK.search(content)
        if match:
            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        # Not JSON at all — treat the raw text as the summary rather than throw
        # away a usable answer.
        return {"summary": content.strip()}


__all__ = ["AISummarizer", "SummaryResult", "extract_key_numbers"]
