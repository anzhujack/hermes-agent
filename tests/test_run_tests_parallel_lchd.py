"""Lchd regression tests for Hermes test-runner environment isolation.

Kept in a separate file so upstream additions to ``test_run_tests_parallel.py``
do not repeatedly conflict with the personal production-safety regressions.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_shell_runner_preserves_prebuilt_docker_image_env(tmp_path: Path) -> None:
    """The hermetic wrapper must not discard the Docker CI image override."""
    repo_root = Path(__file__).resolve().parent.parent
    wrapper = repo_root / "scripts" / "run_tests.sh"
    probe = tmp_path / "test_docker_image_env.py"
    probe.write_text(
        "import os\n\n"
        "def test_docker_image_env():\n"
        "    assert os.environ.get('HERMES_TEST_IMAGE') == 'prebuilt:test'\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["HERMES_TEST_IMAGE"] = "prebuilt:test"
    proc = subprocess.run(
        [str(wrapper), str(probe), "-j", "1", "--file-timeout", "30", "-q"],
        cwd=repo_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout


def test_runner_quarantines_inherited_hermes_home(tmp_path: Path) -> None:
    """A test file must never inherit and mutate the caller's Hermes home.

    The probe imports ``cron.jobs`` at collection time, before pytest fixtures
    can run. This is the exact leak shape that previously wrote synthetic
    ``claim job`` / ``w`` records into a developer's live cron registry.
    """
    repo_root = Path(__file__).resolve().parent.parent
    runner = repo_root / "scripts" / "run_tests_parallel.py"

    inherited_home = tmp_path / "inherited-hermes-home"
    inherited_cron = inherited_home / "cron"
    inherited_cron.mkdir(parents=True)
    inherited_jobs = inherited_cron / "jobs.json"
    inherited_jobs.write_text('{"jobs": []}\n', encoding="utf-8")
    before = inherited_jobs.read_bytes()

    probe_dir = tmp_path / "cron-home-probe"
    probe_dir.mkdir()
    (probe_dir / "test_cron_home_probe.py").write_text(
        "from cron.jobs import create_job\n\n"
        "def test_create_job_is_quarantined():\n"
        "    created = create_job(name='claim job', schedule='0 7 * * *', prompt='x')\n"
        "    assert created['name'] == 'claim job'\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["HERMES_HOME"] = str(inherited_home)
    proc = subprocess.run(
        [
            sys.executable,
            str(runner),
            "--paths",
            str(probe_dir),
            "-j",
            "1",
            "--file-timeout",
            "30",
            "-q",
        ],
        cwd=repo_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
    )

    assert proc.returncode == 0, proc.stdout
    assert inherited_jobs.read_bytes() == before, (
        "run_tests_parallel.py let a collection-time cron.jobs import mutate "
        f"the inherited HERMES_HOME; runner output:\n{proc.stdout}"
    )


def test_direct_pytest_quarantines_home_before_collection(tmp_path: Path) -> None:
    """Root conftest must isolate HERMES_HOME before test-module imports."""
    repo_root = Path(__file__).resolve().parent.parent
    probe = repo_root / "tests" / "_probes" / "cron_home_collection_probe.py"
    assert probe.exists()

    inherited_home = tmp_path / "direct-pytest-inherited-home"
    inherited_cron = inherited_home / "cron"
    inherited_cron.mkdir(parents=True)
    inherited_jobs = inherited_cron / "jobs.json"
    inherited_jobs.write_text('{"jobs": []}\n', encoding="utf-8")
    before = inherited_jobs.read_bytes()

    env = os.environ.copy()
    env["HERMES_HOME"] = str(inherited_home)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(probe), "-q"],
        cwd=repo_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
    )

    assert proc.returncode == 0, proc.stdout
    assert inherited_jobs.read_bytes() == before, (
        "tests/conftest.py isolated HERMES_HOME only after collection; "
        f"child pytest output:\n{proc.stdout}"
    )


def _seed_live_gateway_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "HERMES_REAL_HOME": "/sensitive-real-home",
            "HERMES_SESSION_PLATFORM": "discord",
            "HERMES_SESSION_PROFILE": "live-profile",
            "DISCORD_ALLOWED_CHANNELS": "live-channel",
            "WEIXIN_HOME_CHANNEL": "live-home",
            "OPENAI_API_KEY": "must-not-reach-pytest",
            # Explicit test controls are intentionally preserved.
            "HERMES_TEST_IMAGE": "prebuilt:test",
        }
    )
    return env


def test_runner_scrubs_gateway_context_before_collection() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    runner = repo_root / "scripts" / "run_tests_parallel.py"
    probe = repo_root / "tests" / "_probes" / "env_collection_probe.py"

    proc = subprocess.run(
        [
            sys.executable,
            str(runner),
            "--paths",
            str(probe),
            "-j",
            "1",
            "--file-timeout",
            "30",
            "-q",
        ],
        cwd=repo_root,
        env=_seed_live_gateway_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
    )

    assert proc.returncode == 0, proc.stdout


def test_direct_pytest_scrubs_gateway_context_before_collection() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    probe = repo_root / "tests" / "_probes" / "env_collection_probe.py"

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(probe), "-q"],
        cwd=repo_root,
        env=_seed_live_gateway_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
    )

    assert proc.returncode == 0, proc.stdout
