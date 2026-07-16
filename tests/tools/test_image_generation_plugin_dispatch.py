from __future__ import annotations

import json
import pytest

from agent import image_gen_registry
from agent.image_gen_provider import ImageGenProvider


@pytest.fixture(autouse=True)
def _reset_registry():
    image_gen_registry._reset_for_tests()
    yield
    image_gen_registry._reset_for_tests()


class _FakeCodexProvider(ImageGenProvider):
    def __init__(self, *, success=True, error_type="api_error", model="gpt-5.2-codex"):
        self.calls = []
        self._success = success
        self._error_type = error_type
        self._model = model

    @property
    def name(self) -> str:
        return "codex"

    def generate(self, prompt, aspect_ratio="landscape", **kwargs):
        self.calls.append({"prompt": prompt, "aspect_ratio": aspect_ratio, **kwargs})
        if not self._success:
            return {
                "success": False,
                "image": None,
                "error": "primary failed",
                "error_type": self._error_type,
                "model": self._model,
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "provider": "codex",
            }
        return {
            "success": True,
            "image": "/tmp/codex-test.png",
            "model": kwargs.get("model", self._model),
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "provider": "codex",
        }


class _FakeFallbackProvider(_FakeCodexProvider):
    @property
    def name(self) -> str:
        return "backup"

    def generate(self, prompt, aspect_ratio="landscape", **kwargs):
        self.calls.append({"prompt": prompt, "aspect_ratio": aspect_ratio, **kwargs})
        return {
            "success": True,
            "image": "/tmp/backup-test.png",
            "model": kwargs.get("model", "backup-default"),
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "provider": "backup",
        }


