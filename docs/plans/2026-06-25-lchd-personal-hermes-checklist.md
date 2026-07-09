# Lchd Personal Hermes — Long-Context Checklist

This file is the compact checklist to read when context gets long or after an interruption. Source plan: `docs/plans/2026-06-25-lchd-personal-hermes.md`.

## North Star

Build Lchd's Hermes into a Chinese-first, cost-aware, self-improving private assistant that remembers stable context, uses Obsidian for long facts, protects high-risk actions, and remains upstream-compatible.

## Ground Rules

- Prefer plugin/skill/config changes before Hermes core edits.
- Do not overwrite existing dirty files.
- Do not print secrets from `.env`, config, auth, tokens, or provider keys.
- Use `get_hermes_home()` for Hermes state paths in code.
- Verify with `scripts/run_tests.sh`, not raw `pytest`.
- Separate reports into **implemented** vs **planned**.
- For public posting/uploading, ask for final confirmation.
- For router tasks, never restart sing-box or edit `/etc/init.d/*` without explicit confirmation.
- For people/image tasks, show full prompt before generation and protect local private images.

## Adopted Architecture Pattern From User Images

- Overall architecture: **dual-engine knowledge base + four specialist collaboration profiles**.
- Dynamic workspace / Wiki: `~/.hermes/wiki/` — high-frequency project state, temporary drafts, coordination notes.
- Durable vault / Obsidian: `/root/Documents/Obsidian Vault/` — reviewed reusable knowledge, SOPs, history, learning notes, code snippets.
- Specialist profiles: `~/.hermes/lchd-profiles/{coordinator,researcher,writer,builder}/SOUL.md`.
- Config integration: `/root/.hermes/config.yaml` has `lchd_personal.mode`, `obsidian_vault_path`, `wiki_root`, and `profiles_dir`.
- Division of labor:
  - Wiki = “活力”：项目状态、临时草案、协同信息，高频实时更新。
  - Obsidian = “库力”：通用知识、历史案例、学习笔记、复用代码，低频审核后归档。

## Current Baseline

- Repo: `/root/hermes-agent`.
- Plan file: `docs/plans/2026-06-25-lchd-personal-hermes.md`.
- Checklist file: `docs/plans/2026-06-25-lchd-personal-hermes-checklist.md`.
- Existing dirty files before implementation:
  - `agent/agent_init.py`
  - `agent/context_compressor.py`
  - `agent/context_engine.py`
  - `package-lock.json`
  - `tests/tools/test_browser_supervisor_healthcheck.py`
  - `tools/browser_supervisor.py`
  - `scripts/a_share_fetch.py`
- New planning files are under `docs/plans/`.
- New dynamic Wiki files are under `~/.hermes/wiki/`.
- New specialist SOUL profiles are under `~/.hermes/lchd-profiles/`.

## Source of Truth Split

- **Roadmap source:** `docs/plans/2026-06-25-lchd-personal-hermes.md` keeps the full phase roadmap.
- **Current dynamic status source:** `~/.hermes/wiki/system/dashboard.md` keeps current state and next task.
- **Durable architecture source:** `/root/Documents/Obsidian Vault/Hermes/Hermes个性化助手.md` keeps stable architecture only.
- **This checklist:** keep compact recovery facts only; do not duplicate the full roadmap.

## Current Next Items

1. **Unified plugin slimdown** — implemented.
   - Earlier split plugins (`lchd-context`, `lchd-guardrails`, `lchd-cost-router`, `lchd-gateway-ux`) were consolidated into one plugin: `lchd-personal-assistant`.
   - Repo source: `plugins/lchd_personal_assistant/`.
   - Active runtime copy: `/root/.hermes/plugins/lchd_personal_assistant/`.
   - Unified toolset: `lchd_personal`.
2. **v0.2 expert orchestrator** — implemented.
   - Tools: `lchd_expert_registry`, `lchd_task_route`, `lchd_task_finalize`.
   - Audit log: `/root/.hermes/wiki/logs/expert_routes.jsonl`.
3. **v0.3 observability + human gate** — implemented.
   - `lchd_status(recent_routes=N)` returns `recent_expert_routes`.
   - `lchd_task_route` returns `risk_level`, `requires_confirmation`, `human_gate` and records them in audit JSONL.
   - `lchd_task_finalize` returns `enforcement` hints for end-of-task persistence review.
4. **Next candidate** — v0.4 expert-driven delegation.
   - Do not add automatic fan-out until route conditions, context trimming, audit logging, and failure rollback are designed.

## First Implementation Slice

Implemented only Phase 1 first:

- Created `plugins/lchd_context/plugin.yaml`.
- Created `plugins/lchd_context/__init__.py`.
- Created `plugins/lchd_context/context.py`.
- Created `tests/plugins/test_lchd_context_plugin.py`.
- Copied the plugin into active user plugin dir: `/root/.hermes/plugins/lchd_context/`.
- Enabled it in `/root/.hermes/config.yaml` with backup `/root/.hermes/config.yaml.bak-lchd-context-1782373392`.
- Tools:
  - `lchd_context_profile`
  - `lchd_vault_lookup`
  - `lchd_runtime_snapshot`

## Phase 1 Acceptance Criteria

- Plugin imports cleanly.
- Tool handlers return JSON strings.
- No secrets in output.
- Obsidian lookup is allowlist-only.
- Config summary masks sensitive keys.
- Tests pass:
  ```bash
  scripts/run_tests.sh tests/plugins/test_lchd_context_plugin.py
  ```
- Final `git diff -- docs/plans plugins/lchd_context tests/plugins/test_lchd_context_plugin.py` contains only intended files.

## Phase 1 Verification Results

- Checkpoint tag created before implementation: `_checkpoint_lchd_personal_1782373035`.
- `scripts/run_tests.sh tests/plugins/test_lchd_context_plugin.py` passed: 5 tests, 0 failures.
- Wrapper initially failed because `.venv` lacked pytest; installed test-only prerequisites into `.venv`: `pytest`, `pytest-xdist`, `pytest-timeout`.
- Direct handler smoke test passed for profile/runtime/vault lookup.
- `hermes plugins list` shows `lchd-context` enabled from user plugins.
- `hermes tools list` shows plugin toolset `lchd_context` enabled.

## Phase 2 Verification Results

- Checkpoint tag created before implementation: `_checkpoint_lchd_guardrails_1782378037`.
- Created `plugins/lchd_guardrails/plugin.yaml`, `__init__.py`, and `guardrails.py`.
- Created `tests/plugins/test_lchd_guardrails_plugin.py`.
- Copied plugin into active user plugin dir: `/root/.hermes/plugins/lchd_guardrails/`.
- Enabled it in `/root/.hermes/config.yaml` with backup `/root/.hermes/config.yaml.bak-lchd-guardrails-1782378161`.
- `scripts/run_tests.sh tests/plugins/test_lchd_context_plugin.py tests/plugins/test_lchd_guardrails_plugin.py` passed: 13 tests, 0 failures.
- `hermes plugins list --plain --no-bundled` shows `lchd-guardrails` enabled.
- `hermes tools list` shows plugin toolset `lchd_guardrails` enabled.

## Resume Prompt

If context is lost, resume with:

> Read `docs/plans/2026-06-25-lchd-personal-hermes-checklist.md`, then continue the next incomplete item. Preserve pre-existing dirty files and verify with `scripts/run_tests.sh`.
