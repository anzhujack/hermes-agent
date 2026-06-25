# Lchd Personal Hermes Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task after the user approves a phase.

**Goal:** Turn this Hermes checkout into Lchd's personalized assistant while keeping upstream compatibility, profile safety, and verifiable tests.

**Architecture:** Prefer user/local plugins under `plugins/` or `~/.hermes/plugins/` and skills under `~/.hermes/skills/` before editing core. Core changes are allowed only when a capability needs new framework hooks or UI surfaces. Every phase is additive, has rollback, and is verified with `scripts/run_tests.sh` plus a live Hermes probe.

**Tech Stack:** Hermes plugin API (`register(ctx)`), config.yaml, skills, cron, MCP, session_search/mem0/memory, Obsidian vault, Discord/Telegram/Weixin gateway.

---

## Current Baseline (2026-06-25)

- Repo: `/root/hermes-agent`, branch `main`.
- Worktree already dirty before this plan: `agent/agent_init.py`, `agent/context_compressor.py`, `agent/context_engine.py`, `package-lock.json`, `tests/tools/test_browser_supervisor_healthcheck.py`, `tools/browser_supervisor.py`, `scripts/a_share_fetch.py`.
- Active config summary:
  - Primary model: `openai-codex` / `gpt-5.5`.
  - Custom providers: `CLIProxyAPI`.
  - Memory provider: `mem0`, built-in memory/user profile enabled.
  - STT: `groq`; TTS: `edge`; image generation: `openai-codex`.
  - Gateways enabled: `discord`, `telegram`.
  - MCP servers configured: `exa`, `github`, `playwright`, `sounding`.
  - Curator enabled weekly; delegation concurrency 3.
- User preference signals:
  - Chinese-first, exact commands, staged execution, explicit implemented-vs-proposed separation.
  - Wants a private Jarvis-like Hermes with memory/environment/todo maintenance under hard guardrails.
  - Cost-aware routing and token-saving matter.
  - Long-term facts belong in Obsidian vault; memory stores compact indexes and preferences.
  - Router/sing-box/CLIProxy/Hermes ops are recurring domains.
  - Final public/social actions require explicit confirmation.

---

## Personalized Feature Backlog

### A. Context & Knowledge Layer

1. **Lchd Context Pack**
   - Purpose: let Hermes quickly know “what matters to Lchd right now” without bloating every prompt.
   - Data sources: memory/mem0 summary, selected Obsidian pages, active repo/config summaries.
   - Tool examples: `lchd_context_profile`, `lchd_vault_lookup`, `lchd_runtime_snapshot`.
   - Value: fewer repeated explanations; safer recall of router/Hermes/sing-box/story-writing context.

2. **Obsidian Source-of-Truth Index**
   - Purpose: keep long facts out of memory and in readable vault pages.
   - Could create a single page: `Hermes/Hermes个性化助手.md`.
   - Stores: capability map, guardrails, recurring workflows, where each domain’s facts live.

3. **Session-to-Knowledge Review**
   - Purpose: after long tasks, propose what should become memory, skill, or Obsidian note.
   - Should be conservative: no automatic large writes; report candidates first unless low-risk.

### B. Safety & Autonomy Layer

1. **Personal Guardrails**
   - Router: no sing-box restart or `/etc/init.d` edits without confirmation.
   - Publishing: B站/社媒/公开发布前必须二次确认。
   - Images:人物图先给完整提示词，再生成；隐私图片本地保护。
   - Gateway restart: after interruption, check PID/uptime/logs before proposing another restart.

2. **Action Risk Classifier**
   - Purpose: label actions as read-only / local write / service restart / public side effect / irreversible.
   - Output: short pre-action reminder and verification checklist.
   - This can start as a plugin warning; only later become hard blocking.

3. **Rollback-Aware Coding Workflow**
   - Purpose: before multi-file edits, create checkpoint/branch; never overwrite unknown dirty files.
   - Integrates with existing `checkpoint-rollback` habits.

### C. Cost & Model Routing Layer

1. **Cost-Aware Routing Report**
   - Shows current primary/fallback/auxiliary model routes.
   - Recommends cheaper side models for title/session_search/web_extract/approval.
   - Keeps main model strong for coding and high-stakes reasoning.

2. **Usage Digest**
   - Local JSONL summary of expensive sessions/tasks.
   - Weekly report: what consumed tokens, what could move to cheaper models, what skills could reduce context.

