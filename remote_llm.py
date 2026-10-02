"""Remote LLM client. User supplies API URL, API key and model by hand.

Two dialects are supported, matching the local decision-model client used by the
mini-games project:

  - ``openai``     any OpenAI-compatible ``/v1/chat/completions`` endpoint.
  - ``systemone``  TypeSafe Jev ``/v1/systemone``: typed questions in, typed
                   answers with calibrated confidence out.

Security rules that are not configurable:

- credentials live in a local file that must be mode ``600``;
- remote endpoints must be ``https`` unless they are loopback addresses;
- an API key is never included in an error message or a log line;
- the API key is never written into the evidence or audit records.

Whatever the model answers, the returned payload is a proposal for the same strict
``p5.v1`` schema the local agent uses. Identity fields are forced by this module.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MAX_QUANTITY = 0.0002
MAX_NOTIONAL_FRACTION = 0.02
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
CONFIG_PATH = Path.home() / ".config/ai-trader/llm-remote.json"

SYSTEM_PROMPT = (
    "You are a cautious BTC spot trading assistant in PAPER mode. "
    "Reply with ONE JSON object and no prose, no markdown fences, no explanation. "
    "Exact keys required: schema_version, signal_id, candle_timestamp, symbol, timeframe, "
    "action, quantity, reference_price, confidence, reason_codes, invalid_conditions, "
    "baseline_signal, model_id. "
    'Rules: schema_version="p5.v1"; symbol="BTC"; timeframe="1h"; '
    'action is "hold" or "buy" only, never sell, never short, never leverage; '
    "for hold, quantity and reference_price must both be 0; "
    "for buy both must be positive and quantity at most 0.0002 BTC; "
    "confidence between 0 and 1; reason_codes and invalid_conditions are short snake_case strings. "
    "When unsure answer hold with low confidence."
)


class RemoteLLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemoteLLMConfig:
    dialect: str = "openai"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    temperature: float = 0.2
    max_tokens: int = 400
    timeout: float = 45.0
    enabled: bool = True

    def redacted(self) -> dict[str, Any]:
        return {
            "dialect": self.dialect,
            "base_url": self.base_url,
            "api_key": "[REDACTED]",
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "enabled": self.enabled,
        }


def normalize_base_url(url: str) -> str:
    return str(url or "").strip().rstrip("/").removesuffix("/v1").rstrip("/")


def _endpoint(cfg: RemoteLLMConfig) -> str:
    base = normalize_base_url(cfg.base_url)
    if not base:
        raise RemoteLLMError("base_url is empty")
    if not base.startswith("https://"):
        host = base.split("://", 1)[-1].split("/", 1)[0].split(":")[0]
        if host not in LOOPBACK_HOSTS:
            raise RemoteLLMError("remote endpoint must use https")
    if cfg.dialect == "systemone":
        return base + "/v1/systemone"
    return base + "/v1/chat/completions"


def load_remote_config(path: str | Path = CONFIG_PATH) -> RemoteLLMConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise RemoteLLMError(f"missing config file: {config_path}")
    if config_path.stat().st_mode & 0o077:
        raise RemoteLLMError(f"config file must be mode 600: {config_path}")
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    return RemoteLLMConfig(
        dialect=str(payload.get("dialect", "openai")),
        base_url=str(payload.get("base_url", "")),
        api_key=str(payload.get("api_key", "")),
        model=str(payload.get("model", "")),
        temperature=float(payload.get("temperature", 0.2)),
        max_tokens=int(payload.get("max_tokens", 400)),
        timeout=float(payload.get("timeout", 45.0)),
        enabled=bool(payload.get("enabled", True)),
    )


def save_remote_config(cfg: RemoteLLMConfig, path: str | Path = CONFIG_PATH) -> Path:
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(cfg.redacted() if not cfg.api_key else {
        "dialect": cfg.dialect,
        "base_url": cfg.base_url,
        "api_key": cfg.api_key,
        "model": cfg.model,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "timeout": cfg.timeout,
        "enabled": cfg.enabled,
    }, indent=2), encoding="utf-8")
    config_path.chmod(0o600)
    return config_path


def build_chat_request(system: str, user: str, cfg: RemoteLLMConfig) -> dict[str, Any]:
    return {
        "model": cfg.model,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }


def build_systemone_request(state: str, questions: dict[str, Any], cfg: RemoteLLMConfig) -> dict[str, Any]:
    return {"state": state, "model": cfg.model, "questions": questions}


def extract_chat_text(data: dict[str, Any]) -> str:
    choices = (data or {}).get("choices") or []
    if not choices:
        return ""
    content = (choices[0].get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part if isinstance(part, str) else (part or {}).get("text", "") for part in content)
    return ""


def _clamp(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:
        return default
    return max(low, min(high, number))


def _safe_name(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()[:60]
    return fallback


def _base_payload(candle_timestamp: int, close: float, baseline_signal: str, model_id: str) -> dict[str, Any]:
    return {
        "schema_version": "p5.v1",
        "signal_id": f"remote-{candle_timestamp}",
        "candle_timestamp": candle_timestamp,
        "symbol": "BTC",
        "timeframe": "1h",
        "action": "hold",
        "quantity": 0.0,
        "reference_price": 0.0,
        "confidence": 0.0,
        "reason_codes": ["remote_no_answer"],
        "invalid_conditions": [],
        "baseline_signal": baseline_signal if baseline_signal in {"hold", "buy"} else "hold",
        "model_id": model_id,
    }


def _finalize(payload: dict[str, Any], action: str, confidence: float, equity: float, quantity: float, close: float, reasons: list[str], conditions: list[str]) -> dict[str, Any]:
    if action not in {"hold", "buy"}:
        conditions.append("action_not_allowed")
        reasons.append(f"rejected_action_{str(action)[:24]}")
    payload["action"] = action if action in {"hold", "buy"} else "hold"
    payload["confidence"] = _clamp(confidence, 0.0, 1.0, 0.0)
    payload["reason_codes"] = [r for r in reasons if isinstance(r, str) and r.strip()][:6] or ["no_reason_given"]
    if payload["action"] == "hold":
        payload["quantity"] = 0.0
        payload["reference_price"] = 0.0
    else:
        raw_quantity = quantity
        bounded_qty = min(_clamp(raw_quantity, 0.0, MAX_QUANTITY * 1000.0, 0.0), MAX_QUANTITY)
        if isinstance(raw_quantity, (int, float)) and float(raw_quantity) > MAX_QUANTITY:
            conditions.append("buy_quantity_capped")
        price = _clamp(close, 0.0, close * 1.5, 0.0) if close > 0 else 0.0
        if bounded_qty <= 0 or price <= 0:
            payload["action"] = "hold"
            conditions.append("buy_fields_invalid")
        elif bounded_qty * price > MAX_NOTIONAL_FRACTION * equity:
            payload["action"] = "hold"
            conditions.append("buy_notional_capped")
        else:
            payload["quantity"] = bounded_qty
            payload["reference_price"] = price
        if payload["action"] == "hold":
            payload["quantity"] = 0.0
            payload["reference_price"] = 0.0
    payload["invalid_conditions"] = sorted(set(conditions))
    return payload


def parse_remote_proposal(answers: dict[str, Any], dialect: str, candle_timestamp: int, close: float, baseline_signal: str, model_id: str, equity: float = 1000.0, quantity: float | None = None) -> dict[str, Any]:
    payload = _base_payload(candle_timestamp, close, baseline_signal, model_id)
    conditions: list[str] = []
    reasons: list[str] = []
    confidence = 0.0

    action_answer = (answers or {}).get("action") or {}
    if isinstance(action_answer, dict):
        action = str(action_answer.get("choice", "")).strip().lower()
        confidence = _clamp(action_answer.get("confidence", 0.0), 0.0, 1.0, 0.0)
        probs = action_answer.get("probabilities")
        if isinstance(probs, dict) and action:
            for key, value in probs.items():
                reasons.append(f"p_{str(key).lower().replace(' ', '_')}_{round(float(value), 2)}")
    else:
        action = "hold"
        conditions.append("answer_shape_unexpected")

    noul_answer = (answers or {}).get("confidence")
    if isinstance(noul_answer, dict) and "noul" in noul_answer:
        confidence = _clamp(noul_answer.get("noul", confidence), 0.0, 1.0, confidence)

    if action == "hold":
        reasons = reasons + ["remote_hold"]
    elif action not in {"buy"}:
        conditions.append("action_not_allowed")
        reasons.append(f"rejected_action_{action[:24]}")

    qty = quantity if quantity is not None else (MAX_QUANTITY / 4)
    payload = _finalize(payload, action, confidence, equity, qty, close, reasons, conditions)
    return payload


def _question_set() -> dict[str, Any]:
    return {
        "action": {
            "type": "choice",
            "instructions": (
                "Given only closed BTC 1h candles and a deterministic EMA20/EMA50 baseline signal, "
                "should the next action be hold or buy? Answer hold when unsure. Never sell."
            ),
            "criteria": {
                "hold": "No clear edge, flat EMA, or conditions are unclear.",
                "buy": "Clear bullish crossover and confidence is at least moderate.",
            },
        },
        "confidence": {
            "type": "noul",
            "instructions": "How confident are you in that action, from 0 to 1?",
        },
    }


USER_AGENT = "ai-trader-hermes-client/1.0 (+local paper trading agent)"


def _post_json(endpoint: str, body: dict[str, Any], cfg: RemoteLLMConfig) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    request = Request(
        endpoint,
        data=data,
        headers={
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
            # Some edge providers (Cloudflare in front of them) return error
            # 1010 to the default Python-urllib agent. Naming ourselves keeps
            # the request from being dropped before it reaches the API.
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=cfg.timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        raise RemoteLLMError(f"HTTP {exc.code} from provider: {detail}") from None
    except (URLError, OSError, TimeoutError) as exc:
        raise RemoteLLMError(f"transport error: {type(exc).__name__}") from None
    except json.JSONDecodeError:
        raise RemoteLLMError("provider returned a non-JSON body") from None


def remote_complete(cfg: RemoteLLMConfig, prompt: str, dialect: str | None = None) -> str:
    if not cfg.api_key:
        raise RemoteLLMError("api_key is empty")
    if not cfg.model:
        raise RemoteLLMError("model is empty")
    chosen = dialect or cfg.dialect
    endpoint = _endpoint(cfg)
    if chosen == "systemone":
        body = build_systemone_request(prompt, _question_set(), cfg)
    else:
        body = build_chat_request(SYSTEM_PROMPT, prompt, cfg)
    data = _post_json(endpoint, body, cfg)
    if chosen == "systemone":
        return json.dumps(data.get("answers") or data.get("data", {}), sort_keys=True)
    return extract_chat_text(data)


def parse_chat_json_proposal(text: str, candle_timestamp: int, close: float, baseline_signal: str, model_id: str, equity: float = 1000.0) -> dict[str, Any]:
    from llm_agent import extract_json_object

    parsed = extract_json_object(text)
    payload = _base_payload(candle_timestamp, close, baseline_signal, model_id)
    if not isinstance(parsed, dict):
        payload["invalid_conditions"] = ["llm_output_unparseable"]
        payload["reason_codes"] = ["llm_output_unparseable"]
        return payload
    conditions: list[str] = []
    reasons = [r for r in parsed.get("reason_codes", []) if isinstance(r, str)] if isinstance(parsed.get("reason_codes"), list) else []
    extra = [c for c in parsed.get("invalid_conditions", []) if isinstance(c, str)] if isinstance(parsed.get("invalid_conditions"), list) else []
    signal_id = _safe_name(parsed.get("signal_id"), f"remote-{candle_timestamp}")
    action = str(parsed.get("action", "")).strip().lower()
    confidence = parsed.get("confidence", 0.0)
    quantity = parsed.get("quantity", 0.0)
    payload["signal_id"] = signal_id
    payload = _finalize(payload, action, confidence, equity, quantity if isinstance(quantity, (int, float)) else 0.0, close, reasons, conditions)
    for condition in extra:
        payload["invalid_conditions"] = sorted(set(payload["invalid_conditions"]) | {condition})
    return payload


def fetch_ledger_snapshot(cfg: RemoteLLMConfig) -> dict[str, Any]:  # pragma: no cover - helper for callers
    raise RemoteLLMError("not implemented; use ledger_adapter instead")
