from __future__ import annotations

from dataclasses import dataclass
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

import classifier
from provider_registry import (
    ProviderConfigurationError,
    ProviderSettings,
    create_provider,
    provider_for_config,
    settings_from_config,
)


@dataclass
class FakeModelConfig:
    model_id: str
    provider: str
    provider_kwargs: dict


class FakeFactory:
    ModelConfig = FakeModelConfig

    def __init__(self):
        self.calls = []

    def create_model(self, config):
        self.calls.append(config)
        return object()


def _settings(provider: str, **kwargs):
    return ProviderSettings(provider=provider, model="configured-model", **kwargs)


def test_provider_selection_is_explicit_and_openrouter_uses_compatibility_provider():
    factory = FakeFactory()
    create_provider(
        _settings(
            "openrouter",
            endpoint="http://router.invalid/v1",
            api_key="router-secret",
        ),
        factory=factory,
    )

    selected = factory.calls[0]
    assert selected.provider == "openai"
    assert selected.model_id == "configured-model"
    assert selected.provider_kwargs == {
        "api_key": "router-secret",
        "base_url": "http://router.invalid/v1",
    }


def test_each_builtin_provider_receives_model_endpoint_and_options():
    for provider, expected_factory_provider in (
        ("openai", "openai"),
        ("gemini", "gemini"),
        ("ollama", "ollama"),
    ):
        factory = FakeFactory()
        create_provider(
            _settings(
                provider,
                endpoint=f"http://{provider}.invalid",
                api_key="secret" if provider != "ollama" else "",
                options={"temperature": 0.2},
            ),
            factory=factory,
        )
        selected = factory.calls[0]
        assert selected.provider == expected_factory_provider
        assert selected.model_id == "configured-model"
        assert selected.provider_kwargs["temperature"] == 0.2
        if provider == "gemini":
            assert selected.provider_kwargs["http_options"] == {
                "base_url": f"http://{provider}.invalid"
            }
        else:
            assert selected.provider_kwargs["base_url"] == f"http://{provider}.invalid"


def test_ollama_configuration_needs_no_remote_credential():
    factory = FakeFactory()
    create_provider(
        _settings("ollama", endpoint="http://127.0.0.1:11434"),
        factory=factory,
    )
    assert factory.calls[0].provider == "ollama"
    assert factory.calls[0].provider_kwargs["base_url"] == "http://127.0.0.1:11434"


def test_custom_provider_is_loaded_only_from_configured_path_and_gets_options():
    module = ModuleType("fake_provider_module")

    class FakeProvider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    module.FakeProvider = FakeProvider
    with patch.dict(sys.modules, {module.__name__: module}):
        provider = create_provider(
            _settings(
                "custom",
                custom_path="fake_provider_module:FakeProvider",
                options={"temperature": 0.4},
            )
        )

    assert isinstance(provider, FakeProvider)
    assert provider.kwargs == {
        "model_id": "configured-model",
        "temperature": 0.4,
    }


def test_config_environment_credential_and_provider_precedence_is_deterministic():
    config = SimpleNamespace(
        llm=SimpleNamespace(
            provider="OPENAI",
            model="model-from-file",
            endpoint="",
            options={},
            api_key_env="PENNY_TEST_PROVIDER_KEY",
            custom_path="",
        ),
        openai_api_key="file-key",
    )
    with patch.dict("os.environ", {"PENNY_TEST_PROVIDER_KEY": "env-key"}, clear=False):
        settings = settings_from_config(config)

    assert settings.provider == "openai"
    assert settings.model == "model-from-file"
    assert settings.api_key == "env-key"
    assert settings.endpoint == "https://api.openai.com/v1"


def test_unsupported_provider_fails_closed_without_factory_call():
    factory = FakeFactory()
    with pytest.raises(ProviderConfigurationError) as raised:
        create_provider(_settings("unexpected", api_key="secret"), factory=factory)
    assert raised.value.code == "unsupported_provider"
    assert factory.calls == []

def test_missing_configuration_fails_closed_without_provider_import():
    provider = provider_for_config(SimpleNamespace())

    assert provider.code == "configuration_missing"
    with pytest.raises(ProviderConfigurationError) as raised:
        provider.infer(["private prompt"])
    assert raised.value.code == "configuration_missing"


def test_provider_settings_repr_redacts_credentials_and_endpoint():
    settings = _settings(
        "openai",
        endpoint="https://user:password@example.invalid/v1",
        api_key="api-secret",
    )

    rendered = repr(settings)
    assert "password" not in rendered
    assert "api-secret" not in rendered


def test_missing_credentials_returns_non_networking_fallback():
    config = SimpleNamespace(
        llm=SimpleNamespace(
            provider="openai",
            model="gpt-test",
            endpoint="",
            options={},
            api_key_env="",
            custom_path="",
        ),
        openai_api_key="",
    )
    provider = provider_for_config(config)
    with patch.object(classifier.requests, "post") as post:
        result = classifier.classify(
            "private transcript",
            api_key="",
            model="unused",
            provider=provider,
        )
    post.assert_not_called()
    assert result["fallback"] is True
    assert result["items"][0]["category"] == "inbox"


def test_provider_failure_logs_no_secret_transcript_or_response():
    sentinel = "provider-response-secret-transcript"

    class BrokenProvider:
        def infer(self, prompts):
            raise RuntimeError(sentinel)

    with patch.object(classifier, "log") as log_mock:
        result = classifier.classify(
            "private transcript",
            api_key="api-secret",
            model="model",
            provider=BrokenProvider(),
        )

    assert result["fallback"] is True
    assert sentinel not in repr(log_mock.mock_calls)
    assert "private transcript" not in repr(log_mock.mock_calls)
    assert "api-secret" not in repr(log_mock.mock_calls)
