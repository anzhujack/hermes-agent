"""Secret-safe cost-aware model routing reports for Lchd."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

try:
    from hermes_constants import get_hermes_home
except Exception:  # pragma: no cover - fallback for isolated import tests
    def get_hermes_home() -> Path:
        import os
        return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))

_SECRET_MARKERS = ("key", "token", "secret", "password", "authorization", "cookie", "auth")
_ROUTINE_AUX_TASKS = {
    "title_generation",
    "approval",
    "session_search",
    "skills_hub",
    "mcp",
    "web_extract",
    "triage_specifier",
    "embedding",
}
_STRONG_AUX_TASKS = {"vision", "compression", "curator", "summarization"}


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _load_config() -> dict[str, Any]:
    path = get_hermes_home() / "config.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}
    return data if isinstance(data, dict) else {}


def _safe_scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _public_dict(data: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in keys:
        if key in data and not any(marker in key.lower() for marker in _SECRET_MARKERS):
            out[key] = _safe_scalar(data.get(key))
    return out


def _custom_provider_names(config: dict[str, Any]) -> list[str]:
    providers = config.get("custom_providers") or []
    if not isinstance(providers, list):
        return []
    names: list[str] = []
    for entry in providers:
        if isinstance(entry, dict) and entry.get("name"):
            names.append(str(entry["name"]))
    return sorted(names)


def _custom_provider_public(config: dict[str, Any]) -> list[dict[str, Any]]:
    providers = config.get("custom_providers") or []
    out: list[dict[str, Any]] = []
    if not isinstance(providers, list):
        return out
    for entry in providers:
        if not isinstance(entry, dict):
            continue
        out.append(_public_dict(entry, ("name", "base_url", "api_mode", "model", "default", "context_length")))
    return out


def _fallbacks(config: dict[str, Any]) -> dict[str, Any]:
    fallbacks = config.get("fallback_providers")
    if not isinstance(fallbacks, list):
        fallbacks = []
    public_fallbacks = []
    for entry in fallbacks:
        if isinstance(entry, dict):
            public_fallbacks.append(_public_dict(entry, ("provider", "model", "api_mode", "base_url", "priority")))
    return {
        "fallback_model": _safe_scalar(config.get("fallback_model")) if config.get("fallback_model") else None,
        "fallback_providers": public_fallbacks,
        "count": len(public_fallbacks) + (1 if config.get("fallback_model") else 0),
    }


def _auxiliary_routes(config: dict[str, Any]) -> dict[str, Any]:
    aux = config.get("auxiliary") or {}
    if not isinstance(aux, dict):
        return {"tasks": {}, "count": 0}
    tasks: dict[str, Any] = {}
    for task, value in sorted(aux.items()):
        if isinstance(value, dict):
            tasks[str(task)] = _public_dict(value, ("provider", "model", "base_url", "api_mode", "reasoning_effort", "max_tokens"))
    return {"tasks": tasks, "count": len(tasks)}


def _route_strength(provider: str | None, model: str | None) -> str:
    text = f"{provider or ''} {model or ''}".lower()
    if any(term in text for term in ("opus", "gpt-5", "gpt-4.5", "sonnet", "pro", "xhigh")):
        return "strong"
    if any(term in text for term in ("mini", "flash", "haiku", "small", "cheap", "lite")):
        return "cheap"
    return "unknown"


def _recommendations(config: dict[str, Any]) -> list[str]:
    recs: list[str] = []
    model = config.get("model") or {}
    if not isinstance(model, dict):
        model = {}
    primary_provider = str(model.get("provider") or "")
    primary_model = str(model.get("default") or model.get("model") or "")
    primary_strength = _route_strength(primary_provider, primary_model)

    fb = _fallbacks(config)
    if fb["count"] == 0:
        recs.append("Add at least one heterogeneous fallback provider so long Discord tasks do not fail on one provider outage.")

    aux = _auxiliary_routes(config)["tasks"]
    missing_routine = sorted(task for task in _ROUTINE_AUX_TASKS if task not in aux)
    if missing_routine:
        recs.append("Consider routing routine auxiliary tasks to a cheaper/faster model: " + ", ".join(missing_routine[:8]) + ".")
    for task in sorted(_STRONG_AUX_TASKS & set(aux)):
        route = aux[task]
        strength = _route_strength(str(route.get("provider") or ""), str(route.get("model") or ""))
        if strength == "cheap":
            recs.append(f"Auxiliary task {task} may need a stronger route than its current cheap model for quality-sensitive work.")
    if primary_strength == "strong" and not aux:
        recs.append("Primary route appears strong; define auxiliary routes so summarization/search/title tasks do not always use the main expensive model.")
    if config.get("fallback_model") and config.get("fallback_providers"):
        recs.append("Remove legacy fallback_model after confirming fallback_providers; two fallback sources can confuse maintenance.")
    if not recs:
        recs.append("No obvious routing issue found from static config; live E2E probes are still required before deleting or reordering providers.")
    return recs


def build_policy_report() -> dict[str, Any]:
    config = _load_config()
    model = config.get("model") or {}
    if not isinstance(model, dict):
        model = {}
    return {
        "ok": True,
        "hermes_home": str(get_hermes_home()),
        "primary": _public_dict(model, ("provider", "default", "model", "api_mode", "base_url", "context_length")),
        "fallbacks": _fallbacks(config),
        "auxiliary": _auxiliary_routes(config),
        "custom_providers": _custom_provider_public(config),
        "custom_provider_names": _custom_provider_names(config),
        "recommendations": _recommendations(config),
        "policy": {
            "strong_route": "coding, high-stakes reasoning, hard debugging, final synthesis",
            "cheap_route": "title generation, approvals, session search, skill search, web extraction, small summaries",
            "verification": "Do live E2E before removing or reordering providers; static config reports are advisory only.",
            "redaction_note": "Credentials are intentionally omitted.",
        },
    }


def handle_model_policy(args: dict | None = None, **_: Any) -> str:
    return _json(build_policy_report())


LCHD_MODEL_POLICY_SCHEMA = {
    "name": "lchd_model_policy",
    "description": "Return a secret-safe report of Lchd's Hermes primary/fallback/auxiliary model routing and cost recommendations.",
    "parameters": {"type": "object", "properties": {}},
}
