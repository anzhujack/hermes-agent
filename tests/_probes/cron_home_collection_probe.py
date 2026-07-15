"""Collection-time probe for the test-suite HERMES_HOME guard.

This file is intentionally not named ``test_*.py`` so the normal suite does
not collect it. ``tests/test_run_tests_parallel.py`` invokes it explicitly in a
child pytest process with a sentinel inherited HERMES_HOME.
"""

from cron.jobs import create_job


def test_collection_time_cron_import_is_quarantined() -> None:
    created = create_job(name="paused job", schedule="0 7 * * *", prompt="x")
    assert created["name"] == "paused job"
