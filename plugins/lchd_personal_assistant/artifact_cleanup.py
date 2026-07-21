"""Bounded 24-hour soft quarantine for ephemeral Hermes tool artifacts.

Only three flat, regenerable cache roots are eligible:
- ``$TMPDIR/hermes-results`` (persisted oversized tool results)
- ``$HERMES_HOME/cache/web`` (full web_extract copies)
- ``$HERMES_HOME/cache/screenshots`` (browser screenshots)

The first observation never deletes a file.  It records a deadline in an
atomic manifest so a later sweep can remove it after the configured grace
period.  User documents and generated media caches are intentionally outside
this module's allowlist.
"""

from __future__ import annotations

import json
import logging
import os
import stat as stat_module
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

_STATE_VERSION = 1
_MAX_DELETE_FILES_HARD = 100
_MAX_DELETE_BYTES_HARD = 256 * 1024 * 1024
_MAX_SINGLE_FILE_BYTES_HARD = 500 * 1024 * 1024
_worker_lock = threading.Lock()
logger = logging.getLogger(__name__)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _as_utc(value).isoformat()


def _state_paths(hermes_home: Path) -> tuple[Path, Path]:
    state_dir = hermes_home / "artifact-cleanup"
    return state_dir / "quarantine.json", state_dir / "cleanup.log"


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": _STATE_VERSION, "entries": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"version": _STATE_VERSION, "entries": []}
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return {"version": _STATE_VERSION, "entries": []}
    return {"version": _STATE_VERSION, "entries": data["entries"]}


def _save_manifest(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def _audit(path: Path, event: str, artifact: Path, *, size: int = 0, detail: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    suffix = f" detail={detail}" if detail else ""
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{timestamp} {event} path={artifact} bytes={size}{suffix}\n")
    os.chmod(path, 0o600)


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return _as_utc(datetime.fromisoformat(value))
    except ValueError:
        return None


def _direct_root(path: Path, roots: tuple[tuple[str, Path], ...]) -> Path | None:
    if not path.is_absolute():
        return None
    for _, root in roots:
        if path.parent == root and path != root:
            return root
    return None


def _eligible_roots(hermes_home: Path, tmp_root: Path) -> tuple[tuple[str, Path], ...]:
    return (
        ("tool-result", tmp_root / "hermes-results"),
        ("web-cache", hermes_home / "cache" / "web"),
        ("browser-screenshot", hermes_home / "cache" / "screenshots"),
    )


def sweep_once(
    *,
    hermes_home: Path | str | None = None,
    tmp_root: Path | str | None = None,
    now: datetime | None = None,
    ttl_hours: int = 24,
    max_delete_files: int = 100,
    max_delete_bytes: int = 256 * 1024 * 1024,
    max_single_file_bytes: int = 500 * 1024 * 1024,
) -> dict[str, Any]:
    """Register eligible artifacts and remove expired entries on later sweeps."""
    home = Path(hermes_home or os.environ.get("HERMES_HOME") or Path.home() / ".hermes").expanduser().resolve()
    temp = Path(tmp_root or tempfile.gettempdir()).expanduser().resolve()
    current = _as_utc(now or datetime.now(timezone.utc))
    deadline = current + timedelta(hours=max(1, int(ttl_hours)))
    manifest_path, audit_path = _state_paths(home)
    manifest = _load_manifest(manifest_path)
    entries_by_path = {
        str(item.get("path")): item
        for item in manifest["entries"]
        if isinstance(item, dict) and item.get("path")
    }
    tracked = 0

    roots = _eligible_roots(home, temp)
    for kind, root in roots:
        try:
            if root.is_symlink() or not root.is_dir() or root.resolve(strict=True) != root:
                continue
        except OSError:
            continue
        try:
            children = root.iterdir()
        except OSError:
            continue
        for child in children:
            try:
                if child.is_symlink() or not child.is_file():
                    continue
                resolved = child.resolve(strict=True)
                resolved.relative_to(root)
                stat = resolved.stat()
            except (OSError, ValueError):
                continue
            key = str(resolved)
            existing = entries_by_path.get(key)
            if existing is not None:
                if (
                    existing.get("mtime_ns") != stat.st_mtime_ns
                    or existing.get("size") != stat.st_size
                    or existing.get("device") != stat.st_dev
                    or existing.get("inode") != stat.st_ino
                ):
                    existing["mtime_ns"] = stat.st_mtime_ns
                    existing["size"] = stat.st_size
                    existing["device"] = stat.st_dev
                    existing["inode"] = stat.st_ino
                    existing["kind"] = kind
                    existing["delete_after"] = _iso(deadline)
                continue
            entries_by_path[key] = {
                "path": key,
                "kind": kind,
                "first_seen": _iso(current),
                "delete_after": _iso(deadline),
                "mtime_ns": stat.st_mtime_ns,
                "size": stat.st_size,
                "device": stat.st_dev,
                "inode": stat.st_ino,
            }
            tracked += 1

    deleted = 0
    freed = 0
    skipped_large = 0
    errors: list[str] = []
    retained: list[dict[str, Any]] = []
    for item in sorted(entries_by_path.values(), key=lambda value: value["path"]):
        candidate = Path(str(item["path"]))
        root = _direct_root(candidate, roots)
        if root is None:
            _audit(audit_path, "REJECTED_OUTSIDE_ALLOWLIST", candidate)
            continue

        root_fd: int | None = None
        try:
            if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
                raise OSError("platform lacks safe directory-handle deletion")
            root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            if not stat_module.S_ISDIR(os.fstat(root_fd).st_mode):
                raise OSError("allowlisted root is not a directory")
            file_stat = os.stat(candidate.name, dir_fd=root_fd, follow_symlinks=False)
            if stat_module.S_ISLNK(file_stat.st_mode):
                _audit(audit_path, "REJECTED_SYMLINK", candidate)
                os.close(root_fd)
                root_fd = None
                continue
            if not stat_module.S_ISREG(file_stat.st_mode):
                _audit(audit_path, "REJECTED_NON_REGULAR", candidate)
                os.close(root_fd)
                root_fd = None
                continue
        except FileNotFoundError:
            if root_fd is not None:
                os.close(root_fd)
                root_fd = None
            continue
        except OSError as exc:
            if root_fd is not None:
                os.close(root_fd)
                root_fd = None
            errors.append(f"{candidate}: {exc}")
            retained.append(item)
            continue
        try:
            expires = _parse_iso(item.get("delete_after"))
            if expires is None or current < expires:
                retained.append(item)
                continue
            if (
                file_stat.st_mtime_ns != item.get("mtime_ns")
                or file_stat.st_size != item.get("size")
                or file_stat.st_dev != item.get("device")
                or file_stat.st_ino != item.get("inode")
            ):
                retained.append(item)
                continue
            if file_stat.st_size > max_single_file_bytes:
                skipped_large += 1
                retained.append(item)
                _audit(audit_path, "SKIPPED_LARGE", candidate, size=file_stat.st_size)
                continue
            if deleted >= max_delete_files or freed + file_stat.st_size > max_delete_bytes:
                retained.append(item)
                continue

            try:
                os.unlink(candidate.name, dir_fd=root_fd)
            except OSError as exc:
                errors.append(f"{candidate}: {exc}")
                retained.append(item)
                _audit(audit_path, "DELETE_ERROR", candidate, size=file_stat.st_size, detail=str(exc))
                continue
            deleted += 1
            freed += file_stat.st_size
            _audit(
                audit_path,
                "DELETED",
                candidate,
                size=file_stat.st_size,
                detail=str(item.get("kind", "unknown")),
            )
        finally:
            if root_fd is not None:
                os.close(root_fd)

    manifest["entries"] = retained
    _save_manifest(manifest_path, manifest)
    return {
        "tracked": tracked,
        "deleted": deleted,
        "freed": freed,
        "skipped_large": skipped_large,
        "errors": errors,
    }


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, parsed))