class TestPluginDispatch:
    def test_dispatch_routes_to_codex_provider(self, monkeypatch, tmp_path):
        from tools import image_generation_tool
        from agent import image_gen_registry as registry_module
        from hermes_cli import plugins as plugins_module

        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        (tmp_path / "config.yaml").write_text("image_gen:\n  provider: codex\n")
        image_gen_registry.register_provider(_FakeCodexProvider())

        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "codex")
        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda: None)
        monkeypatch.setattr(registry_module, "get_provider", lambda name: _FakeCodexProvider() if name == "codex" else None)

        dispatched = image_generation_tool._dispatch_to_plugin_provider("draw cat", "square")
        payload = json.loads(dispatched)

        assert payload["success"] is True
        assert payload["provider"] == "codex"
        assert payload["image"] == "/tmp/codex-test.png"
        assert payload["aspect_ratio"] == "square"

    def test_dispatch_reports_missing_registered_provider(self, monkeypatch, tmp_path):
        from tools import image_generation_tool
        from hermes_cli import plugins as plugins_module

        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        (tmp_path / "config.yaml").write_text("image_gen:\n  provider: missing-codex\n")

        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "missing-codex")
        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda: None)

        dispatched = image_generation_tool._dispatch_to_plugin_provider("draw cat", "landscape")
        payload = json.loads(dispatched)

        assert payload["success"] is False
        assert payload["error_type"] == "provider_not_registered"
        assert "image_gen.provider='missing-codex'" in payload["error"]

    def test_dispatch_force_refreshes_plugins_when_provider_initially_missing(self, monkeypatch, tmp_path):
        from tools import image_generation_tool
        from hermes_cli import plugins as plugins_module
        from agent import image_gen_registry as registry_module

        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        (tmp_path / "config.yaml").write_text("image_gen:\n  provider: codex\n")

        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "codex")

        calls = []
        provider_state = {"provider": None}

        def fake_ensure_plugins_discovered(force=False):
            calls.append(force)
            if force:
                provider_state["provider"] = _FakeCodexProvider()

        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", fake_ensure_plugins_discovered)
        monkeypatch.setattr(registry_module, "get_provider", lambda name: provider_state["provider"])

        dispatched = image_generation_tool._dispatch_to_plugin_provider("draw hammy", "portrait")
        payload = json.loads(dispatched)

        assert calls == [False, True]
        assert payload["success"] is True
        assert payload["provider"] == "codex"
        assert payload["aspect_ratio"] == "portrait"

    def test_dispatch_forwards_quality_resolution_and_size(self, monkeypatch, tmp_path):
        from tools import image_generation_tool
        from hermes_cli import plugins as plugins_module
        from agent import image_gen_registry as registry_module

        provider = _FakeCodexProvider()
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "codex")
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_model", lambda: "gpt-image-2-vip")
        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda force=False: None)
        monkeypatch.setattr(registry_module, "get_provider", lambda name: provider if name == "codex" else None)

        dispatched = image_generation_tool._dispatch_to_plugin_provider(
            "draw cat", "portrait", size="1024x1536", quality="high", resolution="2k"
        )
        payload = json.loads(dispatched)

        assert payload["success"] is True
        assert provider.calls[0]["model"] == "gpt-image-2-vip"
        assert provider.calls[0]["size"] == "1024x1536"
        assert provider.calls[0]["quality"] == "high"
        assert provider.calls[0]["resolution"] == "2k"

    def test_retryable_failure_uses_ordered_fallback_chain_models_and_options(self, monkeypatch, tmp_path):
        from tools import image_generation_tool
        from hermes_cli import plugins as plugins_module
        from agent import image_gen_registry as registry_module

        primary = _FakeCodexProvider(success=False, error_type="api_error")
        first_backup = _FakeCodexProvider(success=False, error_type="api_error")
        second_backup = _FakeFallbackProvider()
        monkeypatch.setenv("HERMES_HOME", str(tmp_path))
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: "codex")
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_model", lambda: "primary-model")
        monkeypatch.setattr(
            image_generation_tool,
            "_read_configured_image_fallback_providers",
            lambda: [
                {"provider": "first-backup", "model": "first-model"},
                {"provider": "backup", "model": "backup-model"},
            ],
        )
        monkeypatch.setattr(plugins_module, "_ensure_plugins_discovered", lambda force=False: None)
        monkeypatch.setattr(
            registry_module,
            "get_provider",
            lambda name: {
                "codex": primary,
                "first-backup": first_backup,
                "backup": second_backup,
            }.get(name),
        )

        dispatched = image_generation_tool._dispatch_to_plugin_provider(
            "draw cat", "square", size="2048x2048", quality="high", resolution="4k"
        )
        payload = json.loads(dispatched)

        assert payload["success"] is True
        assert payload["provider"] == "backup"
        assert payload["fallback"] is True
        assert payload["fallback_from_provider"] == "codex"
        assert first_backup.calls[0]["model"] == "first-model"
        assert second_backup.calls[0]["model"] == "backup-model"
        assert second_backup.calls[0]["size"] == "2048x2048"
        assert second_backup.calls[0]["quality"] == "high"
        assert second_backup.calls[0]["resolution"] == "4k"

    def test_unset_provider_keeps_legacy_fal_path(self, monkeypatch):
        """An unrelated API key must not opt the user into paid image generation."""
        from tools import image_generation_tool

        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: None)
        assert image_generation_tool._dispatch_to_plugin_provider("draw cat", "landscape") is None

    def test_deepinfra_key_alone_does_not_select_image_backend(self, monkeypatch):
        """DeepInfra chat credentials do not imply consent to image billing."""
        from tools import image_generation_tool

        monkeypatch.setenv("DEEPINFRA_API_KEY", "«redacted:sk-…»")
        monkeypatch.delenv("FAL_KEY", raising=False)
        monkeypatch.setattr(image_generation_tool, "_read_configured_image_provider", lambda: None)
        assert image_generation_tool._dispatch_to_plugin_provider("a cat", "square") is None

    def test_requirements_ignore_unselected_paid_plugin(self, monkeypatch):
        from tools import image_generation_tool

        monkeypatch.setattr(image_generation_tool, "check_fal_api_key", lambda: False)
        monkeypatch.setattr(
            image_generation_tool, "_read_configured_image_provider", lambda: None
        )
        assert image_generation_tool.check_image_generation_requirements() is False
