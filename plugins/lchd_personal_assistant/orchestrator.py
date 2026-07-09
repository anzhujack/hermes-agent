"""Lightweight four-expert task routing for Lchd's Hermes.

This module turns the v0.1 static SOUL profile skeleton into a verifiable
routing layer. It remains deliberately small: no new core tools, no external
agent framework, and no automatic side effects beyond an audit JSONL that lets
future sessions prove routing happened. v0.4 adds a guarded delegation planner
that tells the parent agent when subagent fan-out is useful without spawning it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from hermes_constants import get_hermes_home
except Exception:  # pragma: no cover - fallback for isolated import tests
    def get_hermes_home() -> Path:
        import os
        return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))

try:
    from .context import _lchd_personal_config
except Exception:  # pragma: no cover
    def _lchd_personal_config() -> dict[str, Any]:
        return {}

_ROLE_ORDER = ("coordinator", "researcher", "writer", "builder")
_PLUGIN_VERSION = "0.4.0"
_ROLE_DEFAULTS: dict[str, dict[str, Any]] = {
    "coordinator": {
        "label": "项目经理",
        "mission": "拆解任务、选择专家组合、控制风险、整合结果。",
        "task_types": ["planning", "triage", "multi_step", "risk_control", "synthesis"],
    },
    "researcher": {
        "label": "事实发现者",
        "mission": "检索、核验、比较方案，输出带来源的事实。",
        "task_types": ["research", "fact_check", "provider_recon", "market_scan"],
    },
    "writer": {
        "label": "叙事架构师",
        "mission": "把事实和草案转成中文可读输出、复盘、网文/文档。",
        "task_types": ["writing", "summary", "story", "documentation", "handoff"],
    },
    "builder": {
        "label": "实现者",
        "mission": "写代码、改配置、运行测试、验证部署。",
        "task_types": ["coding", "debugging", "devops", "verification", "deployment"],
    },
}

LCHD_EXPERT_REGISTRY_SCHEMA = {
    "name": "lchd_expert_registry",
    "description": "Read Lchd's four specialist SOUL profiles and return a compact expert registry.",
    "parameters": {
        "type": "object",
        "properties": {
            "max_chars": {
                "type": "integer",
                "description": "Maximum SOUL excerpt characters per expert. Default 800, capped at 3000.",
                "default": 800,
            }
        },
        "additionalProperties": False,
    },
}

LCHD_TASK_ROUTE_SCHEMA = {
    "name": "lchd_task_route",
    "description": "Route a user task to Lchd's coordinator/researcher/writer/builder profiles and record an audit entry.",
    "parameters": {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "User task or short task summary to route."},
            "context": {"type": "string", "description": "Optional extra context."},
        },
        "required": ["task"],
        "additionalProperties": False,
    },
}

LCHD_TASK_FINALIZE_SCHEMA = {
    "name": "lchd_task_finalize",
    "description": "Recommend where a completed Lchd task should be persisted: handoff, Wiki, Obsidian, memory, or skill.",
    "parameters": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "What was completed or discovered."},
            "files_changed": {"type": "array", "items": {"type": "string"}},
            "verification": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": False,
    },
}


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _lchd_config() -> dict[str, Any]:
    value = _lchd_personal_config()
    return value if isinstance(value, dict) else {}


def _profiles_dir() -> Path:
    configured = _lchd_config().get("profiles_dir")
    if isinstance(configured, str) and configured.strip():
        return Path(configured).expanduser().resolve()
    return (get_hermes_home() / "lchd-profiles").resolve()


def _wiki_root() -> Path:
    configured = _lchd_config().get("wiki_root")
    if isinstance(configured, str) and configured.strip():
        return Path(configured).expanduser().resolve()
    return (get_hermes_home() / "wiki").resolve()


def _clip(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars].rstrip() + "\n\n[truncated]", True


def _safe_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value in (None, ""):
        return []
    return [str(value)]


def build_expert_registry(max_chars: int = 800) -> dict[str, Any]:
    max_chars = min(max(int(max_chars or 800), 80), 3000)
    root = _profiles_dir()
    experts: dict[str, Any] = {}
    for role in _ROLE_ORDER:
        path = root / role / "SOUL.md"
        text = ""
        error = None
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:  # pragma: no cover - defensive I/O guard
                error = type(exc).__name__
        excerpt, truncated = _clip(text, max_chars)
        defaults = _ROLE_DEFAULTS[role]
        experts[role] = {
            "available": path.exists() and error is None,
            "soul_path": str(path),
            "label": defaults["label"],
            "mission": defaults["mission"],
            "task_types": defaults["task_types"],
            "soul_excerpt": excerpt,
            "truncated": truncated,
        }
        if error:
            experts[role]["error"] = error
    return {
        "ok": True,
        "version": _PLUGIN_VERSION,
        "profiles_dir": str(root),
        "experts": experts,
        "routing_note": "This reads SOUL.md content; it is no longer only a static existence check.",
    }


def _classify_task(task: str, context: str = "") -> dict[str, Any]:
    text = f"{task}\n{context}".lower()
    if any(term in text for term in ("联网", "调研", "搜索", "research", "比较", "资料", "来源", "web", "human-in-the-loop", "多智能体")):
        return {
            "task_type": "research",
            "execution_mode": "parallel_research",
            "experts": ["coordinator", "researcher", "writer"],
            "knowledge_sources": ["web", "session_search", "obsidian"],
            "verification": ["cite authoritative sources", "cross-check claims"],
        }
    if any(term in text for term in ("hermes", "插件", "plugin", "代码", "test", "pytest", "实现", "修复", "debug", "gateway", "配置", "v0.2", "v0.3", "v0.4", "路由", "orchestrator", "专家", "delegation")):
        return {
            "task_type": "hermes_dev",
            "execution_mode": "builder_review",
            "experts": ["coordinator", "builder", "writer"],
            "knowledge_sources": ["repo", "config", "session_search", "wiki"],
            "verification": ["scripts/run_tests.sh tests/plugins/test_lchd_personal_assistant_plugin.py"],
        }
    if any(term in text for term in ("小说", "正文", "大纲", "文案", "总结", "报告", "写", "润色")):
        return {
            "task_type": "writing",
            "execution_mode": "writer_synthesis",
            "experts": ["coordinator", "writer"],
            "knowledge_sources": ["obsidian", "wiki", "project files"],
            "verification": ["check style and continuity"],
        }
    if any(term in text for term in ("路由器", "sing-box", "dns", "docker", "端口", "服务", "cron", "健康")):
        return {
            "task_type": "ops",
            "execution_mode": "guarded_builder",
            "experts": ["coordinator", "builder", "researcher"],
            "knowledge_sources": ["vault ops notes", "live system state", "logs"],
            "verification": ["non-destructive checks first", "no service restart without explicit approval"],
        }
    return {
        "task_type": "general",
        "execution_mode": "guided_direct",
        "experts": ["coordinator", "writer"],
        "knowledge_sources": ["memory", "session_search"],
        "verification": ["answer the user's exact request"],
    }


def _assess_human_gate(task: str, context: str, route: dict[str, Any]) -> dict[str, Any]:
    text = f"{task}\n{context}".lower()
    high_risk_terms = (
        "重启",
        "restart",
        "停止服务",
        "stop service",
        "修改启动脚本",
        "init script",
        "公开发布",
        "publish",
        "上传",
        "upload",
        "merge",
        "支付",
        "付款",
        "删除",
        "清理",
        "回滚",
        "rollback",
    )
    medium_risk_terms = (
        "写代码",
        "实现",
        "修复",
        "配置",
        "部署",
        "改文件",
        "edit",
        "deploy",
        "config",
    )
    negated_high_risk_phrases = (
        "不重启",
        "无需重启",
        "不停止服务",
        "不修改启动脚本",
        "不公开发布",
        "不发布",
        "不上传",
        "不删除",
        "不清理",
        "不回滚",
        "no restart",
        "without restart",
        "do not restart",
    )
    risk_text = text
    for phrase in negated_high_risk_phrases:
        risk_text = risk_text.replace(phrase, "")
    task_type = str(route.get("task_type") or "")
    high = any(term in risk_text for term in high_risk_terms)
    if task_type == "ops" and any(term in risk_text for term in ("重启", "restart", "停止服务", "stop service", "修改启动脚本", "init script")):
        high = True
    medium = task_type in {"hermes_dev", "ops"} or any(term in text for term in medium_risk_terms)
    risk_level = "high" if high else "medium" if medium else "low"
    required = risk_level == "high"
    reason = "" if not required else "涉及服务变更、公开发布/上传、删除清理、回滚或支付等高风险动作，执行前需要 Lchd 明确确认。"
    return {
        "risk_level": risk_level,
        "requires_confirmation": required,
        "human_gate": {
            "required": required,
            "reason": reason,
            "confirm_before": [
                "服务重启、停止或启动脚本变更",
                "公开发布、上传、合并或支付动作",
                "不可逆删除、全量清理或回滚",
            ],
        },
    }


def _delegation_context(
    *,
    expert: str,
    user_task: str,
    extra_context: str,
    route: dict[str, Any],
    allowed: list[str],
    forbidden: list[str],
    verification: list[str],
    output_contract: list[str],
) -> str:
    route_summary = {
        "task_type": route.get("task_type"),
        "execution_mode": route.get("execution_mode"),
        "risk_level": route.get("risk_level"),
        "human_gate_required": route.get("human_gate", {}).get("required"),
        "experts": route.get("experts", []),
    }
    lines = [
        f"You are Lchd Personal Hermes' {expert} expert subagent.",
        "",
        "User task:",
        user_task,
        "",
        "Route summary:",
        json.dumps(route_summary, ensure_ascii=False, sort_keys=True),
    ]
    if extra_context:
        lines.extend(["", "Extra parent context:", extra_context])
    lines.extend([
        "",
        "Allowed actions:",
        *[f"- {item}" for item in allowed],
        "",
        "Forbidden actions:",
        *[f"- {item}" for item in forbidden],
        "",
        "Verification expected:",
        *[f"- {item}" for item in verification],
        "",
        "Output contract:",
        *[f"- {item}" for item in output_contract],
        "",
        "Do not write memory. Do not claim external side effects succeeded unless you return verifiable evidence.",
    ])
    return "\n".join(lines)


def _planned_task(
    *,
    expert: str,
    goal: str,
    user_task: str,
    extra_context: str,
    route: dict[str, Any],
    allowed: list[str],
    forbidden: list[str],
    verification: list[str],
    output_contract: list[str],
) -> dict[str, Any]:
    return {
        "expert": expert,
        "goal": goal,
        "context": _delegation_context(
            expert=expert,
            user_task=user_task,
            extra_context=extra_context,
            route=route,
            allowed=allowed,
            forbidden=forbidden,
            verification=verification,
            output_contract=output_contract,
        ),
        "role": "leaf",
    }


def _base_delegation_plan(route: dict[str, Any]) -> dict[str, Any]:
    blocked = bool(route.get("human_gate", {}).get("required"))
    return {
        "recommended": False,
        "mode": "none",
        "dispatch_allowed": False,
        "blocked_until_confirmation": blocked,
        "reason": "Direct parent-agent handling is sufficient.",
        "tasks": [],
        "task_count": 0,
        "parent_verification": list(route.get("verification") or []),
        "merge_strategy": "Parent agent synthesizes child summaries and verifies them before final response.",
        "abort_conditions": [
            "human_gate.required is true",
            "child task would need credentials or user clarification",
            "child reports external side effects without verifiable handle",
        ],
    }


def _with_tasks(plan: dict[str, Any], tasks: list[dict[str, Any]], *, blocked: bool) -> dict[str, Any]:
    tasks = tasks[:3]
    plan = {**plan, "tasks": tasks, "task_count": len(tasks)}
    if blocked:
        return {**plan, "recommended": False, "dispatch_allowed": False, "blocked_until_confirmation": True}
    return {**plan, "recommended": bool(tasks), "dispatch_allowed": bool(tasks), "blocked_until_confirmation": False}


def _build_delegation_plan(task: str, context: str, route: dict[str, Any]) -> dict[str, Any]:
    plan = _base_delegation_plan(route)
    blocked = bool(route.get("human_gate", {}).get("required"))
    task_type = str(route.get("task_type") or "")
    verification = list(route.get("verification") or [])
    common_forbidden = [
        "write persistent memory",
        "publish, upload, pay, delete, restart services, or mutate init scripts",
        "modify files outside the explicit allowed scope",
        "invent facts or cite sources not actually inspected",
    ]
    if task_type == "research":
        plan.update({
            "mode": "parallel_research",
            "reason": "The task benefits from isolated source-finding and synthesis workstreams.",
            "parent_verification": ["cite authoritative sources", "cross-check claims", "separate sourced facts from recommendations"],
            "merge_strategy": "Parent agent compares sourced findings, resolves conflicts, and writes the final Chinese plan.",
        })
        tasks = [
            _planned_task(
                expert="researcher",
                goal="Find authoritative Hermes delegation and plugin constraints relevant to this task.",
                user_task=task,
                extra_context=context,
                route=route,
                allowed=["read official docs", "inspect local source paths named by the parent", "return citations and uncertainty"],
                forbidden=common_forbidden,
                verification=plan["parent_verification"],
                output_contract=["key findings", "source URLs or file paths", "constraints", "risks"],
            ),
            _planned_task(
                expert="researcher",
                goal="Compare multi-agent human-in-the-loop patterns for audit, gating, and failure rollback.",
                user_task=task,
                extra_context=context,
                route=route,
                allowed=["web research", "source comparison", "flag conflicts"],
                forbidden=common_forbidden,
                verification=plan["parent_verification"],
                output_contract=["pattern summary", "trade-offs", "recommended boundary for Lchd"],
            ),
            _planned_task(
                expert="writer",
                goal="Turn verified findings into a concise Chinese proposal draft without adding new facts.",
                user_task=task,
                extra_context=context,
                route=route,
                allowed=["structure findings", "clarify trade-offs", "write Chinese draft"],
                forbidden=common_forbidden,
                verification=plan["parent_verification"],
                output_contract=["draft outline", "assumptions", "open questions"],
            ),
        ]
        return _with_tasks(plan, tasks, blocked=blocked)
    if task_type == "hermes_dev":
        plan.update({
            "mode": "builder_review",
            "reason": "Hermes plugin development should be implemented by a builder then reviewed and verified by the parent.",
            "parent_verification": verification,
            "merge_strategy": "Prefer sequential builder implementation then coordinator/spec review; parent agent runs tests and reads diffs.",
        })
        tasks = [
            _planned_task(
                expert="builder",
                goal="Implement the smallest tested slice for the requested Lchd Personal Hermes change.",
                user_task=task,
                extra_context=context,
                route=route,
                allowed=[
                    "modify plugins/lchd_personal_assistant/ only when needed",
                    "modify tests/plugins/test_lchd_personal_assistant_plugin.py",
                    "run focused tests and py_compile",
                ],
                forbidden=common_forbidden + ["modify Hermes core tools", "restart gateway without explicit parent approval"],
                verification=verification,
                output_contract=["changed files", "tests run", "risks", "remaining work"],
            ),
            _planned_task(
                expert="coordinator",
                goal="Review the implementation plan or diff for scope, guardrails, and verification gaps.",
                user_task=task,
                extra_context=context,
                route=route,
                allowed=["review diffs", "check guardrails", "suggest missing tests"],
                forbidden=common_forbidden + ["make unverified success claims"],
                verification=verification,
                output_contract=["review verdict", "must-fix items", "nice-to-have items"],
            ),
        ]
        return _with_tasks(plan, tasks, blocked=blocked)
    if task_type == "writing":
        plan.update({
            "mode": "writer_synthesis",
            "reason": "Writing tasks can be drafted by a writer expert while the parent checks continuity and user intent.",
            "parent_verification": verification,
            "merge_strategy": "Parent agent adapts the writer draft to the current conversation and checks for style/continuity.",
        })
        tasks = [_planned_task(
            expert="writer",
            goal="Draft the requested Chinese writing/synthesis output in Lchd's preferred style.",
            user_task=task,
            extra_context=context,
            route=route,
            allowed=["write draft", "summarize", "flag style assumptions"],
            forbidden=common_forbidden + ["publish or send externally"],
            verification=verification,
            output_contract=["draft", "style notes", "continuity checks"],
        )]
        return _with_tasks(plan, tasks, blocked=blocked)
    if task_type == "ops":
        plan.update({
            "mode": "guarded_diagnosis",
            "reason": "Ops work is only delegable for read-only diagnosis; mutation waits for Lchd confirmation.",
            "parent_verification": verification,
            "merge_strategy": "Parent agent verifies live system state before any action and asks before service mutation.",
        })
        tasks = [] if blocked else [_planned_task(
            expert="builder",
            goal="Perform read-only diagnosis and propose a guarded operations plan.",
            user_task=task,
            extra_context=context,
            route=route,
            allowed=["read logs", "inspect config", "run non-destructive status checks"],
            forbidden=common_forbidden + ["restart services", "edit init scripts", "delete or rollback"],
            verification=verification,
            output_contract=["findings", "proposed safe next action", "confirmation needed"],
        )]
        return _with_tasks(plan, tasks, blocked=blocked)
    return plan


def _delegation_summary(delegation: dict[str, Any]) -> dict[str, Any]:
    return {
        "recommended": bool(delegation.get("recommended")),
        "mode": str(delegation.get("mode") or "none"),
        "dispatch_allowed": bool(delegation.get("dispatch_allowed")),
        "task_count": int(delegation.get("task_count") or len(delegation.get("tasks") or [])),
    }


def _append_audit(record: dict[str, Any]) -> Path:
    path = _wiki_root() / "logs" / "expert_routes.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def build_task_route(task: str, context: str = "") -> dict[str, Any]:
    task = str(task or "").strip()
    context = str(context or "").strip()
    if not task:
        return {"ok": False, "error": "missing_task"}
    route = _classify_task(task, context)
    route = {**route, **_assess_human_gate(task, context, route)}
    delegation = _build_delegation_plan(task, context, route)
    route = {**route, "delegation": delegation}
    route_for_audit = {key: value for key, value in route.items() if key != "delegation"}
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "task": task[:500],
        "context_present": bool(context),
        **route_for_audit,
        "delegation_summary": _delegation_summary(delegation),
    }
    audit_path = _append_audit(record)
    return {
        "ok": True,
        "version": _PLUGIN_VERSION,
        "task": task,
        "audit_path": str(audit_path),
        "guardrails": [
            "先做可验证的读取/检查，再写入或重启。",
            "公开发布、服务重启、路由器破坏性修改需要 Lchd 明确确认。",
        ],
        **route,
    }


def build_task_finalize(summary: str = "", files_changed: Any = None, verification: Any = None) -> dict[str, Any]:
    summary = str(summary or "").strip()
    changed_files = _safe_list(files_changed)
    checks = _safe_list(verification)
    text = "\n".join([summary, *changed_files, *checks]).lower()
    touched_code = any(path.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".yaml", ".yml")) for path in changed_files)
    reusable = any(term in text for term in ("skill", "流程", "可复用", "workflow", "troubleshoot", "路由", "orchestrator"))
    durable = any(term in text for term in ("架构", "长期", "obsidian", "知识库", "四专家", "专家"))
    recommendations = {
        "write_handoff": bool(summary or changed_files or checks),
        "update_wiki": bool(touched_code or "wiki" in text or "dashboard" in text or "路由" in text),
        "update_obsidian": bool(durable),
        "suggest_memory": False,
        "suggest_skill": bool(reusable or touched_code),
    }
    recommended_actions = [name for name, needed in recommendations.items() if needed]
    return {
        "ok": True,
        "version": _PLUGIN_VERSION,
        "summary": summary,
        "changed_files": changed_files,
        "verification": checks,
        "recommendations": recommendations,
        "enforcement": {
            "must_review_before_final": True,
            "recommended_actions": recommended_actions,
            "non_actions": ["do_not_save_task_progress_to_memory"],
            "human_gate": "Ask before service restarts, public publishing/uploading, destructive cleanup, rollback, or payment actions.",
        },
        "policy": {
            "memory": "Only compact durable preferences/environment facts; do not store task progress.",
            "wiki": "Dynamic project status, audit logs, handoffs.",
            "obsidian": "Reviewed stable architecture and SOPs.",
            "skill": "Reusable procedures discovered during non-trivial tasks.",
        },
    }


def handle_expert_registry(args: dict | None = None, **_: Any) -> str:
    args = args or {}
    try:
        max_chars = int(args.get("max_chars") or 800)
    except (TypeError, ValueError):
        max_chars = 800
    return _json(build_expert_registry(max_chars=max_chars))


def handle_task_route(args: dict | None = None, **_: Any) -> str:
    args = args or {}
    return _json(build_task_route(task=str(args.get("task") or ""), context=str(args.get("context") or "")))


def handle_task_finalize(args: dict | None = None, **_: Any) -> str:
    args = args or {}
    return _json(build_task_finalize(
        summary=str(args.get("summary") or ""),
        files_changed=args.get("files_changed") or [],
        verification=args.get("verification") or [],
    ))
