"""Safety tests for Lchd's 24-hour tool-artifact soft quarantine."""

from __future__ import annotations

import importlib.util
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "plugins" / "lchd_personal_assistant" / "artifact_cleanup.py"
    spec = importlib.util.spec_from_file_location("lchd_artifact_cleanup_under_test", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_first_sweep_soft_quarantines_only_allowlisted_files(tmp_path):
    cleanup = _load_module()
    home = tmp_path / ".hermes"
    tmp_root = tmp_path / "tmp"
    tool_result = tmp_root / "hermes-results" / "tool.txt"
    web_cache = home / "cache" / "web" / "page.md"
    screenshot = home / "cache" / "screenshots" / "shot.png"
    outside = tmp_path / "user-document.txt"
    for path in (tool_result, web_cache, screenshot, outside):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")

    result = cleanup.sweep_once(
        hermes_home=home,
        tmp_root=tmp_root,
        now=datetime(2026, 7, 21, 8, 0, tzinfo=timezone.utc),
        ttl_hours=24,
    )

    assert result == {
        "tracked": 3,
        "deleted": 0,
        "freed": 0,
        "skipped_large": 0,
        "errors": [],
    }
    assert all(path.exists() for path in (tool_result, web_cache, screenshot, outside))
    manifest = json.loads((home / "artifact-cleanup" / "quarantine.json").read_text(encoding="utf-8"))
    assert {item["path"] for item in manifest["entries"]} == {
        str(tool_result.resolve()),
        str(web_cache.resolve()),
        str(screenshot.resolve()),
    }


def test_second_sweep_deletes_expired_allowlisted_files_and_audits(tmp_path):
    cleanup = _load_module()
    home = tmp_path / ".hermes"
    tmp_root = tmp_path / "tmp"
    candidates = (
        tmp_root / "hermes-results" / "tool.txt",
        home / "cache" / "web" / "page.md",
        home / "cache" / "screenshots" / "shot.png",
    )
    outside = tmp_path / "keep.txt"
    for path in (*candidates, outside):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("payload", encoding="utf-8")

    start = datetime(2026, 7, 21, 8, 0, tzinfo=timezone.utc)
    cleanup.sweep_once(hermes_home=home, tmp_root=tmp_root, now=start, ttl_hours=24)
    result = cleanup.sweep_once(
        hermes_home=home,
        tmp_root=tmp_root,
        now=datetime(2026, 7, 22, 8, 0, 1, tzinfo=timezone.utc),
        ttl_hours=24,
    )

    assert result == {
        "tracked": 0,
        "deleted": 3,
        "freed": 21,
        "skipped_large": 0,
        "errors": [],
    }
    assert not any(path.exists() for path in candidates)
    assert outside.exists()
    manifest = json.loads((home / "artifact-cleanup" / "quarantine.json").read_text(encoding="utf-8"))
    assert manifest["entries"] == []
    audit = (home / "artifact-cleanup" / "cleanup.log").read_text(encoding="utf-8")
    assert audit.count("DELETED") == 3
    assert str(outside) not in audit


def test_modified_artifact_gets_a_fresh_24_hour_grace_period(tmp_path):
    cleanup = _load_module()
    home = tmp_path / ".hermes"
    tmp_root = tmp_path / "tmp"
    artifact = tmp_root / "hermes-results" / "active.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("first", encoding="utf-8")
    os.utime(artifact, ns=(1_000_000_000, 1_000_000_000))

    start = datetime(2026, 7, 21, 8, 0, tzinfo=timezone.utc)
    cleanup.sweep_once(hermes_home=home, tmp_root=tmp_root, now=start, ttl_hours=24)
    artifact.write_text("still in use", encoding="utf-8")
    os.utime(artifact, ns=(2_000_000_000, 2_000_000_000))

    refreshed = cleanup.sweep_once(
        hermes_home=home,
        tmp_root=tmp_root,
        now=datetime(2026, 7, 22, 8, 0, 1, tzinfo=timezone.utc),
        ttl_hours=24,
    )
    assert refreshed["deleted"] == 0
    assert artifact.exists()

    manifest = json.loads((home / "artifact-cleanup" / "quarantine.json").read_text(encoding="utf-8"))
    assert manifest["entries"][0]["delete_after"] == "2026-07-23T08:00:01+00:00"
    assert manifest["entries"][0]["mtime_ns"] == 2_000_000_000

    expired = cleanup.sweep_once(
        hermes_home=home,
        tmp_root=tmp_root,
        now=datetime(2026, 7, 23, 8, 0, 2, tzinfo=timezone.utc),
        ttl_hours=24,
    )
    assert expired["deleted"] == 1
    assert not artifact.exists()


def test_allowlisted_root_symlink_cannot_escape_to_user_files(tmp_path):
    cleanup = _load_module()
    home = tmp_path / ".hermes"
    outside_dir = tmp_path / "documents"
    outside_file = outside_dir / "important.md"
    outside_dir.mkdir()
    outside_file.write_text("keep", encoding="utf-8")
    (home / "cache").mkdir(parents=True)
    (home / "cache" / "web").symlink_to(outside_dir, target_is_directory=True)

    result = cleanup.sweep_once(
        hermes_home=home,
        tmp_root=tmp_path / "tmp",
        now=datetime(2026, 7, 21, 8, 0, tzinfo=timezone.utc),
    )

    assert result["tracked"] == 0
    assert outside_file.exists()
    manifest = json.loads((home / "artifact-cleanup" / "quarantine.json").read_text(encoding="utf-8"))
    assert manifest["entries"] == []


def test_session_hook_is_disabled_by_default_and_audits_enabled_sweeps(tmp_path, monkeypatch):
    cleanup = _load_module()
    home = tmp_path / ".hermes"
    tmp_root = tmp_path / "tmp"
    web_cache = home / "cache" / "web" / "page.md"
    web_cache.parent.mkdir(parents=True)
    web_cache.write_text("cached", encoding="utf-8")
    home.joinpath("config.yaml").write_text("lchd_personal: {}\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(cleanup.tempfile, "gettempdir", lambda: str(tmp_root))

    cleanup.on_session_end(session_id="disabled")
    assert not (home / "artifact-cleanup").exists()

    home.joinpath("config.yaml").write_text(
        yaml.safe_dump(
            {
                "lchd_personal": {
                    "artifact_cleanup": {
                        "enabled": True,
                        "ttl_hours": 24,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    cleanup.on_session_end(session_id="enabled")
    audit_path = home / "artifact-cleanup" / "cleanup.log"
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not audit_path.exists():
        time.sleep(0.01)

    assert audit_path.exists()
    audit = audit_path.read_text(encoding="utf-8")
    assert "SWEEP_SUMMARY" in audit
    assert "tracked=1" in audit
    assert "deleted=0" in audit
    assert web_cache.exists()


def test_size_change_refreshes_grace_even_when_mtime_is_preserved(tmp_path):
    cleanup = _load_module()
    home = tmp_path / ".hermes"
    tmp_root = tmp_path / "tmp"
    artifact = tmp_root / "hermes-results" / "preserved-mtime.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("one", encoding="utf-8")
    os.utime(artifact, ns=(3_000_000_000, 3_000_000_000))
    start = datetime(2026, 7, 21, 8, 0, tzinfo=timezone.utc)
    cleanup.sweep_once(hermes_home=home, tmp_root=tmp_root, now=start)

    artifact.write_text("substantially longer", encoding="utf-8")
    os.utime(artifact, ns=(3_000_000_000, 3_000_000_000))
    result = cleanup.sweep_once(
        hermes_home=home,
        tmp_root=tmp_root,
        now=datetime(2026, 7, 22, 8, 0, 1, tzinfo=timezone.utc),
    )

    assert result["deleted"] == 0
    assert artifact.exists()
    manifest = json.loads((home / "artifact-cleanup" / "quarantine.json").read_text(encoding="utf-8"))
    assert manifest["entries"][0]["size"] == len("substantially longer")
    assert manifest["entries"][0]["delete_after"] == "2026-07-23T08:00:01+00:00"


def test_delete_caps_keep_large_files_and_remove_only_bounded_small_files(tmp_path):
    cleanup = _load_module()
    home = tmp_path / ".hermes"
    tmp_root = tmp_path / "tmp"
    root = tmp_root / "hermes-results"
    root.mkdir(parents=True)
    large = root / "large.bin"
    small = root / "small.txt"
    large.write_bytes(b"12345678")
    small.write_bytes(b"1234")
    start = datetime(2026, 7, 21, 8, 0, tzinfo=timezone.utc)
    cleanup.sweep_once(hermes_home=home, tmp_root=tmp_root, now=start)

    result = cleanup.sweep_once(
        hermes_home=home,
        tmp_root=tmp_root,
        now=datetime(2026, 7, 22, 8, 0, 1, tzinfo=timezone.utc),
        max_single_file_bytes=6,
        max_delete_files=1,
        max_delete_bytes=4,
    )

    assert result["deleted"] == 1
    assert result["freed"] == 4
    assert result["skipped_large"] == 1
    assert large.exists()
    assert not small.exists()
    audit = (home / "artifact-cleanup" / "cleanup.log").read_text(encoding="utf-8")
    assert "SKIPPED_LARGE" in audit


def test_delete_uses_directory_handle_not_a_re_resolved_full_path(tmp_path, monkeypatch):
    cleanup = _load_module()
    home = tmp_path / ".hermes"
    tmp_root = tmp_path / "tmp"
    root = tmp_root / "hermes-results"
    outside = tmp_path / "documents"
    root.mkdir(parents=True)
    outside.mkdir()
    artifact = root / "victim.txt"
    outside_file = outside / "victim.txt"
    artifact.write_text("same", encoding="utf-8")
    outside_file.write_text("same", encoding="utf-8")
    fixed_ns = 4_000_000_000
    os.utime(artifact, ns=(fixed_ns, fixed_ns))
    os.utime(outside_file, ns=(fixed_ns, fixed_ns))
    start = datetime(2026, 7, 21, 8, 0, tzinfo=timezone.utc)
    cleanup.sweep_once(hermes_home=home, tmp_root=tmp_root, now=start)

    original_unlink = Path.unlink

    def swap_root_then_unlink(path, *args, **kwargs):
        if path == artifact:
            root.rename(tmp_root / "hermes-results-original")
            root.symlink_to(outside, target_is_directory=True)
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", swap_root_then_unlink)
    cleanup.sweep_once(
        hermes_home=home,
        tmp_root=tmp_root,
        now=datetime(2026, 7, 22, 8, 0, 1, tzinfo=timezone.utc),
    )

    assert outside_file.exists(), "root replacement must never redirect deletion outside the cache"
    assert not artifact.exists()
