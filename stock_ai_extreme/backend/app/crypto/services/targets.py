"""
Target service (spec §32–§40, §44, §70–§72).

Reads real candles through the market service and turns them into:

  * an evaluated target list (status, proximity, observed touches) for a symbol;
  * a derived reference ladder built from real historical swing structure;
  * threshold probability analyses (delegated to :mod:`app.crypto.thresholds`);
  * factual "was the price above X on date Y?" answers (spec §35).

Status changes are persisted together with a *target event* recording the real
observation that caused them, so a target's timeline is auditable and can never
be advanced by a client click (spec §34).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.crypto import repositories as repo
from app.crypto import targets as targets_mod
from app.crypto import thresholds as thresholds_mod
from app.crypto.config import crypto_settings
from app.crypto.schemas import DataStatus, PriceTarget, TargetStatus, ValueOrigin

logger = logging.getLogger("neural_market.crypto.services.targets")


class TargetService:
    """Analytical milestones, thresholds and date queries over real history."""

    def __init__(self, manager, market_service) -> None:
        self.manager = manager
        self.market = market_service

    # -------------------------------------------------------------------- create
    async def create(
        self,
        *,
        symbol: str,
        target_price: float,
        direction: str,
        target_date: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        asset = self.manager.resolve(symbol)
        price, resolved_direction, resolved_date = targets_mod.validate_target_inputs(
            target_price=target_price, direction=direction, target_date=target_date
        )
        if repo.count_targets(asset.internal) >= crypto_settings.max_targets_per_symbol:
            return {
                "status": "REJECTED",
                "reason": (
                    f"symbol already has {crypto_settings.max_targets_per_symbol} targets "
                    "(CRYPTO_MAX_TARGETS_PER_SYMBOL)"
                ),
            }

        target = targets_mod.build_target(
            symbol=asset.internal,
            target_price=price,
            direction=resolved_direction,
            target_date=resolved_date,
            source="user",
            methodology="User-defined analytical milestone (not a forecast).",
            notes=notes,
        )
        repo.create_target(target.to_dict())

        # Evaluate immediately against real history so the created target already
        # carries its observed status rather than a claimed one.
        evaluation = await self._evaluate_one(target, asset.internal)
        if evaluation.get("data_status") == "UNAVAILABLE":
            return {
                "status": "REJECTED",
                "reason": "no real candle history available to evaluate this target; "
                "it was not created (status cannot be verified from data)",
            }
        repo.record_target_event(
            {
                "target_id": target.id,
                "symbol": asset.internal,
                "event_type": "CREATED",
                "status": evaluation["status"],
                "observed_price": evaluation.get("current_price"),
                "observed_at": self._now(),
                "source": evaluation.get("source"),
                "detail": {
                    "target_price": target.target_price,
                    "direction": target.direction,
                    "touch_count": evaluation.get("touch_count"),
                },
            }
        )
        if evaluation["status"] != target.status.value:
            repo.update_target(
                target.id,
                status=evaluation["status"],
                first_reached_at=evaluation.get("first_reached_at_dt"),
            )
        # Keep the envelope status (CREATED) separate from the evaluated milestone
        # status (ACTIVE/REACHED/...) — the latter rides on `target` and `target_status`.
        return {
            "status": "CREATED",
            "origin": ValueOrigin.SOURCE.value,
            "target": evaluation["target"],
            "target_status": evaluation["status"],
            "touch_count": evaluation.get("touch_count"),
            "crossing_count": evaluation.get("crossing_count"),
            "last_touched_at": evaluation.get("last_touched_at"),
            "proximity": evaluation.get("proximity"),
            "current_price": evaluation.get("current_price"),
            "source": evaluation.get("source"),
            "data_status": evaluation.get("data_status"),
            "note": evaluation.get("note"),
        }

    async def invalidate(self, target_id: str) -> Dict[str, Any]:
        """Explicitly retire a target (the only status a client may set)."""
        existing = repo.get_target(target_id)
        if existing is None:
            return {"status": "NOT_FOUND", "target_id": target_id}
        repo.update_target(target_id, status=TargetStatus.INVALIDATED.value)
        repo.record_target_event(
            {
                "target_id": target_id,
                "symbol": existing["symbol"],
                "event_type": "INVALIDATED",
                "status": TargetStatus.INVALIDATED.value,
                "observed_at": self._now(),
                "detail": {"reason": "explicit user invalidation"},
            }
        )
        return {"status": "INVALIDATED", "target_id": target_id}

    # ---------------------------------------------------------------------- read
    async def list_for_symbol(
        self,
        symbol: str,
        *,
        include_derived: bool = True,
        lookback_days: Optional[int] = None,
    ) -> Dict[str, Any]:
        asset = self.manager.resolve(symbol)
        bundle = await self.market.load_series(asset.internal, "1h")
        candles = bundle.candles
        current_price = candles[-1].close if candles else None

        stored = repo.list_targets(symbol=asset.internal)
        evaluated: List[Dict[str, Any]] = []
        for row in stored:
            target = PriceTarget(
                id=row["id"],
                symbol=row["symbol"],
                target_price=row["target_price"],
                direction=row["direction"],
                target_date=_parse(row.get("target_date")),
                created_at=_parse(row.get("created_at")) or self._now(),
                source=row["source"],
                methodology=row["methodology"],
                status=TargetStatus(row["status"]),
                first_reached_at=_parse(row.get("first_reached_at")),
                notes=row.get("notes"),
            )
            result = targets_mod.evaluate_target(
                target,
                candles=candles,
                current_price=current_price,
                lookback_days=lookback_days,
            )
            # Persist a status change discovered from real data (with its evidence).
            if result["status"] != row["status"] and row["status"] != TargetStatus.INVALIDATED.value:
                # The event timestamp is the REAL observation that caused the
                # change (e.g. the first bar that touched the level), not now().
                observed_at = _parse(result.get("first_reached_at")) or self._now()
                repo.update_target(
                    target.id,
                    status=result["status"],
                    first_reached_at=_parse(result.get("first_reached_at")),
                )
                repo.record_target_event(
                    {
                        "target_id": target.id,
                        "symbol": asset.internal,
                        "event_type": "STATUS_CHANGED",
                        "status": result["status"],
                        "observed_price": current_price,
                        "observed_at": observed_at,
                        "source": bundle.series.source,
                        "detail": {
                            "previous_status": row["status"],
                            "touch_count": result.get("touch_count"),
                        },
                    }
                )
            evaluated.append(result)

        ladder = (
            targets_mod.derive_reference_ladder(candles, current_price=current_price)
            if include_derived
            else []
        )
        return {
            "symbol": asset.internal,
            "current_price": current_price,
            "source": bundle.series.source,
            "data_status": bundle.data_status.value,
            "targets": evaluated,
            "active_count": sum(1 for t in evaluated if t["status"] == TargetStatus.ACTIVE.value),
            "reached_count": sum(1 for t in evaluated if t["status"] == TargetStatus.REACHED.value),
            "derived_ladder": ladder,
            "lookback_days": lookback_days or crypto_settings.target_touch_lookback_days,
            "note": (
                "Stored targets are analytical milestones the user recorded. The derived ladder "
                "contains real historical swing levels (support/resistance) — observations, not "
                "forecasts."
            ),
            "origin": ValueOrigin.CALCULATED.value,
        }

    def events(self, target_id: str) -> Dict[str, Any]:
        rows = repo.target_events(target_id)
        return {
            "target_id": target_id,
            "count": len(rows),
            "events": rows,
            "origin": ValueOrigin.CALCULATED.value,
        }

    # ----------------------------------------------------------------- thresholds
    async def threshold(
        self,
        *,
        symbol: str,
        timeframe_id: Optional[str],
        threshold: float,
        horizon: Optional[int] = None,
        direction: str = "above",
    ) -> Dict[str, Any]:
        asset = self.manager.resolve(symbol)
        bundle = await self.market.load_series(asset.internal, timeframe_id)
        resolved_horizon = horizon or crypto_settings.default_horizon
        result = thresholds_mod.threshold_analysis(
            symbol=asset.internal,
            timeframe=bundle.timeframe.id,
            candles=bundle.candles,
            threshold=threshold,
            horizon=resolved_horizon,
            direction=direction,
        )
        result["source"] = bundle.series.source
        result["candles_used"] = len(bundle.candles)
        return result

    async def on_date(
        self,
        *,
        symbol: str,
        date: str,
        threshold: Optional[float] = None,
        direction: str = "above",
    ) -> Dict[str, Any]:
        """
        Factual historical query (spec §35).

        Without a threshold this answers "what did the price do that day?";
        with one it answers "was it above/below X?" — in both cases from a real
        observation or ``UNAVAILABLE``.
        """
        asset = self.manager.resolve(symbol)
        parsed = targets_mod.validate_target_inputs(
            target_price=threshold if threshold is not None else 1.0,
            direction=direction,
            target_date=date,
        )[2]
        if parsed is None:
            raise targets_mod.TargetError("date is required")

        # Daily candles are the correct resolution for a calendar-day question.
        bundle = await self.market.load_series(asset.internal, "1d", limit=500)
        if threshold is None:
            observation = targets_mod.price_on_date(bundle.candles, date=parsed)
            observation["symbol"] = asset.internal
            observation["source"] = bundle.series.source
            return observation
        answer = targets_mod.evaluate_threshold_on_date(
            bundle.candles, date=parsed, threshold=float(threshold), direction=direction
        )
        answer["symbol"] = asset.internal
        answer["source"] = bundle.series.source
        return answer

    async def reference_ladder(self, symbol: str, *, count: Optional[int] = None) -> Dict[str, Any]:
        asset = self.manager.resolve(symbol)
        bundle = await self.market.load_series(asset.internal, "4h", limit=1000)
        current_price = bundle.candles[-1].close if bundle.candles else None
        ladder = targets_mod.derive_reference_ladder(
            bundle.candles, current_price=current_price, count=count
        )
        return {
            "symbol": asset.internal,
            "current_price": current_price,
            "source": bundle.series.source,
            "levels": ladder,
            "count": len(ladder),
            "note": "Derived from real local extrema in the 4h candle history.",
            "origin": ValueOrigin.DERIVED.value,
        }

    # ------------------------------------------------------------------- helpers
    async def _evaluate_one(self, target: PriceTarget, symbol: str) -> Dict[str, Any]:
        bundle = await self.market.load_series(symbol, "1h")
        candles = bundle.candles
        current_price = candles[-1].close if candles else None
        result = targets_mod.evaluate_target(target, candles=candles, current_price=current_price)
        result["current_price"] = current_price
        result["source"] = bundle.series.source
        result["data_status"] = bundle.data_status.value
        first = result.get("first_reached_at")
        result["first_reached_at_dt"] = _parse(first)
        return result

    @staticmethod
    def _now() -> datetime:
        from datetime import timezone

        return datetime.now(timezone.utc)


def _parse(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
