"""Entry-mode agent: the model proposes, code decides whether entry is allowed.

The first replay showed the LLM never buys: conservative model, plus a baseline
signal that fires on 0.91% of bars, equals zero trades. More indicators will not
fix that.

This module moves the entry decision into deterministic code. The model still
explains and still proposes, but a BUY only survives when code-computed criteria
agree. The point is to find out whether the model can act at all when the bar for
entry is raised in a way it can see.

The safety ceiling is unchanged: BTC, 1h, long only, capped size, and the same
schema validator downstream.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from llm_agent import MAX_NOTIONAL_FRACTION, MAX_QUANTITY, extract_json_object

RSI_MIN = 45.0
RSI_MAX = 70.0

EXIT_RULES = [
    "ema_bearish: ema20 is below ema50",
    "price_below_ema50: close is below ema50",
    "stop_hit: close is more than 2% below your entry price",
]


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def _flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    number = _num(value)
    return bool(number) if number is not None else False


def entry_criteria(context: dict[str, Any] | None) -> dict[str, bool]:
    """Code-side entry gate. Every rule must be true for a BUY to pass.

    A missing indicator counts as false on purpose: an unknown is not a yes.
    """
    ctx = context or {}
    spread = _num(ctx.get("ema_spread_pct"))
    rsi14 = _num(ctx.get("rsi14"))
    momentum = _num(ctx.get("return_4"))

    return {
        "ema_spread_positive": spread is not None and spread > 0,
        "price_above_ema20": _flag(ctx.get("closes_above_ema20")),
        "rsi_in_band": rsi14 is not None and RSI_MIN <= rsi14 <= RSI_MAX,
        "not_overbought": rsi14 is not None and rsi14 < RSI_MAX,
        "momentum_positive": momentum is not None and momentum > 0,
    }


def build_exit_criteria(context: dict[str, Any] | None, has_position: bool = False, entry_price: float | None = None) -> dict[str, bool]:
    ctx = context or {}
    spread = _num(ctx.get("ema_spread_pct"))
    close = _num(ctx.get("close"))
    below_ema50 = not _flag(ctx.get("closes_above_ema50")) if ctx.get("closes_above_ema50") is not None else False
    stop_hit = False
    if has_position and entry_price and close is not None:
        stop_hit = close < entry_price * 0.98
    return {
        "ema_bearish": (spread is not None and spread < 0) or below_ema50,
        "price_below_ema50": below_ema50,
        "stop_hit": stop_hit,
    }


class EntryModeAgent:
    """Wraps any LLM backend with a deterministic entry/exit gate."""

    def __init__(self, model_id: str = "entry-mode", complete: Callable[[str], str] | None = None):
        self.model_id = model_id
        self._complete = complete

    def available(self) -> bool:
        return self._complete is not None

    def build_criteria(self, context: dict[str, Any] | None) -> dict[str, bool]:
        return entry_criteria(context)

    def build_exit_criteria(self, context: dict[str, Any] | None, has_position: bool = False, entry_price: float | None = None) -> dict[str, bool]:
        return build_exit_criteria(context, has_position, entry_price)

    def should_force_exit(self, exits: dict[str, bool]) -> bool:
        return bool(exits.get("ema_bearish") or exits.get("stop_hit"))

    def build_prompt(self, candle_timestamp: int, close: float, baseline_signal: str, context: dict[str, Any] | None = None) -> str:
        criteria = entry_criteria(context)
        exits = build_exit_criteria(context, bool((context or {}).get("has_position")))
        lines = [
            "You are a BTC spot trading assistant running in PAPER mode.",
            "Return ONE JSON object, no prose, no markdown fences.",
            "Required keys: schema_version, signal_id, candle_timestamp, symbol, timeframe,",
            "action, quantity, reference_price, confidence, reason_codes, invalid_conditions,",
            "baseline_signal, model_id.",
            'schema_version="p5.v1", symbol="BTC", timeframe="1h", signal_id must be unique.',
            "action is one of: hold, buy, sell.",
            "  buy  only opens a long position; it requires an open_position=false context.",
            "  sell only closes an open long position; it requires an open_position=true context.",
            "  hold means keep the current position, which may be nothing.",
            "For hold and sell, quantity and reference_price must both be 0.",
            "For buy, both must be positive and quantity at most 0.0002 BTC,",
            f"and the notional must not exceed {int(MAX_NOTIONAL_FRACTION * 100)}% of equity.",
            "confidence is between 0 and 1.",
            "reason_codes are short snake_case strings describing your decision.",
            "",
            "The entry_criteria below are computed by the risk system, not by you.",
            "If every entry_criteria value is true, a buy is permitted and you should",
            "consider it. If any is false, a buy will be rejected, so answer hold or sell.",
            "",
            "entry_criteria: " + json.dumps(criteria, sort_keys=True),
            "exit_criteria: " + json.dumps(exits, sort_keys=True),
            "",
            "Market context:",
            "candle_timestamp: " + str(candle_timestamp),
            "last_closed_price: " + str(close),
            "deterministic_baseline_signal: " + str(baseline_signal),
            "indicators: " + json.dumps(context or {}, sort_keys=True),
        ]
        return "\n".join(lines)

    def _base(self, candle_timestamp: int, baseline_signal: str) -> dict[str, Any]:
        return {
            "schema_version": "p5.v1",
            "signal_id": f"entry-{candle_timestamp}",
            "candle_timestamp": candle_timestamp,
            "symbol": "BTC",
            "timeframe": "1h",
            "action": "hold",
            "quantity": 0.0,
            "reference_price": 0.0,
            "confidence": 0.0,
            "reason_codes": ["no_answer"],
            "invalid_conditions": [],
            "baseline_signal": baseline_signal if baseline_signal in {"hold", "buy", "sell"} else "hold",
            "model_id": self.model_id,
        }

    def propose(
        self,
        candle_timestamp: int,
        close: float,
        baseline_signal: str,
        context: dict[str, Any] | None = None,
        equity: float = 1000.0,
        has_position: bool = False,
        entry_price: float | None = None,
    ) -> dict[str, Any]:
        payload = self._base(candle_timestamp, baseline_signal)
        ctx = dict(context or {})
        ctx["has_position"] = has_position
        criteria = entry_criteria(ctx)
        exits = build_exit_criteria(ctx, has_position, entry_price)
        allowed = all(criteria.values())

        if self._complete is None:
            payload["reason_codes"] = ["entry_mode_no_backend"]
            payload["invalid_conditions"] = ["llm_unavailable"]
            return payload

        try:
            raw = self._complete(self.build_prompt(candle_timestamp, close, baseline_signal, ctx))
        except Exception as exc:  # noqa: BLE001 - transport failure must not crash the loop
            payload["reason_codes"] = ["llm_unavailable"]
            payload["invalid_conditions"] = [f"remote_error:{type(exc).__name__}".lower()]
            return payload

        parsed = extract_json_object(raw or "")
        if not isinstance(parsed, dict):
            payload["reason_codes"] = ["llm_output_unparseable"]
            payload["invalid_conditions"] = ["llm_output_unparseable"]
            return payload

        conditions: list[str] = []
        reasons: list[str] = [r for r in (parsed.get("reason_codes") or []) if isinstance(r, str)][:6]

        action = str(parsed.get("action", "")).strip().lower()
        confidence = parsed.get("confidence", 0.0)
        try:
            confidence_value = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            confidence_value = 0.0
        payload["confidence"] = confidence_value
        signal_id = parsed.get("signal_id")
        if isinstance(signal_id, str) and signal_id.strip():
            payload["signal_id"] = signal_id.strip()[:60]

        forced_exit = has_position and self.should_force_exit(exits)

        if action == "sell":
            if not has_position:
                action = "hold"
                conditions.append("sell_without_position")
        elif action == "buy":
            if has_position:
                action = "hold"
                conditions.append("buy_with_position")
            elif not allowed:
                action = "hold"
                conditions.append("entry_criteria_not_met")
            else:
                try:
                    quantity = min(float(parsed.get("quantity") or 0.0), MAX_QUANTITY)
                except (TypeError, ValueError):
                    quantity = 0.0
                try:
                    price = float(parsed.get("reference_price") or 0.0)
                except (TypeError, ValueError):
                    price = 0.0
                if quantity <= 0 or price <= 0:
                    action = "hold"
                    conditions.append("buy_fields_invalid")
                elif quantity * price > MAX_NOTIONAL_FRACTION * equity:
                    action = "hold"
                    conditions.append("buy_notional_capped")
                else:
                    payload["quantity"] = quantity
                    payload["reference_price"] = price
        elif action not in {"hold"}:
            action = "hold"
            conditions.append("action_not_allowed")

        if forced_exit and action == "hold":
            action = "sell"
            reasons.append("forced_exit_bearish_flip")

        payload["action"] = action
        if action in {"hold", "sell"}:
            payload["quantity"] = 0.0
            payload["reference_price"] = 0.0
        payload["reason_codes"] = [r for r in reasons if r.strip()][:6] or ["no_reason_given"]
        payload["invalid_conditions"] = sorted(set(conditions))
        return payload