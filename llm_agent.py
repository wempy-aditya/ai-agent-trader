"""LLM proposal agent. Two backends: local Ollama or a remote HTTP API.

Whatever the backend, the output is forced into the strict ``p5.v1`` proposal shape.
The model never chooses its own symbol, timeframe, candle, or baseline signal, and its
order size is capped. A broken or unreachable backend degrades to HOLD with a reason.

This module never places an order and never touches the ledger.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

from remote_llm import (
    RemoteLLMConfig,
    RemoteLLMError,
    load_remote_config,
    parse_chat_json_proposal,
    parse_remote_proposal,
    remote_complete,
)

OLLAMA_HOST = "http://127.0.0.1:11434"
BACKEND_OLLAMA = "ollama"
BACKEND_REMOTE = "remote"
SCHEMA_KEYS = (
    "action",
    "baseline_signal",
    "candle_timestamp",
    "confidence",
    "invalid_conditions",
    "model_id",
    "quantity",
    "reason_codes",
    "reference_price",
    "schema_version",
    "signal_id",
    "symbol",
    "timeframe",
)
MAX_QUANTITY = 0.0002
MAX_NOTIONAL_FRACTION = 0.02
RULES = [
    'You are a cautious BTC spot trading assistant running in PAPER mode only.',
    "Return ONE JSON object and nothing else. No prose, no markdown fences.",
    "",
    "Required exact keys:",
    "",
    'Rules:',
    '- "schema_version" must be "p5.v1".',
    '- "symbol" must be "BTC". "timeframe" must be "1h".',
    '- "action" must be "hold" or "buy". Never sell, never short, never leverage.',
    '- For "hold": "quantity" and "reference_price" must both be 0.',
    '- For "buy": "quantity" and "reference_price" must both be positive numbers.',
    f'- "quantity" must be at most {MAX_QUANTITY} BTC.',
    f'- The buy notional must not exceed {int(MAX_NOTIONAL_FRACTION * 100)}% of equity.',
    '- "confidence" must be between 0 and 1.',
    '- "candle_timestamp", "symbol", "timeframe" and "baseline_signal" are given below; echo them exactly.',
    '- "reason_codes" and "invalid_conditions" are short snake_case strings, at least one in "reason_codes".',
    '- "signal_id" is a unique string. "model_id" is the model name given below.',
    "",
    "When unsure, answer hold with low confidence.",
]


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Pull the first complete JSON object out of arbitrary model output."""
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = [fence.group(1)] if fence else []
    depth = 0
    start = -1
    for index, char in enumerate(text):
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start >= 0:
                candidates.append(text[start : index + 1])
                start = -1
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _clamp(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return max(low, min(high, number))


def _clean_list(value: Any, fallback: list[str]) -> list[str]:
    if isinstance(value, list):
        items = [str(item).strip() for item in value if isinstance(item, (str, int, float)) and str(item).strip()]
        if items:
            return items
    return list(fallback)


class BaseAgent:
    """Shared sanitizer. Subclasses only supply raw model text."""

    model_id: str = "unknown"

    def build_schema_hint(self) -> tuple[str, ...]:
        return SCHEMA_KEYS

    def build_prompt(self, candle_timestamp: int, close: float, baseline_signal: str, context: dict[str, Any] | None = None) -> str:
        lines = list(RULES) + [
            "",
            "Market context:",
            f"candle_timestamp: {candle_timestamp}",
            f"last_closed_price: {close}",
            f"deterministic_baseline_signal: {baseline_signal}",
        ]
        for key, value in (context or {}).items():
            lines.append(f"{key}: {value}")
        return "\n".join(lines)

    def _sanitize(self, parsed: dict[str, Any] | None, invalid_conditions: list[str], candle_timestamp: int, close: float, baseline_signal: str, equity: float) -> dict[str, Any]:
        baseline = baseline_signal if baseline_signal in {"hold", "buy"} else "hold"
        payload: dict[str, Any] = {
            "schema_version": "p5.v1",
            "signal_id": f"llm-{candle_timestamp}",
            "candle_timestamp": candle_timestamp,
            "symbol": "BTC",
            "timeframe": "1h",
            "action": "hold",
            "quantity": 0.0,
            "reference_price": 0.0,
            "confidence": 0.0,
            "reason_codes": ["llm_unavailable"],
            "invalid_conditions": [],
            "baseline_signal": baseline,
            "model_id": self.model_id,
        }
        if parsed is None:
            payload["invalid_conditions"] = sorted(set(invalid_conditions)) or ["llm_output_unparseable"]
            return payload

        action = parsed.get("action")
        if action in {"hold", "buy"}:
            payload["action"] = action
        else:
            invalid_conditions.append("action_not_allowed")
        payload["confidence"] = _clamp(parsed.get("confidence"), 0.0, 1.0, 0.0)
        payload["reason_codes"] = _clean_list(parsed.get("reason_codes"), ["no_reason_given"])
        invalid_conditions.extend(_clean_list(parsed.get("invalid_conditions"), []))
        signal_id = parsed.get("signal_id")
        if isinstance(signal_id, str) and signal_id.strip():
            payload["signal_id"] = signal_id.strip()[:60]
        else:
            invalid_conditions.append("signal_id_missing")

        if payload["action"] == "buy":
            raw_quantity = parsed.get("quantity")
            requested = _clamp(raw_quantity, 0.0, MAX_QUANTITY * 1000.0, 0.0)
            if isinstance(raw_quantity, (int, float)) and float(raw_quantity) > MAX_QUANTITY:
                invalid_conditions.append("buy_quantity_capped")
            quantity = min(requested, MAX_QUANTITY)
            price = _clamp(parsed.get("reference_price"), 0.0, close * 1.5, 0.0) if close > 0 else 0.0
            if quantity <= 0 or price <= 0:
                payload["action"] = "hold"
                invalid_conditions.append("buy_fields_invalid")
            elif quantity * price > MAX_NOTIONAL_FRACTION * equity:
                payload["action"] = "hold"
                invalid_conditions.append("buy_notional_capped")
            else:
                payload["quantity"] = quantity
                payload["reference_price"] = price
        if payload["action"] == "hold":
            payload["quantity"] = 0.0
            payload["reference_price"] = 0.0
        payload["invalid_conditions"] = sorted(set(invalid_conditions))
        return payload

    def available(self) -> bool:
        return True

    def propose(self, candle_timestamp: int, close: float, baseline_signal: str, context: dict[str, Any] | None = None, equity: float = 1000.0) -> dict[str, Any]:
        raise NotImplementedError


class LocalLLMAgent(BaseAgent):
    """Local Ollama backend."""

    def __init__(self, model: str = "qwen2.5:7b", host: str = OLLAMA_HOST, timeout: float = 60.0, complete: Callable[[str, dict], str] | None = None):
        self.model = model
        self.model_id = model
        self.host = host.rstrip("/")
        self.timeout = timeout
        self._complete = complete or self._ollama_complete

    def _ollama_complete(self, prompt: str, options: dict) -> str:
        body = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": options.get("temperature", 0.2)},
        }).encode()
        request = Request(self.host + "/api/generate", data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode()).get("response", "")

    def available(self) -> bool:
        try:
            with urlopen(Request(self.host + "/api/tags", method="GET"), timeout=5) as response:
                return response.status == 200
        except (URLError, OSError):
            return False

    def propose(self, candle_timestamp: int, close: float, baseline_signal: str, context: dict[str, Any] | None = None, equity: float = 1000.0) -> dict[str, Any]:
        prompt = self.build_prompt(candle_timestamp, close, baseline_signal, context)
        invalid_conditions: list[str] = []
        parsed = None
        try:
            parsed = extract_json_object(self._complete(prompt, {"temperature": 0.2}))
        except (URLError, OSError, TimeoutError, ValueError) as exc:
            invalid_conditions.append(f"llm_unavailable:{type(exc).__name__}")
        if parsed is None:
            invalid_conditions.append("llm_output_unparseable")
        return self._sanitize(parsed, invalid_conditions, candle_timestamp, close, baseline_signal, equity)


