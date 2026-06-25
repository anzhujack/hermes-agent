"""Deterministic Lchd-specific safety guardrails.

This plugin encodes the user's stable safety preferences as executable checks.
It is intentionally small and local: no network, no secrets, and no reads of
sensitive files.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict
from typing import Any, Iterable, List, Optional

_APPROVAL_TOKENS = (
    "LCHD_APPROVED=1",
    "CONFIRMED_BY_LCHD=1",
    "LCHD_EXPLICIT_CONFIRMATION=1",
)

_TERMINAL_MUTATION_RE = re.compile(
    r"(?ix)"
    r"(\bsing-box\b\s+(restart|reload|stop|start)\b)"
    r"|(/etc/init\.d/[^\s;&|]+\s+(restart|reload|stop|start|enable|disable)\b)"
    r"|(\bservice\s+sing-box\s+(restart|reload|stop|start)\b)"
    r"|(\bsystemctl\s+(restart|reload|stop|start)\s+sing-box\b)"
)

_INIT_SCRIPT_EDIT_RE = re.compile(r"(?i)(/etc/init\.d/[^\s;&|]+)")
_GATEWAY_RESTART_RE = re.compile(r"(?i)(\bhermes\s+gateway\s+restart\b|/restart\b|\bhermes-gateway\b.*\brestart\b)")
_PUBLIC_ACTION_RE = re.compile(
    r"(?i)(\bpublish\b|\bupload\b|投稿|发布|公开发布|发到B站|发到 b站|bilibili|youtube|抖音|小红书|微博|twitter|x\.com)"
)
_IMAGE_PEOPLE_RE = re.compile(
    r"(?i)(人物|真人|人像|生成图|\bface\b|\bportrait\b|\bcharacter\b|\bcosplay\b|\bgirl\b|\bboy\b|\bwoman\b|\bman\b|\bimage\b)"
)

_WRITE_TOOLS = {"write_file", "patch", "skill_manage"}
_PUBLIC_TOOLS = {
    "mcp_github_create_issue",
    "mcp_github_add_issue_comment",
    "mcp_github_create_pull_request",
    "mcp_github_create_pull_request_review",
    "mcp_github_merge_pull_request",
    "mcp_github_create_or_update_file",
    "mcp_github_push_files",
}


@dataclass(frozen=True)
class Finding:
    id: str
    severity: str
    action: str
    message: str
    required_confirmation: str = ""


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def _has_approval_marker(text: str) -> bool:
    env_enabled = os.environ.get("LCHD_GUARDRAILS_APPROVED", "").lower() in {"1", "true", "yes", "on"}
    return env_enabled or any(token in text for token in _APPROVAL_TOKENS)


def _command_from_args(args: Any) -> str:
    if isinstance(args, dict):
        return _stringify(args.get("command") or args.get("cmd") or args)
    return _stringify(args)


def _write_target_and_content(tool_name: str, args: Any) -> tuple[str, str]:
    if not isinstance(args, dict):
        return "", ""
    if tool_name == "write_file":
        return _stringify(args.get("path")), _stringify(args.get("content"))
    if tool_name == "patch":
        return _stringify(args.get("path")), "\n".join(_stringify(args.get(k)) for k in ("old_string", "new_string", "patch"))
    if tool_name == "skill_manage":
        return _stringify(args.get("file_path") or args.get("name")), "\n".join(_stringify(args.get(k)) for k in ("content", "old_string", "new_string", "file_content"))
    return "", ""


def classify_action(tool_name: str, args: Any) -> List[Finding]:
    """Return guardrail findings for one proposed tool/action."""
    findings: list[Finding] = []
    tool_name = tool_name or ""
    serialized = _stringify(args)

    if tool_name == "terminal":
        command = _command_from_args(args)
        if _TERMINAL_MUTATION_RE.search(command):
            findings.append(Finding(
                id="router_service_mutation",
                severity="block",
                action="block",
                message="Router/sing-box service mutation detected. Lchd requires explicit confirmation before restarting/reloading/stopping/starting sing-box or init services.",
                required_confirmation="Ask Lchd, then include LCHD_APPROVED=1 in the command context if confirmed.",
            ))
        elif _GATEWAY_RESTART_RE.search(command):
            findings.append(Finding(
                id="gateway_restart_check",
                severity="warn",
                action="warn",
                message="Gateway restart/control detected. If this follows an interruption, check PID/uptime/log timestamps before proposing another restart.",
            ))
        if _INIT_SCRIPT_EDIT_RE.search(command) and re.search(r"(?i)\b(vi|vim|nano|sed|perl|python|cat\s*>|tee|chmod|rm|mv|cp)\b", command):
            findings.append(Finding(
                id="init_script_edit",
                severity="block",
                action="block",
                message="Potential /etc/init.d edit detected. Lchd requires explicit confirmation before editing init scripts.",
                required_confirmation="Ask Lchd, then include LCHD_APPROVED=1 in the command context if confirmed.",
            ))

    if tool_name in _WRITE_TOOLS:
        path, content = _write_target_and_content(tool_name, args)
        combined = f"{path}\n{content}"
        if "/etc/init.d/" in combined:
            findings.append(Finding(
                id="init_script_write",
                severity="block",
                action="block",
                message="Write/patch targets /etc/init.d. Lchd requires explicit confirmation before init script edits.",
                required_confirmation="Ask Lchd before retrying with an explicit approval marker.",
            ))

    if tool_name in _PUBLIC_TOOLS:
        findings.append(Finding(
            id="public_side_effect",
            severity="block",
            action="block",
            message="Public/external side-effect tool detected. Lchd requires final explicit confirmation before publishing, PR review, merge, GitHub writes, or public posting.",
            required_confirmation="Ask Lchd for final confirmation before retrying with an explicit approval marker.",
        ))
    elif _PUBLIC_ACTION_RE.search(serialized):
        findings.append(Finding(
            id="public_posting_confirmation",
            severity="warn",
            action="warn",
            message="Publishing/uploading wording detected. Final public release must wait for Lchd's explicit confirmation.",
        ))

    if tool_name in {"image_generate", "video_generate"}:
        if _IMAGE_PEOPLE_RE.search(serialized):
            findings.append(Finding(
                id="people_image_prompt_first",
                severity="warn",
                action="warn",
                message="People/image-related task detected. Show the complete prompt first and protect local private images; only generate after the requested approval path.",
            ))

    # De-duplicate by id while preserving order.
    seen: set[str] = set()
    deduped: list[Finding] = []
    for finding in findings:
        if finding.id not in seen:
            seen.add(finding.id)
            deduped.append(finding)
    return deduped


def _blocking_findings(findings: Iterable[Finding], args: Any) -> list[Finding]:
    text = _stringify(args)
    if _has_approval_marker(text):
        return []
    return [f for f in findings if f.action == "block"]


def _format_findings(findings: Iterable[Finding]) -> str:
    lines = ["🛡️ Lchd guardrails triggered:"]
    for finding in findings:
        lines.append(f"- [{finding.severity}] {finding.id}: {finding.message}")
        if finding.required_confirmation:
            lines.append(f"  Required: {finding.required_confirmation}")
    return "\n".join(lines)


def on_pre_tool_call(tool_name: str = "", args: Any = None, **_: Any) -> Optional[dict[str, str]]:
    findings = classify_action(tool_name, args)
    blocked = _blocking_findings(findings, args)
    if not blocked:
        return None
    return {"action": "block", "message": _format_findings(blocked)}


def on_transform_tool_result(tool_name: str = "", args: Any = None, result: Any = None, **_: Any) -> Optional[str]:
    findings = [f for f in classify_action(tool_name, args) if f.action == "warn"]
    if not findings or not isinstance(result, str):
        return None
    return result + "\n\n" + _format_findings(findings)


def handle_guardrails_check(args: dict | None = None, **_: Any) -> str:
    args = args or {}
    tool_name = _stringify(args.get("tool_name") or "")
    tool_args = args.get("args", {})
    findings = classify_action(tool_name, tool_args)
    blocked = _blocking_findings(findings, tool_args)
    return _json({
        "ok": True,
        "tool_name": tool_name,
        "allowed": not blocked,
        "findings": [asdict(f) for f in findings],
        "blocked_findings": [asdict(f) for f in blocked],
        "approval_markers": list(_APPROVAL_TOKENS),
    })


LCHD_GUARDRAILS_CHECK_SCHEMA = {
    "name": "lchd_guardrails_check",
    "description": "Classify a proposed action against Lchd-specific safety guardrails before executing it.",
    "parameters": {
        "type": "object",
        "properties": {
            "tool_name": {"type": "string", "description": "Tool name being considered, e.g. terminal or image_generate."},
            "args": {"type": "object", "description": "Arguments that would be sent to that tool."},
        },
        "required": ["tool_name"],
    },
}
