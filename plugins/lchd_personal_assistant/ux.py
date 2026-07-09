"""Chinese status and handoff helpers for Lchd's Hermes UX."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

try:
    from hermes_constants import get_hermes_home
except Exception:  # pragma: no cover
    def get_hermes_home() -> Path:
        import os
        return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))

_DEFAULT_WIKI = get_hermes_home() / "wiki"


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _load_config() -> dict[str, Any]:
    try:
        data = yaml.safe_load((get_hermes_home() / "config.yaml").read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}
    return data if isinstance(data, dict) else {}


def _lchd_config(config: dict[str, Any]) -> dict[str, Any]:
    value = config.get("lchd_personal")
    return value if isinstance(value, dict) else {}


def _plugins_enabled(config: dict[str, Any]) -> list[str]:
    plugins = config.get("plugins") or {}
    enabled = plugins.get("enabled") if isinstance(plugins, dict) else []
    return [str(x) for x in enabled] if isinstance(enabled, list) else []


def _wiki_root(config: dict[str, Any]) -> Path:
    personal = _lchd_config(config)
    configured = personal.get("wiki_root")
    if isinstance(configured, str) and configured:
        return Path(configured).expanduser()
    return _DEFAULT_WIKI


def _safe_slug(text: str) -> str:
    text = text.strip() or "handoff"
    text = re.sub(r"[^\w\-\u4e00-\u9fff]+", "-", text, flags=re.UNICODE).strip("-")
    return text[:80] or "handoff"


def _coerce_recent_routes_limit(value: Any) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = 5
    return min(max(limit, 0), 20)


def _recent_expert_routes(wiki: Path, limit: int) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    path = wiki / "logs" / "expert_routes.jsonl"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return []
    routes: list[dict[str, Any]] = []
    keep = ("ts", "task", "task_type", "execution_mode", "experts", "risk_level", "requires_confirmation", "delegation_summary")
    for line in reversed(lines):
        if len(routes) >= limit:
            break
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        route = {key: record.get(key) for key in keep if key in record}
        delegation = record.get("delegation")
        if "delegation_summary" not in route and isinstance(delegation, dict):
            route["delegation_summary"] = {
                "recommended": bool(delegation.get("recommended")),
                "mode": str(delegation.get("mode") or "none"),
                "dispatch_allowed": bool(delegation.get("dispatch_allowed")),
                "task_count": int(delegation.get("task_count") or len(delegation.get("tasks") or [])),
            }
        routes.append(route)
    return routes


def build_status(recent_routes: int = 5) -> dict[str, Any]:
    config = _load_config()
    personal = _lchd_config(config)
    enabled = _plugins_enabled(config)
    expected = ["lchd-personal-assistant"]
    legacy = ["lchd-context", "lchd-guardrails", "lchd-cost-router", "lchd-gateway-ux"]
    plugin_state = {name: (name in enabled) for name in expected}
    legacy_state = {name: (name in enabled) for name in legacy}
    model = config.get("model") or {}
    if not isinstance(model, dict):
        model = {}
    wiki = _wiki_root(config)
    recent_routes = _coerce_recent_routes_limit(recent_routes)
    return {
        "ok": True,
        "中文阶段摘要": {
            "已完成": [name for name, ok in plugin_state.items() if ok] + ["Wiki/Obsidian/Profile skeleton", "v0.4 expert delegation planner"],
            "未完成": [name for name, ok in plugin_state.items() if not ok],
            "验证建议": [
                "scripts/run_tests.sh tests/plugins/test_lchd_personal_assistant_plugin.py",
                "cd /root/Documents/Obsidian Vault && python3 scripts/kb-lint.py --links --secrets",
            ],
            "下一步": "Use lchd_task_route first; if delegation.recommended and dispatch_allowed, parent agent may call delegate_task and must verify child summaries.",
        },
        "paths": {
            "wiki_root": str(wiki),
            "obsidian_vault_path": str(personal.get("obsidian_vault_path", "/root/Documents/Obsidian Vault")),
            "profiles_dir": str(personal.get("profiles_dir", get_hermes_home() / "lchd-profiles")),
            "dashboard": str(wiki / "system" / "dashboard.md"),
        },
        "model": {"provider": model.get("provider"), "default": model.get("default") or model.get("model")},
        "plugins": plugin_state,
        "legacy_plugins": legacy_state,
        "toolset": "lchd_personal",
        "recent_expert_routes": _recent_expert_routes(wiki, recent_routes),
    }


def handle_status(args: dict | None = None, **_: Any) -> str:
    args = args or {}
    return _json(build_status(recent_routes=_coerce_recent_routes_limit(args.get("recent_routes", 5))))


def handle_handoff_note(args: dict | None = None, **_: Any) -> str:
    args = args or {}
    title = str(args.get("title") or "Hermes handoff")
    completed = args.get("completed") or []
    pending = args.get("pending") or []
    verification = args.get("verification") or []
    next_step = str(args.get("next_step") or "")
    if not isinstance(completed, list):
        completed = [str(completed)]
    if not isinstance(pending, list):
        pending = [str(pending)]
    if not isinstance(verification, list):
        verification = [str(verification)]

    config = _load_config()
    wiki = _wiki_root(config)
    out_dir = wiki / "handoffs"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"{stamp}-{_safe_slug(title)}.md"
    lines = [
        f"# {title}",
        "",
        f"> Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## 已完成",
        *[f"- {x}" for x in completed],
        "",
        "## 未完成",
        *[f"- {x}" for x in pending],
        "",
        "## 验证结果",
        *[f"- {x}" for x in verification],
        "",
        "## 下一步",
        next_step or "- 待定",
        "",
    ]
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return _json({"ok": True, "path": str(path), "title": title})


LCHD_STATUS_SCHEMA = {
    "name": "lchd_status",
    "description": "Return a Chinese phased status summary for Lchd's personalized Hermes project.",
    "parameters": {
        "type": "object",
        "properties": {
            "recent_routes": {
                "type": "integer",
                "description": "Number of recent expert route audit entries to include. Default 5, capped at 20.",
                "default": 5,
            }
        },
        "additionalProperties": False,
    },
}

LCHD_HANDOFF_NOTE_SCHEMA = {
    "name": "lchd_handoff_note",
    "description": "Write a compact Chinese handoff note into Lchd's Wiki handoffs directory.",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "completed": {"type": "array", "items": {"type": "string"}},
            "pending": {"type": "array", "items": {"type": "string"}},
            "verification": {"type": "array", "items": {"type": "string"}},
            "next_step": {"type": "string"},
        },
    },
}
