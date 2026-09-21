"""Compatibility facade. Provider connectivity lives in app.services.provider_router."""

from app.services.provider_router import (
    OpenAI,
    PROVIDER_DISPLAY_NAMES,
    SUPPORTED_PROVIDERS,
    gemini_is_disabled,
    generate,
    generate as llm_complete,
    get_active_provider_or_none,
    get_configured_model,
    get_ollama_base_url,
    get_provider,
    list_provider_diagnostics,
    log_active_llm_config,
    provider_available,
    provider_available as llm_available,
    reload_settings,
    run_provider_smoke_test,
)

__all__ = [
    "OpenAI",
    "PROVIDER_DISPLAY_NAMES",
    "SUPPORTED_PROVIDERS",
    "gemini_is_disabled",
    "generate",
    "llm_complete",
    "get_active_provider_or_none",
    "get_configured_model",
    "get_ollama_base_url",
    "get_provider",
    "list_provider_diagnostics",
    "log_active_llm_config",
    "provider_available",
    "llm_available",
    "reload_settings",
    "run_provider_smoke_test",
]
