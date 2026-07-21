"""Tests for the unified Lchd personal assistant plugin."""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest
import yaml


@pytest.fixture(autouse=True)
def _isolated_lchd_home(tmp_path, monkeypatch):
    hermes_home = tmp_path / ".hermes"
    vault = tmp_path / "vault"
    profiles = hermes_home / "lchd-profiles"
    wiki = hermes_home / "wiki"
    hermes_home.mkdir()
    vault.mkdir()
    (vault / "Home.md").write_text("# Home\n", encoding="utf-8")
    (vault / "Hermes").mkdir()
    (vault / "Hermes" / "Hermes个性化助手.md").write_text("# Personal\n", encoding="utf-8")
    for role in ["coordinator", "researcher", "writer", "builder"]:
        d = profiles / role
        d.mkdir(parents=True, exist_ok=True)
        (d / "SOUL.md").write_text(f"# {role}\n", encoding="utf-8")
    wiki.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("LCHD_OBSIDIAN_VAULT", str(vault))
    (hermes_home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "model": {"provider": "openai-codex", "default": "gpt-5.5", "api_key": "SECRET"},
                "plugins": {"enabled": ["lchd-personal-assistant"]},
                "lchd_personal": {
                    "wiki_root": str(wiki),
                    "obsidian_vault_path": str(vault),
                    "profiles_dir": str(profiles),
                    "mode": "dual_engine_knowledge_base_with_specialist_profiles",
                },
                "fallback_providers": [{"provider": "custom:CLIProxyAPI", "model": "glm-5.2"}],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return hermes_home


def _load_package():
    repo_root = Path(__file__).resolve().parents[2]
    plugin_dir = repo_root / "plugins" / "lchd_personal_assistant"
    if "hermes_plugins" not in sys.modules:
        ns = types.ModuleType("hermes_plugins")
        ns.__path__ = []
        sys.modules["hermes_plugins"] = ns
    spec = importlib.util.spec_from_file_location(
        "hermes_plugins.lchd_personal_assistant",
        plugin_dir / "__init__.py",
        submodule_search_locations=[str(plugin_dir)],
    )
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "hermes_plugins.lchd_personal_assistant"
    mod.__path__ = [str(plugin_dir)]
    sys.modules["hermes_plugins.lchd_personal_assistant"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_unified_plugin_registers_all_tools_and_hooks():
    plugin = _load_package()

    class Ctx:
        def __init__(self):
            self.tools = []
            self.hooks = []

        def register_tool(self, **kwargs):
            self.tools.append(kwargs)

        def register_hook(self, name, fn):
            self.hooks.append((name, fn))

    ctx = Ctx()
    plugin.register(ctx)

    assert [tool["name"] for tool in ctx.tools] == [
        "lchd_context_profile",
        "lchd_vault_lookup",
        "lchd_runtime_snapshot",
        "lchd_guardrails_check",
        "lchd_model_policy",
        "lchd_status",
        "lchd_handoff_note",
        "lchd_expert_registry",
        "lchd_task_route",
        "lchd_task_finalize",
    ]
    assert {tool["toolset"] for tool in ctx.tools} == {"lchd_personal"}
    assert [name for name, _ in ctx.hooks] == [
        "pre_tool_call",
        "transform_tool_result",
        "pre_llm_call",
        "subagent_start",
        "subagent_stop",
        "on_session_end",
    ]
    assert plugin.__file__ is not None
    metadata = yaml.safe_load((Path(plugin.__file__).with_name("plugin.yaml")).read_text(encoding="utf-8"))
    assert metadata["version"] == "0.7.0"
    assert metadata["hooks"] == [
        "pre_tool_call",
        "transform_tool_result",
        "pre_llm_call",
        "subagent_start",
        "subagent_stop",
        "on_session_end",
    ]


def test_task_route_schema_discourages_routing_and_delegating_simple_tasks():
    plugin = _load_package()

    description = plugin.LCHD_TASK_ROUTE_SCHEMA["description"].lower()

    assert "non-trivial" in description
    assert "simple" in description
    assert "recommended" in description
    assert "dispatch_allowed" in description


def test_context_vault_and_runtime_handlers_work():
    plugin = _load_package()

    profile = json.loads(plugin.handle_context_profile({}))
    assert profile["profile"]["architecture"] == "dual-engine knowledge base + four specialist SOUL profiles"
    assert all(profile["profile"]["profile_roles"].values())

    note = json.loads(plugin.handle_vault_lookup({"key": "home"}))
    assert note["ok"] is True
    assert note["key"] == "home"

    bad = json.loads(plugin.handle_vault_lookup({"key": "../../etc/passwd"}))
    assert bad["ok"] is False
    assert bad["error"] == "unknown_vault_key"

    snap = json.loads(plugin.handle_runtime_snapshot({}))
    assert snap["runtime"]["model"]["provider"] == "openai-codex"
    assert "api_key" not in json.dumps(snap).lower()


def test_guardrails_and_routing_handlers_work():
    plugin = _load_package()

    blocked = json.loads(plugin.handle_guardrails_check({"tool_name": "terminal", "args": {"command": "/etc/init.d/sing-box restart"}}))
    assert blocked["allowed"] is False
    assert blocked["findings"][0]["id"] == "router_service_mutation"

    allowed = json.loads(plugin.handle_guardrails_check({"tool_name": "terminal", "args": {"command": "echo safe"}}))
    assert allowed["allowed"] is True

    policy = json.loads(plugin.handle_model_policy({}))
    assert policy["primary"]["provider"] == "openai-codex"
    assert policy["fallbacks"]["fallback_providers"][0]["provider"] == "custom:CLIProxyAPI"
    assert "SECRET" not in json.dumps(policy)


def test_status_and_handoff_handlers_work(_isolated_lchd_home):
    plugin = _load_package()

    audit_path = _isolated_lchd_home / "wiki" / "logs" / "expert_routes.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        "\n".join(
            json.dumps(record, ensure_ascii=False)
            for record in [
                {
                    "ts": "2026-01-01T00:00:00+00:00",
                    "task": "旧任务",
                    "task_type": "research",
                    "execution_mode": "parallel_research",
                    "experts": ["coordinator", "researcher", "writer"],
                    "risk_level": "low",
                    "requires_confirmation": False,
                },
                {
                    "ts": "2026-01-02T00:00:00+00:00",
                    "task": "新任务",
                    "task_type": "hermes_dev",
                    "classification_source": "task",
                    "complexity": "non_trivial",
                    "execution_mode": "builder_review",
                    "experts": ["coordinator", "builder", "writer"],
                    "risk_level": "medium",
                    "requires_confirmation": False,
                    "delegation_summary": {
                        "recommended": True,
                        "mode": "builder_review",
                        "dispatch_allowed": True,
                        "task_count": 2,
                    },
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    status = json.loads(plugin.handle_status({"recent_routes": 1}))
    assert status["plugins"] == {"lchd-personal-assistant": True}
    assert status["toolset"] == "lchd_personal"
    assert [route["task"] for route in status["recent_expert_routes"]] == ["新任务"]
    assert status["recent_expert_routes"][0]["risk_level"] == "medium"
    assert status["recent_expert_routes"][0]["classification_source"] == "task"
    assert status["recent_expert_routes"][0]["complexity"] == "non_trivial"
    assert status["recent_expert_routes"][0]["delegation_summary"] == {
        "recommended": True,
        "mode": "builder_review",
        "dispatch_allowed": True,
        "task_count": 2,
    }
    route_guidance = status["中文阶段摘要"]["下一步"]
    assert "复杂任务" in route_guidance
    assert "简单" in route_guidance
    assert "delegation.recommended" in route_guidance
    assert "dispatch_allowed" in route_guidance

    result = json.loads(plugin.handle_handoff_note({"title": "瘦身测试", "completed": ["ok"], "next_step": "done"}))
    path = Path(result["path"])
    assert path.exists()
    assert "## 已完成" in path.read_text(encoding="utf-8")


def test_expert_registry_reads_soul_profiles_without_being_status_only():
    plugin = _load_package()

    registry = json.loads(plugin.handle_expert_registry({"max_chars": 120}))

    assert registry["ok"] is True
    assert registry["profiles_dir"].endswith("lchd-profiles")
    assert set(registry["experts"]) == {"coordinator", "researcher", "writer", "builder"}
    assert all(item["available"] for item in registry["experts"].values())
    assert registry["experts"]["builder"]["soul_excerpt"].startswith("# builder")
    assert "task_types" in registry["experts"]["researcher"]


def test_task_route_keeps_generic_action_menu_general_when_context_only_mentions_hermes(_isolated_lchd_home):
    plugin = _load_package()

    route = json.loads(plugin.handle_task_route({
        "task": "梳理当前最值得立即开展的事项，并给出可直接回复编号启动的行动菜单。",
        "context": "用户泛问现在还能做什么；请基于当前 Hermes 个性化状态、近期项目与长期偏好回答。",
    }))

    assert route["ok"] is True
    assert route["task_type"] == "general"
    assert route["execution_mode"] == "guided_direct"
    assert route["experts"] == ["coordinator", "writer"]
    assert route["risk_level"] == "low"
    assert route["delegation"]["recommended"] is False
    assert route["delegation"]["dispatch_allowed"] is False
    assert route["delegation"]["tasks"] == []


def test_task_route_does_not_treat_hermes_domain_nouns_as_development(_isolated_lchd_home):
    plugin = _load_package()

    route = json.loads(plugin.handle_task_route({"task": "Hermes 现在有哪些能力？"}))

    assert route["task_type"] == "general"
    assert route["execution_mode"] == "guided_direct"
    assert route["delegation"]["recommended"] is False


def test_task_route_requires_hermes_domain_for_code_actions(_isolated_lchd_home):
    plugin = _load_package()

    route = json.loads(plugin.handle_task_route({"task": "写代码实现一个本地 CSV 去重脚本"}))

    assert route["task_type"] == "general"
    assert route["classification_source"] == "task"
    assert route["delegation"]["recommended"] is False


def test_task_route_keeps_simple_hermes_change_direct(_isolated_lchd_home):
    plugin = _load_package()

    route = json.loads(plugin.handle_task_route({
        "task": "修复 Hermes 插件里的一个拼写错误",
        "context": "这是 v0.5 系统性版本升级中的一个背景事项。",
    }))

    assert route["task_type"] == "hermes_dev"
    assert route["classification_source"] == "task"
    assert route["complexity"] == "simple"
    assert route["experts"] == ["coordinator", "builder"]
    assert route["delegation"]["mode"] == "none"
    assert route["delegation"]["recommended"] is False
    assert route["delegation"]["dispatch_allowed"] is False
    assert route["delegation"]["tasks"] == []


@pytest.mark.parametrize(
    ("task", "context", "task_type", "complexity", "experts", "recommended"),
    [
        (
            "查一下 Hermes 当前最新版本",
            "",
            "research",
            "simple",
            ["coordinator", "researcher"],
            False,
        ),
        (
            "联网调研并比较三种 Hermes 委派方案，要求多来源交叉核验",
            "",
            "research",
            "non_trivial",
            ["coordinator", "researcher", "writer"],
            True,
        ),
        (
            "把这句话润色一下",
            "",
            "writing",
            "simple",
            ["coordinator", "writer"],
            False,
        ),
        (
            "撰写一份完整的多章节项目报告，并统一结构和叙事",
            "",
            "writing",
            "non_trivial",
            ["coordinator", "writer"],
            True,
        ),
        (
            "检查 sing-box 服务状态",
            "",
            "ops",
            "simple",
            ["coordinator", "builder"],
            False,
        ),
        (
            "系统性诊断 sing-box DNS 故障，检查日志和配置，不重启服务",
            "",
            "ops",
            "non_trivial",
            ["coordinator", "builder", "researcher"],
            True,
        ),
        (
            "推进 Personal Hermes v0.5，优化任务分类与自动委派并补齐回归测试",
            "",
            "hermes_dev",
            "non_trivial",
            ["coordinator", "builder", "writer"],
            True,
        ),
        (
            "审计三家 AI API 中转站的真实性、安全性和供应链风险，要求交叉核验",
            "",
            "research",
            "non_trivial",
            ["coordinator", "researcher", "writer"],
            True,
        ),
        (
            "制作一条完整 AI 动画视频，从脚本、分镜、配音到成片",
            "",
            "media_production",
            "non_trivial",
            ["coordinator", "writer", "builder"],
            True,
        ),
        (
            "只读诊断当前网络连通性问题，检查代理日志和配置，不做修改",
            "",
            "ops",
            "non_trivial",
            ["coordinator", "builder", "researcher"],
            True,
        ),
    ],
)
def test_task_route_classification_and_delegation_matrix(
    _isolated_lchd_home,
    task,
    context,
    task_type,
    complexity,
    experts,
    recommended,
):
    plugin = _load_package()

    route = json.loads(plugin.handle_task_route({"task": task, "context": context}))

    assert route["task_type"] == task_type
    assert route["complexity"] == complexity
    assert route["experts"] == experts
    assert route["delegation"]["recommended"] is recommended
    assert route["delegation"]["dispatch_allowed"] is recommended


def test_task_route_uses_context_only_for_referential_tasks(_isolated_lchd_home):
    plugin = _load_package()
    context = "当前正在优化 Hermes 插件路由并跑回归测试。"

    referential = json.loads(plugin.handle_task_route({"task": "继续处理这个", "context": context}))
    terse = json.loads(plugin.handle_task_route({"task": "继续", "context": context}))
    standalone = json.loads(plugin.handle_task_route({"task": "给我列一个行动菜单", "context": context}))

    assert referential["task_type"] == "hermes_dev"
    assert referential["classification_source"] == "context"
    assert referential["complexity"] == "non_trivial"
    assert referential["delegation"]["recommended"] is True
    assert terse["task_type"] == "hermes_dev"
    assert terse["classification_source"] == "context"
    assert terse["delegation"]["recommended"] is True
    assert standalone["task_type"] == "general"
    assert standalone["classification_source"] == "task"
    assert standalone["complexity"] == "simple"
    assert standalone["delegation"]["recommended"] is False


def test_task_route_requires_ops_action_not_just_domain_noun(_isolated_lchd_home):
    plugin = _load_package()

    route = json.loads(plugin.handle_task_route({"task": "sing-box 是什么？"}))
    intro = json.loads(plugin.handle_task_route({"task": "请写一段 Hermes 功能介绍"}))
    implementation = json.loads(plugin.handle_task_route({
        "task": "联网查官方文档后修复 Hermes 插件路由并跑回归测试",
    }))

    assert route["task_type"] == "general"
    assert route["delegation"]["recommended"] is False
    assert intro["task_type"] == "writing"
    assert intro["delegation"]["recommended"] is False
    assert implementation["task_type"] == "hermes_dev"
    assert implementation["complexity"] == "non_trivial"
    assert implementation["delegation"]["recommended"] is True


@pytest.mark.parametrize(
    "task",
    [
        "不用联网，直接解释 Hermes 是什么",
        "不要改代码，只介绍 Hermes 插件能力",
        "无需修改 Hermes，给我一个行动菜单",
    ],
)
def test_negated_actions_do_not_promote_generic_tasks(_isolated_lchd_home, task):
    plugin = _load_package()

    route = json.loads(plugin.handle_task_route({"task": task}))

    assert route["task_type"] == "general"
    assert route["classification_source"] == "task"
    assert route["complexity"] == "simple"
    assert route["delegation"]["recommended"] is False


def test_background_context_does_not_trigger_human_gate(_isolated_lchd_home):
    plugin = _load_package()

    route = json.loads(plugin.handle_task_route({
        "task": "检查 sing-box 服务状态",
        "context": "历史记录：昨天曾重启 sing-box 服务，今天只需读取状态。",
    }))
    referential = json.loads(plugin.handle_task_route({
        "task": "继续执行刚才那一步",
        "context": "当前待执行动作是重启 sing-box 服务。",
    }))

    assert route["task_type"] == "ops"
    assert route["risk_level"] == "medium"
    assert route["human_gate"]["required"] is False
    assert referential["task_type"] == "ops"
    assert referential["classification_source"] == "context"
    assert referential["risk_level"] == "high"
    assert referential["human_gate"]["required"] is True
    assert referential["delegation"]["dispatch_allowed"] is False


def test_pre_llm_routing_hint_hardens_parent_agent_habit():
    plugin = _load_package()

    direct = plugin.on_pre_llm_call(
        user_message="Hermes 现在有哪些能力？",
        conversation_history=[],
        platform="discord",
    )
    routed = plugin.on_pre_llm_call(
        user_message="推进 Personal Hermes v0.5，优化任务分类与自动委派并补齐回归测试",
        conversation_history=[],
        platform="discord",
    )
    continuation = plugin.on_pre_llm_call(
        user_message="继续",
        conversation_history=[{"role": "user", "content": "优化 Hermes 插件路由"}],
        platform="discord",
    )

    assert "handling=direct" in direct["context"]
    assert "task_type=general" in direct["context"]
    assert "do not call delegate_task" in direct["context"].lower()
    assert "handling=route_first" in routed["context"]
    assert "task_type=hermes_dev" in routed["context"]
    assert "delegation.recommended=true" in routed["context"]
    assert "dispatch_allowed=true" in routed["context"]
    assert "task_type=continuation" in continuation["context"]
    assert "classification_source=conversation_history" in continuation["context"]
    assert "conversation_history=available" in continuation["context"]
    assert "call lchd_task_route once" in continuation["context"]
    assert plugin.on_pre_llm_call(user_message="anything", platform="subagent") is None


def test_pre_llm_direct_hint_preserves_high_risk_human_gate():
    plugin = _load_package()

    result = plugin.on_pre_llm_call(
        user_message="重启 sing-box 服务",
        conversation_history=[],
        platform="discord",
    )

    assert "handling=direct" in result["context"]
    assert "human_gate.required=true" in result["context"]
    assert "explicit confirmation" in result["context"].lower()
    assert "do not call delegate_task" in result["context"].lower()


def test_task_route_selects_experts_and_records_audit_file(_isolated_lchd_home):
    plugin = _load_package()

    route = json.loads(plugin.handle_task_route({"task": "继续推进 Hermes v0.2，写代码实现四专家任务路由并跑测试"}))

    assert route["ok"] is True
    assert route["task_type"] == "hermes_dev"
    assert route["execution_mode"] == "builder_review"
    assert route["experts"][0] == "coordinator"
    assert "builder" in route["experts"]
    assert "scripts/run_tests.sh tests/plugins/test_lchd_personal_assistant_plugin.py" in route["verification"]
    assert route["version"] == "0.7.0"
    assert route["risk_level"] == "medium"
    assert route["requires_confirmation"] is False
    assert route["human_gate"]["required"] is False
    assert route["delegation"]["mode"] == "builder_review"
    assert route["delegation"]["recommended"] is True
    assert route["delegation"]["dispatch_allowed"] is True
    audit_path = Path(route["audit_path"])
    assert audit_path.exists()
    audit = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[-1])
    assert audit["task_type"] == "hermes_dev"
    assert audit["risk_level"] == "medium"
    assert audit["delegation_summary"] == {
        "recommended": True,
        "mode": "builder_review",
        "dispatch_allowed": True,
        "task_count": 2,
    }

    route_only = json.loads(plugin.handle_task_route({"task": "v0.2 四专家路由最终验证"}))
    assert route_only["task_type"] == "hermes_dev"


def test_task_route_audit_redacts_secret_like_values(_isolated_lchd_home):
    plugin = _load_package()
    task = (
        "检查 Hermes 配置 api_key=credential-value-123 "
        "password=example-pass-456 Authorization: Bearer example-token-789"
    )

    route = json.loads(plugin.handle_task_route({"task": task}))
    audit = json.loads(Path(route["audit_path"]).read_text(encoding="utf-8").splitlines()[-1])
    serialized = json.dumps(audit, ensure_ascii=False)

    assert "[REDACTED]" in audit["task"]
    assert "credential-value-123" not in serialized
    assert "example-pass-456" not in serialized
    assert "example-token-789" not in serialized


def test_delegation_context_injects_only_the_selected_expert_soul(_isolated_lchd_home):
    plugin = _load_package()
    profiles = _isolated_lchd_home / "lchd-profiles"
    (profiles / "researcher" / "SOUL.md").write_text(
        "RESEARCHER-SOUL: authority-first cross-checking", encoding="utf-8"
    )
    (profiles / "writer" / "SOUL.md").write_text(
        "WRITER-SOUL: concise synthesis", encoding="utf-8"
    )

    route = json.loads(
        plugin.handle_task_route(
            {"task": "联网调研并比较多个方案，要求多来源交叉核验", "context": ""}
        )
    )
    tasks = route["delegation"]["tasks"]
    researcher_context = next(task["context"] for task in tasks if task["expert"] == "researcher")
    writer_context = next(task["context"] for task in tasks if task["expert"] == "writer")

    assert "RESEARCHER-SOUL: authority-first cross-checking" in researcher_context
    assert "WRITER-SOUL: concise synthesis" not in researcher_context
    assert "WRITER-SOUL: concise synthesis" in writer_context
    assert "RESEARCHER-SOUL: authority-first cross-checking" not in writer_context


def test_subagent_execution_audit_records_safe_lifecycle(_isolated_lchd_home):
    plugin = _load_package()

    plugin.on_subagent_start(
        parent_session_id="parent-session-sensitive",
        parent_turn_id="turn-sensitive",
        child_session_id="child-session-sensitive",
        child_subagent_id="child-sa-sensitive",
        child_role="researcher",
        child_goal="research with api_key=sk-live-super-secret",
    )
    plugin.on_subagent_stop(
        parent_session_id="parent-session-sensitive",
        parent_turn_id="turn-sensitive",
        child_session_id="child-session-sensitive",
        child_role="researcher",
        child_summary="Bearer secret-summary-token",
        child_status="completed",
        duration_ms=1234,
    )

    audit_path = _isolated_lchd_home / "wiki" / "logs" / "delegation_executions.jsonl"
    rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert [row["event"] for row in rows] == ["subagent_start", "subagent_stop"]
    assert rows[0]["child_session_ref"] == rows[1]["child_session_ref"]
    assert rows[1]["status"] == "completed"
    assert rows[1]["duration_ms"] == 1234
    serialized = json.dumps(rows, ensure_ascii=False)
    for secret in (
        "parent-session-sensitive",
        "turn-sensitive",
        "child-session-sensitive",
        "child-sa-sensitive",
        "sk-live-super-secret",
        "secret-summary-token",
    ):
        assert secret not in serialized
    assert "child_goal" not in serialized
    assert "child_summary" not in serialized


def test_task_route_marks_human_gate_for_high_risk_ops(_isolated_lchd_home):
    plugin = _load_package()

    route = json.loads(plugin.handle_task_route({"task": "重启 sing-box 服务并修改启动脚本"}))

    assert route["ok"] is True
    assert route["task_type"] == "ops"
    assert route["risk_level"] == "high"
    assert route["requires_confirmation"] is True
    assert route["human_gate"]["required"] is True
    assert route["human_gate"]["reason"]
    assert route["delegation"]["mode"] == "guarded_diagnosis"
    assert route["delegation"]["recommended"] is False
    assert route["delegation"]["dispatch_allowed"] is False
    assert route["delegation"]["blocked_until_confirmation"] is True


def test_task_route_builds_parallel_research_delegation_plan(_isolated_lchd_home):
    plugin = _load_package()

    route = json.loads(plugin.handle_task_route({"task": "联网搜索 Hermes delegate_task 和多智能体 human-in-the-loop 方案，给我 v0.4 方案"}))

    assert route["ok"] is True
    assert route["version"] == "0.7.0"
    assert route["task_type"] == "research"
    assert route["delegation"]["recommended"] is True
    assert route["delegation"]["mode"] == "parallel_research"
    assert route["delegation"]["dispatch_allowed"] is True
    assert 1 <= len(route["delegation"]["tasks"]) <= 3
    assert {task["expert"] for task in route["delegation"]["tasks"]} <= {"researcher", "writer"}
    assert "cite authoritative sources" in route["delegation"]["parent_verification"]
    assert "toolsets" not in json.dumps(route["delegation"], ensure_ascii=False)


def test_task_route_builds_builder_review_delegation_plan(_isolated_lchd_home):
    plugin = _load_package()

    route = json.loads(plugin.handle_task_route({"task": "实现 lchd personal assistant v0.4 delegation planner 并跑测试"}))

    assert route["ok"] is True
    assert route["task_type"] == "hermes_dev"
    assert route["delegation"]["mode"] == "builder_review"
    assert route["delegation"]["recommended"] is True
    assert route["delegation"]["dispatch_allowed"] is True
    assert route["delegation"]["tasks"][0]["expert"] == "builder"
    assert route["delegation"]["tasks"][1]["expert"] == "coordinator"
    assert "scripts/run_tests.sh tests/plugins/test_lchd_personal_assistant_plugin.py" in route["delegation"]["parent_verification"]
    assert "toolsets" not in json.dumps(route["delegation"], ensure_ascii=False)


def test_task_route_does_not_escalate_negated_restart_language(_isolated_lchd_home):
    plugin = _load_package()

    route = json.loads(plugin.handle_task_route({"task": "v0.3 写代码验证，不重启服务"}))

    assert route["ok"] is True
    assert route["task_type"] == "hermes_dev"
    assert route["risk_level"] == "medium"
    assert route["requires_confirmation"] is False
    assert route["human_gate"]["required"] is False


def test_task_finalize_recommends_persistence_targets(_isolated_lchd_home):
    plugin = _load_package()

    decision = json.loads(plugin.handle_task_finalize({
        "summary": "实现了四专家任务路由器，新增插件工具和 pytest 覆盖。",
        "files_changed": ["plugins/lchd_personal_assistant/orchestrator.py", "tests/plugins/test_lchd_personal_assistant_plugin.py"],
        "verification": ["scripts/run_tests.sh tests/plugins/test_lchd_personal_assistant_plugin.py"],
    }))

    assert decision["ok"] is True
    assert decision["version"] == "0.7.0"
    assert decision["recommendations"]["write_handoff"] is True
    assert decision["recommendations"]["update_wiki"] is True
    assert decision["recommendations"]["suggest_skill"] is True
    assert decision["enforcement"]["must_review_before_final"] is True
    assert "write_handoff" in decision["enforcement"]["recommended_actions"]
    assert "do_not_save_task_progress_to_memory" in decision["enforcement"]["non_actions"]
    assert "plugins/lchd_personal_assistant/orchestrator.py" in decision["changed_files"]