def _load_settings() -> dict[str, Any]:
    home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes").expanduser().resolve()
    block: dict[str, Any] = {}
    try:
        config = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8")) or {}
        personal = config.get("lchd_personal") if isinstance(config, dict) else {}
        candidate = personal.get("artifact_cleanup") if isinstance(personal, dict) else {}
        if isinstance(candidate, dict):
            block = candidate
    except (OSError, yaml.YAMLError):
        pass
    return {
        "enabled": block.get("enabled") is True,
        "hermes_home": home,
        "tmp_root": Path(tempfile.gettempdir()).resolve(),
        "ttl_hours": _bounded_int(block.get("ttl_hours"), 24, 24, 24 * 30),
        "max_delete_files": _bounded_int(
            block.get("max_delete_files_per_turn"), 50, 1, _MAX_DELETE_FILES_HARD
        ),
        "max_delete_bytes": _bounded_int(
            block.get("max_delete_bytes_per_turn"),
            128 * 1024 * 1024,
            1024,
            _MAX_DELETE_BYTES_HARD,
        ),
        "max_single_file_bytes": _bounded_int(
            block.get("max_single_file_bytes"),
            _MAX_SINGLE_FILE_BYTES_HARD,
            1024,
            _MAX_SINGLE_FILE_BYTES_HARD,
        ),
    }


def _background_sweep(settings: dict[str, Any]) -> None:
    try:
        summary = sweep_once(
            hermes_home=settings["hermes_home"],
            tmp_root=settings["tmp_root"],
            ttl_hours=settings["ttl_hours"],
            max_delete_files=settings["max_delete_files"],
            max_delete_bytes=settings["max_delete_bytes"],
            max_single_file_bytes=settings["max_single_file_bytes"],
        )
        _, audit_path = _state_paths(settings["hermes_home"])
        _audit(
            audit_path,
            "SWEEP_SUMMARY",
            settings["hermes_home"] / "artifact-cleanup",
            size=summary["freed"],
            detail=(
                f"tracked={summary['tracked']} deleted={summary['deleted']} "
                f"skipped_large={summary['skipped_large']} errors={len(summary['errors'])}"
            ),
        )
    except Exception:
        logger.warning("artifact cleanup sweep failed", exc_info=True)
    finally:
        _worker_lock.release()


def on_session_end(**_: Any) -> None:
    """Start one bounded cleanup worker after each completed agent turn."""
    settings = _load_settings()
    if not settings["enabled"] or not _worker_lock.acquire(blocking=False):
        return
    worker = threading.Thread(
        target=_background_sweep,
        args=(settings,),
        name="lchd-artifact-cleanup",
        daemon=True,
    )
    try:
        worker.start()
    except Exception:
        _worker_lock.release()
        logger.warning("artifact cleanup worker did not start", exc_info=True)