class RemoteLLMAgent(BaseAgent):
    """Remote HTTP backend, either OpenAI-compatible chat or System One (Jev)."""

    def __init__(self, config: RemoteLLMConfig, complete: Callable[[str], str] | None = None):
        self.config = config
        self.model_id = config.model or "remote"
        self._complete = complete or (lambda prompt: remote_complete(config, prompt))

    def describe(self) -> dict[str, Any]:
        return self.config.redacted()

    def available(self) -> bool:
        return bool(self.config.api_key and self.config.model and self.config.base_url)

    def propose(self, candle_timestamp: int, close: float, baseline_signal: str, context: dict[str, Any] | None = None, equity: float = 1000.0) -> dict[str, Any]:
        prompt = self.build_prompt(candle_timestamp, close, baseline_signal, context)
        try:
            text = self._complete(prompt)
        except RemoteLLMError as exc:
            condition = "remote_error:" + str(exc).split(" ")[0].lower()
            if "https" in str(exc) or "empty" in str(exc):
                return self._sanitize(None, [condition], candle_timestamp, close, baseline_signal, equity)
            return self._sanitize(None, [condition], candle_timestamp, close, baseline_signal, equity)
        if self.config.dialect == "systemone":
            try:
                answers = json.loads(text) if isinstance(text, str) else dict(text)
            except json.JSONDecodeError:
                return self._sanitize(None, ["remote_output_unparseable"], candle_timestamp, close, baseline_signal, equity)
            payload = parse_remote_proposal(answers, dialect="systemone", candle_timestamp=candle_timestamp, close=close, baseline_signal=baseline_signal, model_id=self.model_id, equity=equity)
            return payload
        return parse_chat_json_proposal(text, candle_timestamp=candle_timestamp, close=close, baseline_signal=baseline_signal, model_id=self.model_id, equity=equity)


def build_agent(backend: str, model: str | None = None, config_path: str | None = None) -> BaseAgent:
    """Factory used by the CLI. `remote` reads the mode-600 config file."""
    if backend == BACKEND_REMOTE:
        return RemoteLLMAgent(load_remote_config(config_path) if config_path else load_remote_config())
    return LocalLLMAgent(model=model or "qwen2.5:7b")