3. **Provider Health Panel**
   - Minimal live probes for configured custom providers/fallbacks.
   - No secret printing.
   - Helps catch broken relays before a long task fails mid-way.

### D. Dev/Ops Specialist Layer

1. **Router Health Assistant**
   - Non-destructive checks: disk, memory, DNS, sing-box state, nft rules, Docker state.
   - Explicitly does not restart or rewrite configs unless confirmed.

2. **CLIProxy / Relay Auditor Shortcut**
   - Standardizes relay checks: model list, protocol mode, hidden prompt injection, stream behavior, latency.
   - Saves reports to `/tmp` or Obsidian, not memory.

3. **Hermes Self-Diagnostics**
   - One command/tool to collect: version, git commit, gateway PID/uptime, config summary, MCP list, tools list, latest errors.
   - Designed for “为什么 Hermes 又不对劲了”快速定位。

### E. Creative & Publishing Layer

1. **Image Prompt Studio**
   - Implements your preferred structure: overall style → strict identity lock → scene → pose → outfit fusion → photography → avoid.
   - Shows full prompt first; generation only after approval if needed.

2. **Story Writing Workspace Assistant**
   - Knows `/root/从火塘开始养文明/` project layout.
   - Helps maintain character/plot/world bible, chapter outlines, and 番茄投稿流程。

3. **Media Production Pipeline**
   - For B站/视频: script → assets → edit checklist → upload confirmation gate.
   - Public publish remains manual-confirmed.

### F. Gateway UX Layer

1. **Chinese Phase Recap Mode**
   - Long tasks end with: 已完成 / 未完成 / 验证结果 / 下一步。
   - Keeps Discord/Telegram responses readable.

2. **`/lchd status` or Plugin Tool Equivalent**
   - Reports model, gateway, memory, MCP, cron, plugin state.
   - If core slash command is too invasive, start as a tool exposed by plugin.

3. **Handoff Summary Generator**
   - When tasks are interrupted or long-running, writes a compact handoff summary for continuation.

### Priority Recommendation

- **First build:** A1 + B1 + C1, because they directly reduce repeated context, prevent known accidents, and control cost.
- **Second build:** D1 + D3, because your router/Hermes ops are recurring and high-value.
- **Third build:** E1 + E2, because creative workflows benefit from persistent structure but are lower operational risk.

---

## Phase 0: Safety Rails Before Coding

**Objective:** Avoid corrupting existing uncommitted work and establish rollback.

**Files:**
- Inspect: current git diff.
- Create: optional checkpoint branch or stash only after user confirms handling of existing dirty files.

**Steps:**
1. Run `git status --short` and `git diff --stat`.
2. Ask user whether existing dirty files are theirs and whether to keep them in place, branch them, or stash them.
3. For approved implementation, create a checkpoint branch:
   ```bash
   git switch -c lchd-personal-hermes-$(date +%Y%m%d)
   ```
4. Do not overwrite existing dirty files unless explicitly approved.

**Verification:** `git status --short` clearly separates pre-existing changes from new plan/plugin files.

---

## Phase 1: Lchd Context Pack Plugin (low risk, additive)

**Objective:** Add a local plugin that exposes personalized context tools without modifying core.

**Files:**
- Create: `plugins/lchd_context/plugin.yaml`
- Create: `plugins/lchd_context/__init__.py`
- Create: `plugins/lchd_context/context.py`
- Test: `tests/plugins/test_lchd_context_plugin.py`

**Tool candidates:**
1. `lchd_context_profile` — returns a sanitized, compact overview of relevant local context sources.
2. `lchd_vault_lookup` — reads allowlisted Obsidian pages by logical key, e.g. `router_singbox`, `nft_dns`, `nsfw_image_chain`, never scans the whole vault by default.
3. `lchd_runtime_snapshot` — returns non-secret status: Hermes config summary, active gateways, model/provider names, MCP server names.

**Guardrails:**
- Use `get_hermes_home()` and `Path.home()` carefully; no hardcoded profile state except allowlisted user paths.
- Never return secrets from `.env` or raw config values containing keys/tokens.
- Obsidian access is allowlist-only: no arbitrary file reads through this plugin.

**Verification:**
```bash
scripts/run_tests.sh tests/plugins/test_lchd_context_plugin.py
hermes plugins list | grep -i lchd || true
```

---

## Phase 2: Personal Guardrails Plugin

