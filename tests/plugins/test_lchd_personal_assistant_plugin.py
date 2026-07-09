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
    assert [name for name, _ in ctx.hooks] == ["pre_tool_call", "transform_tool_result"]


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
    assert status["recent_expert_routes"][0]["delegation_summary"] == {
        "recommended": True,
        "mode": "builder_review",
        "dispatch_allowed": True,
        "task_count": 2,
    }

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


def test_task_route_selects_experts_and_records_audit_file(_isolated_lchd_home):
    plugin = _load_package()

    route = json.loads(plugin.handle_task_route({"task": "继续推进 Hermes v0.2，写代码实现四专家任务路由并跑测试"}))

    assert route["ok"] is True
    assert route["task_type"] == "hermes_dev"
    assert route["execution_mode"] == "builder_review"
    assert route["experts"][0] == "coordinator"
    assert "builder" in route["experts"]
    assert "scripts/run_tests.sh tests/plugins/test_lchd_personal_assistant_plugin.py" in route["verification"]
    assert route["version"] == "0.4.0"
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
    assert route["version"] == "0.4.0"
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
    assert decision["version"] == "0.4.0"
    assert decision["recommendations"]["write_handoff"] is True
    assert decision["recommendations"]["update_wiki"] is True
    assert decision["recommendations"]["suggest_skill"] is True
    assert decision["enforcement"]["must_review_before_final"] is True
    assert "write_handoff" in decision["enforcement"]["recommended_actions"]
    assert "do_not_save_task_progress_to_memory" in decision["enforcement"]["non_actions"]
    assert "plugins/lchd_personal_assistant/orchestrator.py" in decision["changed_files"]
