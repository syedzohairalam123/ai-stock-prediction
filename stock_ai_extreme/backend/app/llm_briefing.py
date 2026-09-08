"""
Phase 14 — AI market briefing (optional, requires ANTHROPIC_API_KEY).

Turns structured data the app has ALREADY computed (price, indicators,
baseline comparison, cross-asset stats, ...) into a short plain-English
summary. The model is only ever handed real numbers already in that data
and instructed not to introduce new ones — this is narration, not a second
source of "facts". Skips cleanly (status "UNAVAILABLE") if no key is
configured, exactly like the Finnhub provider does; it never blocks the
rest of the app.

Uses `requests` directly against the Messages API rather than adding the
`anthropic` SDK as a dependency — one HTTP call doesn't need a whole SDK,
and it keeps this consistent with how the Finnhub provider is built.
"""
from __future__ import annotations

import json

import requests

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
# Configurable on purpose (see .env.example) — model names and IDs change
# over time; check https://docs.claude.com/en/docs/about-claude/models for
# the current lineup rather than trusting a hardcoded default forever.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = (
    "You write short, plain-English financial data summaries. You will be given a JSON object "
    "of numbers the application has already computed. Rules you must follow exactly:\n"
    "1. Only state numbers that literally appear in the JSON. Never invent, estimate, or round "
    "a figure that isn't there.\n"
    "2. Never predict a price or outcome beyond what the JSON's own forecast fields already say.\n"
    "3. Never give investment advice or tell the reader to buy or sell anything.\n"
    "4. If the JSON is sparse, write a shorter briefing rather than filling gaps with guesses.\n"
    "5. Plain prose, 3-5 sentences, no headers or bullet points."
)


def is_configured(api_key: str | None) -> bool:
    return bool(api_key)


def generate_briefing(structured_data: dict, api_key: str | None, model: str = DEFAULT_MODEL, timeout: float = 20.0) -> dict:
    if not is_configured(api_key):
        return {"status": "UNAVAILABLE", "reason": "ANTHROPIC_API_KEY not set", "text": None}

    payload = {
        "model": model,
        "max_tokens": 400,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": f"DATA:\n{json.dumps(structured_data, indent=2, default=str)}"}],
    }
    try:
        resp = requests.post(
            ANTHROPIC_API_URL,
            headers={"content-type": "application/json", "x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION},
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        return {"status": "ERROR", "reason": str(exc), "text": None}

    data = resp.json()
    text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
    if not text:
        return {"status": "ERROR", "reason": "Empty response from the model.", "text": None}
    return {"status": "OK", "text": text.strip(), "model": model}
