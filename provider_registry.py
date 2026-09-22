"""Explicit, fail-closed provider construction for Penny's classifier."""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import os
from types import ModuleType
from typing import Any, Mapping, Protocol, Sequence


SUPPORTED_PROVIDERS = frozenset({"openrouter", "openai", "gemini", "ollama", "custom"})

_DEFAULT_ENDPOINTS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "ollama": "http://127.0.0.1:11434",
}
_DEFAULT_CREDENTIAL_ENV = {
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


class LanguageModelProvider(Protocol):
    """Small interface consumed by the classifier."""

    def infer(self, batch_prompts: Sequence[str], **kwargs: Any) -> Any:
        ...


class ProviderConfigurationError(RuntimeError):
    """A bounded provider setup failure safe to expose to application code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ProviderSettings:
    """Resolved provider settings with credentials kept out of repr/logs."""

    provider: str
    model: str
    endpoint: str = field(default="", repr=False)
    api_key: str = field(default="", repr=False)
    options: Mapping[str, Any] = field(default_factory=dict, repr=False)
    custom_path: str = ""


class FailClosedProvider:
    """Provider used when construction failed; it cannot make network calls."""

    def __init__(self, code: str):
        self.code = code

    def infer(self, batch_prompts: Sequence[str], **kwargs: Any) -> Any:
        raise ProviderConfigurationError(self.code)


def _text_setting(value: Any) -> str:
    """Normalize optional config values without turning ``None`` into text."""
    return "" if value is None else str(value).strip()


def settings_from_config(config: Any) -> ProviderSettings:
    """Resolve the configured provider and its dedicated runtime credential."""

    llm = getattr(config, "llm", None)
    if llm is None:
        raise ProviderConfigurationError("configuration_missing")

    provider = _text_setting(getattr(llm, "provider", "")).lower()
    model = _text_setting(getattr(llm, "model", ""))
    endpoint = _text_setting(
        getattr(llm, "endpoint", None) or getattr(llm, "base_url", "")
    )
    options = getattr(llm, "options", {})
    if not isinstance(options, Mapping):
        raise ProviderConfigurationError("invalid_options")
    try:
        resolved_options = dict(options)
    except Exception as exc:
        raise ProviderConfigurationError("invalid_options") from exc

    api_key_env = _text_setting(getattr(llm, "api_key_env", ""))
    if api_key_env:
        api_key = os.environ.get(api_key_env, "")
    else:
        configured_key = getattr(config, f"{provider}_api_key", "")
        api_key = str(configured_key or "")
        if not api_key and provider in _DEFAULT_CREDENTIAL_ENV:
            api_key = os.environ.get(_DEFAULT_CREDENTIAL_ENV[provider], "")

    if not endpoint:
        endpoint = _DEFAULT_ENDPOINTS.get(provider, "")

    return ProviderSettings(
        provider=provider,
        model=model,
        endpoint=endpoint,
        api_key=api_key,
        options=resolved_options,
        custom_path=_text_setting(
            getattr(
                llm,
                "custom_path",
                getattr(llm, "custom_provider_path", ""),
            )
        ),
    )


def _provider_kwargs(settings: ProviderSettings) -> dict[str, Any]:
    kwargs = dict(settings.options)
    if settings.api_key:
        kwargs["api_key"] = settings.api_key

    if settings.provider.strip().lower() == "gemini":
        if settings.endpoint and "http_options" not in kwargs:
            kwargs["http_options"] = {"base_url": settings.endpoint}
    elif settings.endpoint:
        kwargs["base_url"] = settings.endpoint
    return kwargs


def _langextract_factory() -> ModuleType:
    try:
        return importlib.import_module("langextract.factory")
    except Exception as exc:
        raise ProviderConfigurationError("provider_unavailable") from exc


def _load_custom_provider(path: str) -> type[LanguageModelProvider]:
    if not path:
        raise ProviderConfigurationError("custom_path_missing")
    if ":" in path:
        module_name, attribute = path.split(":", 1)
    else:
        module_name, separator, attribute = path.rpartition(".")
        if not separator:
            raise ProviderConfigurationError("custom_path_invalid")
    if not module_name or not attribute:
        raise ProviderConfigurationError("custom_path_invalid")
    try:
        target = getattr(importlib.import_module(module_name), attribute)
    except Exception as exc:
        raise ProviderConfigurationError("custom_provider_unavailable") from exc
    if not callable(target):
        raise ProviderConfigurationError("custom_provider_invalid")
    return target


def create_provider(
    settings: ProviderSettings,
    *,
    factory: Any | None = None,
) -> LanguageModelProvider:
    """Construct exactly the provider named by ``settings``.

    ``factory`` is injectable so selection tests never import a provider SDK or
    make a network request.
    """

    provider = settings.provider.strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise ProviderConfigurationError("unsupported_provider")
    if not settings.model:
        raise ProviderConfigurationError("model_missing")
    if provider in {"openrouter", "openai", "gemini"} and not settings.api_key:
        raise ProviderConfigurationError("credentials_missing")

    try:
        kwargs = _provider_kwargs(settings)
    except Exception as exc:
        raise ProviderConfigurationError("invalid_options") from exc
    if provider == "custom":
        target = _load_custom_provider(settings.custom_path)
        custom_kwargs = dict(kwargs)
        custom_kwargs["model_id"] = settings.model
        try:
            return target(**custom_kwargs)
        except Exception as exc:
            raise ProviderConfigurationError("provider_initialization_failed") from exc

    factory = factory if factory is not None else _langextract_factory()
    factory_provider = "openai" if provider in {"openrouter", "openai"} else provider
    try:
        model_config = factory.ModelConfig(
            model_id=settings.model,
            provider=factory_provider,
            provider_kwargs=kwargs,
        )
        return factory.create_model(model_config)
    except ProviderConfigurationError:
        raise
    except Exception as exc:
        raise ProviderConfigurationError("provider_initialization_failed") from exc


def provider_for_config(config: Any) -> LanguageModelProvider:
    """Return a configured provider or a provider that always fails closed."""

    try:
        return create_provider(settings_from_config(config))
    except ProviderConfigurationError as exc:
        return FailClosedProvider(exc.code)
    except Exception:
        return FailClosedProvider("provider_configuration_failed")
