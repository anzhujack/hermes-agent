"""Unified Lchd personal assistant plugin.

This replaces the earlier split plugins:
- lchd-context
- lchd-guardrails
- lchd-cost-router
- lchd-gateway-ux

All tools are exposed through one toolset, ``lchd_personal``.
"""

from __future__ import annotations

from .artifact_cleanup import on_session_end as on_artifact_cleanup_session_end
from .context import (
    LCHD_CONTEXT_PROFILE_SCHEMA,
    LCHD_RUNTIME_SNAPSHOT_SCHEMA,
    LCHD_VAULT_LOOKUP_SCHEMA,
    handle_context_profile,
    handle_runtime_snapshot,
    handle_vault_lookup,
)
from .delegation_audit import on_subagent_start, on_subagent_stop
from .guardrails import (
    LCHD_GUARDRAILS_CHECK_SCHEMA,
    handle_guardrails_check,
    on_pre_tool_call,
    on_transform_tool_result,
)
from .orchestrator import (
    LCHD_EXPERT_REGISTRY_SCHEMA,
    LCHD_TASK_FINALIZE_SCHEMA,
    LCHD_TASK_ROUTE_SCHEMA,
    handle_expert_registry,
    handle_task_finalize,
    handle_task_route,
    on_pre_llm_call,
)
from .routing import LCHD_MODEL_POLICY_SCHEMA, handle_model_policy
from .ux import LCHD_HANDOFF_NOTE_SCHEMA, LCHD_STATUS_SCHEMA, handle_handoff_note, handle_status

_TOOLSET = "lchd_personal"


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    ctx.register_hook("transform_tool_result", on_transform_tool_result)
    ctx.register_hook("pre_llm_call", on_pre_llm_call)
    ctx.register_hook("subagent_start", on_subagent_start)
    ctx.register_hook("subagent_stop", on_subagent_stop)
    ctx.register_hook("on_session_end", on_artifact_cleanup_session_end)
    ctx.register_tool(
        name="lchd_context_profile",
        toolset=_TOOLSET,
        schema=LCHD_CONTEXT_PROFILE_SCHEMA,
        handler=handle_context_profile,
        emoji="🧭",
    )
    ctx.register_tool(
        name="lchd_vault_lookup",
        toolset=_TOOLSET,
        schema=LCHD_VAULT_LOOKUP_SCHEMA,
        handler=handle_vault_lookup,
        emoji="🗂️",
    )
    ctx.register_tool(
        name="lchd_runtime_snapshot",
        toolset=_TOOLSET,
        schema=LCHD_RUNTIME_SNAPSHOT_SCHEMA,
        handler=handle_runtime_snapshot,
        emoji="🩺",
    )
    ctx.register_tool(
        name="lchd_guardrails_check",
        toolset=_TOOLSET,
        schema=LCHD_GUARDRAILS_CHECK_SCHEMA,
        handler=handle_guardrails_check,
        emoji="🛡️",
    )
    ctx.register_tool(
        name="lchd_model_policy",
        toolset=_TOOLSET,
        schema=LCHD_MODEL_POLICY_SCHEMA,
        handler=handle_model_policy,
        emoji="💸",
    )
    ctx.register_tool(
        name="lchd_status",
        toolset=_TOOLSET,
        schema=LCHD_STATUS_SCHEMA,
        handler=handle_status,
        emoji="📊",
    )
    ctx.register_tool(
        name="lchd_handoff_note",
        toolset=_TOOLSET,
        schema=LCHD_HANDOFF_NOTE_SCHEMA,
        handler=handle_handoff_note,
        emoji="🧾",
    )
    ctx.register_tool(
        name="lchd_expert_registry",
        toolset=_TOOLSET,
        schema=LCHD_EXPERT_REGISTRY_SCHEMA,
        handler=handle_expert_registry,
        emoji="🧑‍💼",
    )
    ctx.register_tool(
        name="lchd_task_route",
        toolset=_TOOLSET,
        schema=LCHD_TASK_ROUTE_SCHEMA,
        handler=handle_task_route,
        emoji="🧭",
    )
    ctx.register_tool(
        name="lchd_task_finalize",
        toolset=_TOOLSET,
        schema=LCHD_TASK_FINALIZE_SCHEMA,
        handler=handle_task_finalize,
        emoji="🧾",
    )
