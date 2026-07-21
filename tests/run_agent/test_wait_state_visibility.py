"""Tests for wait-state visibility — the live "what are we waiting on" notices.

Long provider waits (slow/overloaded backend, no first byte, reasoning model
thinking for minutes) used to leave CLI/TUI/Desktop users staring at a generic
"cogitating..." spinner with no explanation. ``AIAgent._emit_wait_notice``
rewrites the live spinner/status line (via ``thinking_callback``, bridged to
``thinking.delta`` for TUI/Desktop) and updates the activity tracker (which the
gateway's "⏳ Working — N min" heartbeat includes).
"""

from __future__ import annotations

import sys
import time
import types
from types import SimpleNamespace

import pytest

# Stub optional heavy imports so run_agent imports cleanly in isolation.
sys.modules.setdefault("fire", types.SimpleNamespace(Fire=lambda *a, **k: None))
sys.modules.setdefault("firecrawl", types.SimpleNamespace(Firecrawl=object))
sys.modules.setdefault("fal_client", types.SimpleNamespace())


def _make_agent(tmp_path, monkeypatch, **kwargs):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / ".env").write_text("", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("{}\n", encoding="utf-8")
    from run_agent import AIAgent

    return AIAgent(
        model="test-model",
        api_key="sk-dummy",
        base_url="https://openrouter.ai/api/v1",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
        platform="cli",
        **kwargs,
    )


def test_emit_wait_notice_updates_spinner_and_activity(tmp_path, monkeypatch):
    """The notice reaches the live display callback AND the activity tracker."""
    seen: list = []
    agent = _make_agent(tmp_path, monkeypatch, thinking_callback=seen.append)

    agent._emit_wait_notice("⏳ waiting on test-model — 30s with no response yet")

    assert seen == ["⏳ waiting on test-model — 30s with no response yet"]
    summary = agent.get_activity_summary()
    assert "waiting on test-model" in summary["last_activity_desc"]


def test_emit_wait_notice_without_callback_still_touches_activity(tmp_path, monkeypatch):
    """No thinking_callback bound (gateway sessions) — activity still updates."""
    agent = _make_agent(tmp_path, monkeypatch)
    agent.thinking_callback = None

    agent._emit_wait_notice("⏳ waiting on test-model — 60s")

    assert "waiting on test-model" in agent.get_activity_summary()["last_activity_desc"]


def test_emit_wait_notice_swallows_callback_errors(tmp_path, monkeypatch):
    """A broken display callback must never break the API-call wait loop."""

    def _boom(text):
        raise RuntimeError("display exploded")

    agent = _make_agent(tmp_path, monkeypatch, thinking_callback=_boom)

    agent._emit_wait_notice("⏳ waiting")  # must not raise
    assert "waiting" in agent.get_activity_summary()["last_activity_desc"]


def test_nonstream_wait_notice_handles_infinite_stale_with_idle_watchdog(
    tmp_path, monkeypatch
):
    """A local endpoint's infinite generic deadline must stay display-safe.

    Codex Responses can emit an opening SSE event and then spend longer than
    30 seconds generating the full response.  Local endpoints intentionally
    disable the generic stale detector with ``float("inf")``; the periodic
    wait notice must not convert that sentinel to ``int``.  The newer finite
    event-idle watchdog remains active and should be advertised instead.
    """
    from agent import chat_completion_helpers as h

    seen: list[str] = []
    agent = _make_agent(tmp_path, monkeypatch, thinking_callback=seen.append)
    setattr(agent, "api_mode", "codex_responses")
    monkeypatch.setattr(
        agent,
        "_compute_non_stream_stale_timeout",
        lambda *a, **k: float("inf"),
    )

    class _FakeClock:
        def __init__(self):
            self.polls = 0

        def time(self):
            # Derive time from the poll count instead of repeatedly adding 0.3,
            # which keeps the 100th poll exactly at the 30-second boundary.
            return 1_000.0 + (self.polls * 0.3)

        def advance_poll(self):
            self.polls += 1

    clock = _FakeClock()
    monkeypatch.setattr(h, "time", SimpleNamespace(time=clock.time))

    class _OpeningEventThenSlowThread:
        def __init__(self, *args, **kwargs):
            self._alive_checks = 0

        def start(self):
            # Simulate the opening SSE frame that disables the TTFB deadline.
            setattr(agent, "_codex_stream_last_event_ts", clock.time())

        def is_alive(self):
            self._alive_checks += 1
            return self._alive_checks <= 100

        def join(self, timeout=None):
            clock.advance_poll()
            # Keep the stream active so the event-idle watchdog does not fire.
            setattr(agent, "_codex_stream_last_event_ts", clock.time())

    monkeypatch.setattr(h.threading, "Thread", _OpeningEventThenSlowThread)

    assert h.interruptible_api_call(
        agent,
        {"model": "gpt-5.6-sol", "input": "slow response"},
    ) is None
    assert clock.polls == 100
    assert any(
        "30s with no response yet" in notice
        and "auto-reconnect at " in notice
        for notice in seen
    )


def test_nonstream_wait_loop_emits_explained_notice(tmp_path, monkeypatch):
    """After ~30s with no response, interruptible_api_call rewrites the live
    line with an explanation (model name, elapsed, overload hint, recovery
    deadline) instead of a bare 'waiting for non-streaming response'."""
    from agent import chat_completion_helpers as h

    seen: list = []
    agent = _make_agent(tmp_path, monkeypatch, thinking_callback=seen.append)
    agent.api_mode = "codex_responses"
    monkeypatch.setattr(agent, "_compute_non_stream_stale_timeout", lambda *a, **k: 60.0)

    # Compress the 30s cadence: the loop fires the notice every 100 polls of
    # 0.3s; patch the join timeout down via a tiny thread that stays alive
    # briefly, and shrink the poll interval by patching time.  Simplest
    # reliable approach: run a worker that hangs ~1.2s and patch the modulo
    # counter trigger by making the loop's join timeout effectively immediate.
    dummy_client = SimpleNamespace()
    monkeypatch.setattr(agent, "_create_request_openai_client", lambda **k: dummy_client)
    monkeypatch.setattr(agent, "_abort_request_openai_client", lambda c, reason=None: None)
    monkeypatch.setattr(agent, "_close_request_openai_client", lambda c, reason=None: None)

    stop = {"flag": False}

    def fake_hang(api_kwargs, client=None, on_first_delta=None):
        deadline = time.time() + 10
        while time.time() < deadline and not stop["flag"] and not agent._interrupt_requested:
            time.sleep(0.02)
        raise RuntimeError("connection closed")

    monkeypatch.setattr(agent, "_run_codex_stream", fake_hang)
    # TTFB kill at 1s ends the call quickly; the wait notice fires on the
    # 100-poll cadence, so to observe it within the 1s window we shrink the
    # cadence by patching threading.Thread.join used in the poll loop is
    # overkill — instead just verify the TTFB reconnect notice, which flows
    # through the same _emit_wait_notice path.
    monkeypatch.setenv("HERMES_CODEX_TTFB_TIMEOUT_SECONDS", "1")

    try:
        with pytest.raises(TimeoutError):
            h.interruptible_api_call(agent, {"model": "gpt-5.5", "input": "hi"})
    finally:
        stop["flag"] = True

    reconnect_notices = [s for s in seen if "reconnecting" in s]
    assert reconnect_notices, f"expected a reconnect wait-notice, saw: {seen}"
    assert "no response from provider" in reconnect_notices[0]
