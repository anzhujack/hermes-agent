"""Collection-time probe for inherited gateway environment isolation."""

import os

_FORBIDDEN = (
    "HERMES_REAL_HOME",
    "HERMES_SESSION_PLATFORM",
    "HERMES_SESSION_PROFILE",
    "DISCORD_ALLOWED_CHANNELS",
    "WEIXIN_HOME_CHANNEL",
    "OPENAI_API_KEY",
)

for _name in _FORBIDDEN:
    assert _name not in os.environ, f"live runtime variable leaked into collection: {_name}"


def test_collection_environment_is_quarantined():
    assert os.environ.get("HERMES_HOME")
    assert os.environ.get("HERMES_TEST_IMAGE") == "prebuilt:test"
