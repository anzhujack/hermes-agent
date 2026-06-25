"""Read-only personalized context helpers for Lchd.

The handlers in this module return JSON strings because Hermes plugin tools are
registered through the same registry as built-in tools. Outputs are deliberately
compact and sanitized: they expose names/statuses, never token values.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable

try:
    import yaml
except Exception:  # pragma: no cover - yaml is an installed Hermes dependency
    yaml = None  # type: ignore[assignment]

from hermes_constants import get_hermes_home


# Obsidian keys are intentionally explicit. This prevents the tool from becoming
# an arbitrary file reader over the user's vault.
_VAULT_RELATIVE_ALLOWLIST: Dict[str, str] = {
    "home": "Home.md",
    "schema": "Hermes/SCHEMA.md",
    "hermes_personal": "Hermes/Hermes个性化助手.md",
    "router_singbox": "路由器与网络/sing-box.md",
    "router_momo": "路由器与网络/momo.md",
    "router_docker": "路由器与网络/docker.md",
    "nft_dns": "路由器与网络/nft-dns劫持.md",
    "nsfw_image_chain": "Hermes/NSFW生图链路.md",
}

_SECRET_FIELD_MARKERS = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "authorization",
    "auth",
    "cookie",
)

LCHD_CONTEXT_PROFILE_SCHEMA = {
    "name": "lchd_context_profile",
    "description": "Return a compact, non-secret profile of Lchd's personalized Hermes context sources and operating rules.",
    "parameters": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}

LCHD_VAULT_LOOKUP_SCHEMA = {
    "name": "lchd_vault_lookup",
    "description": "Read an allowlisted Obsidian note by key for Lchd-specific long-term context. Does not accept arbitrary paths.",
    "parameters": {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Allowlisted note key, e.g. router_singbox, router_momo, router_docker, nft_dns, nsfw_image_chain, hermes_personal, schema, home.",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to return from the note. Default 4000, capped at 12000.",
                "default": 4000,
            },
        },
        "required": ["key"],
        "additionalProperties": False,
    },
}

LCHD_RUNTIME_SNAPSHOT_SCHEMA = {
    "name": "lchd_runtime_snapshot",
    "description": "Return a sanitized snapshot of Hermes runtime configuration names/statuses for Lchd. Secrets are omitted.",
    "parameters": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}


def _json(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def _vault_root() -> Path:
    override = os.environ.get("LCHD_OBSIDIAN_VAULT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    configured = _lchd_personal_config().get("obsidian_vault_path")
    if isinstance(configured, str) and configured.strip():
        return Path(configured).expanduser().resolve()
    return (Path.home() / "Documents" / "Obsidian Vault").resolve()


def _lchd_personal_config() -> Dict[str, Any]:
    config = _load_yaml(get_hermes_home() / "config.yaml")
    personal = config.get("lchd_personal")
    return personal if isinstance(personal, dict) else {}


def _wiki_root() -> Path:
    configured = _lchd_personal_config().get("wiki_root")
    if isinstance(configured, str) and configured.strip():
        return Path(configured).expanduser().resolve()
    return (get_hermes_home() / "wiki").resolve()


def _profiles_dir() -> Path:
    configured = _lchd_personal_config().get("profiles_dir")
    if isinstance(configured, str) and configured.strip():
        return Path(configured).expanduser().resolve()
    return (get_hermes_home() / "lchd-profiles").resolve()


def _clip_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars].rstrip() + "\n\n[truncated]", True


def _load_yaml(path: Path) -> Dict[str, Any]:
    if yaml is None or not path.exists():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _public_keys(mapping: Dict[str, Any], keys: Iterable[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in keys:
        if key in mapping and not _looks_secret_key(key):
            out[key] = mapping[key]
    return out


def _looks_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SECRET_FIELD_MARKERS)


def _sanitize(value: Any, *, depth: int = 0) -> Any:
    """Return a config-shaped value with secret-ish fields removed.

    This is intentionally conservative. If a key name looks auth-related, the
    value becomes "<redacted>" even if it is not actually a secret.
    """
    if depth > 4:
        return "<omitted>"
    if isinstance(value, dict):
        clean: Dict[str, Any] = {}
        for key, child in value.items():
            key_s = str(key)
            clean[key_s] = "<redacted>" if _looks_secret_key(key_s) else _sanitize(child, depth=depth + 1)
        return clean
    if isinstance(value, list):
        return [_sanitize(item, depth=depth + 1) for item in value[:25]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _config_summary() -> Dict[str, Any]:
    config = _load_yaml(get_hermes_home() / "config.yaml")
    model = config.get("model") if isinstance(config.get("model"), dict) else {}
    memory = config.get("memory") if isinstance(config.get("memory"), dict) else {}
    stt = config.get("stt") if isinstance(config.get("stt"), dict) else {}
    tts = config.get("tts") if isinstance(config.get("tts"), dict) else {}
    image_gen = config.get("image_gen") if isinstance(config.get("image_gen"), dict) else {}
    delegation = config.get("delegation") if isinstance(config.get("delegation"), dict) else {}

    platforms = config.get("platforms") if isinstance(config.get("platforms"), dict) else {}
    enabled_platforms = [
        name for name, value in platforms.items()
        if isinstance(value, dict) and value.get("enabled") is True
    ]

    custom_providers = config.get("custom_providers") if isinstance(config.get("custom_providers"), list) else []
    custom_provider_names = [
        item.get("name") for item in custom_providers
        if isinstance(item, dict) and item.get("name")
    ]

    mcp_servers = config.get("mcp_servers") if isinstance(config.get("mcp_servers"), dict) else {}

    return {
        "hermes_home": str(get_hermes_home()),
        "lchd_personal": _public_keys(
            _lchd_personal_config(),
            ("mode", "obsidian_vault_path", "wiki_root", "profiles_dir"),
        ),
        "model": _public_keys(model, ("provider", "default", "api_mode", "base_url", "context_length")),
        "fallback_providers_count": len(config.get("fallback_providers") or []),
        "custom_providers": custom_provider_names,
        "memory": _public_keys(memory, ("provider", "memory_enabled", "user_profile_enabled")),
        "stt": _public_keys(stt, ("enabled", "provider")),
        "tts": _public_keys(tts, ("provider",)),
        "image_gen": _public_keys(image_gen, ("provider", "model")),
        "delegation": _public_keys(delegation, ("max_concurrent_children", "max_iterations", "provider", "model")),
        "gateway_platforms_enabled": enabled_platforms,
        "mcp_servers": sorted(str(name) for name in mcp_servers.keys()),
    }


def handle_context_profile(args: dict | None = None, **_: Any) -> str:
    vault_root = _vault_root()
    wiki_root = _wiki_root()
    profiles_dir = _profiles_dir()
    available_notes = {
        key: (vault_root / relative).exists()
        for key, relative in _VAULT_RELATIVE_ALLOWLIST.items()
    }
    profile_roles = {
        role: (profiles_dir / role / "SOUL.md").exists()
        for role in ("coordinator", "researcher", "writer", "builder")
    }
    return _json({
        "ok": True,
        "profile": {
            "architecture": "dual-engine knowledge base + four specialist SOUL profiles",
            "language": "zh-CN first; concise phase recaps for long work.",
            "operating_style": [
                "staged execution with explicit implemented-vs-planned separation",
                "use tools for current facts and verification",
                "prefer exact executable commands for technical work",
                "preserve existing dirty files before coding",
            ],
            "knowledge_policy": {
                "memory": "compact durable preferences and indexes only",
                "mem0": "semantic cross-session facts",
                "obsidian": "long-lived project and operations source of truth",
                "skills": "reusable procedures and troubleshooting workflows",
            },
            "guardrails": [
                "do not restart sing-box or edit /etc/init.d/* without explicit approval",
                "public publishing/uploading requires final confirmation",
                "people/image tasks show the full prompt before generation and protect private images",
                "after gateway interruption, verify PID/uptime/logs before proposing another restart",
            ],
            "priority_domains": [
                "Hermes development and gateway ops",
                "router/sing-box/DNS/Docker maintenance",
                "provider/relay auditing and model routing",
                "Chinese web-novel writing and image/media workflows",
            ],
            "vault_root": str(vault_root),
            "wiki_root": str(wiki_root),
            "profiles_dir": str(profiles_dir),
            "allowlisted_vault_keys": available_notes,
            "profile_roles": profile_roles,
        },
    })


def handle_vault_lookup(args: dict | None = None, **_: Any) -> str:
    args = args or {}
    key = str(args.get("key") or "").strip()
    if key not in _VAULT_RELATIVE_ALLOWLIST:
        return _json({
            "ok": False,
            "error": "unknown_vault_key",
            "allowed_keys": sorted(_VAULT_RELATIVE_ALLOWLIST),
        })

    try:
        max_chars = int(args.get("max_chars") or 4000)
    except (TypeError, ValueError):
        max_chars = 4000
    max_chars = min(max(max_chars, 200), 12000)

    vault_root = _vault_root()
    target = (vault_root / _VAULT_RELATIVE_ALLOWLIST[key]).resolve()
    try:
        target.relative_to(vault_root)
    except ValueError:
        return _json({"ok": False, "error": "resolved_path_outside_vault", "key": key})

    if not target.exists():
        return _json({
            "ok": False,
            "error": "note_not_found",
            "key": key,
            "path": str(target),
        })

    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = target.read_text(errors="replace")
    clipped, truncated = _clip_text(text, max_chars)
    return _json({
        "ok": True,
        "key": key,
        "path": str(target),
        "truncated": truncated,
        "content": clipped,
    })


def handle_runtime_snapshot(args: dict | None = None, **_: Any) -> str:
    repo_root = Path(__file__).resolve().parents[2]
    plan_path = repo_root / "docs" / "plans" / "2026-06-25-lchd-personal-hermes.md"
    checklist_path = repo_root / "docs" / "plans" / "2026-06-25-lchd-personal-hermes-checklist.md"
    return _json({
        "ok": True,
        "runtime": _config_summary(),
        "personalization_files": {
            "plan": str(plan_path),
            "plan_exists": plan_path.exists(),
            "checklist": str(checklist_path),
            "checklist_exists": checklist_path.exists(),
        },
        "security": {
            "secrets_policy": "secret-like config fields are omitted or redacted",
            "vault_access": "allowlist-only, no arbitrary paths",
        },
    })