**Objective:** Add fast, deterministic reminders for Lchd-specific risky actions.

**Files:**
- Create: `plugins/lchd_guardrails/plugin.yaml`
- Create: `plugins/lchd_guardrails/__init__.py`
- Test: `tests/plugins/test_lchd_guardrails_plugin.py`

**Rules:**
1. Before commands that restart gateway/services, remind to check PID/uptime if a restart just occurred.
2. For router tasks, warn not to restart sing-box or edit `/etc/init.d/*` without explicit confirmation.
3. For public posting/uploading tasks, require explicit final confirmation.
4. For image generation involving people, remind: show full prompt first, privacy-safe handling, prefer MEDIA output.

**Implementation style:**
- Use plugin hooks similar to `plugins/security-guidance`.
- Warning/reminder first; block only for high-risk public posting or router service mutation without explicit approval metadata.

**Verification:**
```bash
scripts/run_tests.sh tests/plugins/test_lchd_guardrails_plugin.py
```

---

## Phase 3: Cost-Aware Routing Assistant

**Objective:** Help Hermes choose cheaper/faster side models and track when expensive models are actually needed.

**Files:**
- Create: `plugins/lchd_cost_router/plugin.yaml`
- Create: `plugins/lchd_cost_router/__init__.py`
- Optional core hook only if existing plugin hooks cannot observe enough provider metadata.
- Test: `tests/plugins/test_lchd_cost_router_plugin.py`

**Features:**
1. Tool `lchd_model_policy` returns current main/fallback/auxiliary routing and suggested cheaper alternatives.
2. Optional `post_llm_call` hook logs per-session estimated usage to a local JSONL file under `get_hermes_home()/usage/lchd_cost_router.jsonl`.
3. A daily/weekly report can summarize expensive sessions and candidates for cheaper routing.

**Verification:**
```bash
scripts/run_tests.sh tests/plugins/test_lchd_cost_router_plugin.py
hermes chat -q '只回复 pong' -Q --toolsets safe
```

---

## Phase 4: Obsidian Knowledge Workflow

**Objective:** Make Hermes use the vault consistently without dumping large context into memory.

**Files:**
- Create or update: `/root/Documents/Obsidian Vault/Hermes/Hermes个性化助手.md`
- Optional skill updates: `obsidian-knowledge-governance`, `hermes-agent` references if gaps are found.

**Content:**
- Index of personalized capabilities and where facts live.
- Rules: memory vs mem0 vs Obsidian vs skills.
- Router/network/Hermes/fiction-writing source-of-truth pages.

**Verification:** use `read_file` on the created page and confirm it follows the vault schema.

---

## Phase 5: Gateway UX / Discord Thread Personalization

**Objective:** Improve how Hermes behaves in Discord/Telegram/Weixin for Lchd.

**Possible features:**
1. Chinese-first concise phase recap footer for long tasks.
2. `/lchd status` slash/quick command that reports gateway/model/memory/plugin health.
3. Thread-aware handoff summaries for long-running tasks.

**Core edit warning:** slash command registry changes touch core (`hermes_cli/commands.py`, gateway/CLI dispatch) and must be implemented only after plugin-only options are insufficient.

**Verification:** unit tests for command catalog + live gateway `/status` style check after restart.

---

## Phase 6: Recurring Maintenance Jobs

**Objective:** Add cost-aware and safety-aware maintenance jobs without runaway autonomy.

**Jobs:**
1. Weekly memory/skill review using toolsets `session_search`, `memory`, `skills`, `file`; do not attach `hermes-agent` skill to cron.
2. Router health report: non-destructive only; never restart sing-box without asking.
3. Provider/fallback health report: minimal live probes, no key leakage.

**Verification:** create scripts under `~/.hermes/scripts/`, pass only script filenames to cron, run each job once with `cronjob run`, inspect `~/.hermes/cron/output/<job_id>/` and logs.

---

## Acceptance Criteria

A phase is complete only when:
- Tests for new plugin/feature pass via `scripts/run_tests.sh`.
- No secrets are printed or persisted.
- `git diff` contains only intended files.
- A live Hermes probe confirms the capability is discoverable or usable.
- The final report separates **implemented** from **planned** work.

## First Recommended Implementation Slice

Start with **Phase 1 only**:
- It is additive.
- It does not require gateway restart until enabled.
- It builds a clean base for later personalized tools.
- It can be tested without touching the current dirty core files.
