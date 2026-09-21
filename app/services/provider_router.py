"""
AgentTrade-aligned LLM provider router for Campaign Console.

One configured provider. One request. One response. No fallbacks.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

CHAT_TIMEOUT_SECONDS = 45
SMOKE_TEST_PROMPT = "Reply with exactly OK"

SUPPORTED_PROVIDERS = {
    "openai",
    "gemini",
    "mistral",
    "groq",
    "deepseek",
    "ollama",
    "claude",
    "copilot",
}

PROVIDER_DISPLAY_NAMES = {
    "openai": "ChatGPT / OpenAI",
    "gemini": "Google Gemini",
    "mistral": "Mistral",
    "groq": "Groq",
    "deepseek": "DeepSeek",
    "ollama": "Ollama",
    "claude": "Claude",
    "copilot": "Copilot",
}

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.5-flash-lite",
    "mistral": "mistral-small-latest",
    "groq": "llama-3.3-70b-versatile",
    "deepseek": "deepseek-chat",
    "ollama": "llama2",
    "claude": "claude-3-5-sonnet-20241022",
    "copilot": "copilot",
}

MODEL_ENV_KEYS = {
    "openai": "OPENAI_MODEL",
    "gemini": "GEMINI_MODEL",
    "mistral": "MISTRAL_MODEL",
    "groq": "GROQ_MODEL",
    "deepseek": "DEEPSEEK_MODEL",
    "ollama": "OLLAMA_MODEL",
    "claude": "CLAUDE_MODEL",
    "copilot": "COPILOT_MODEL",
}

API_KEY_ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "groq": "GROQ_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "claude": ("CLAUDE_API_KEY", "ANTHROPIC_API_KEY"),
    "copilot": "COPILOT_API_KEY",
}

CHAT_ENDPOINT_URLS = {
    "mistral": "https://api.mistral.ai/v1/chat/completions",
    "deepseek": "https://api.deepseek.com/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
}

_openai_client: Optional[Any] = None


def reload_settings() -> None:
    global _openai_client
    load_dotenv(BASE_DIR / ".env", override=True)
    _openai_client = None


def gemini_is_disabled() -> bool:
    return os.getenv("GEMINI_DISABLED", "").lower() in {"1", "true", "yes"}


def get_provider() -> str:
    provider = os.getenv("CAMPAIGN_CONSOLE_LLM_PROVIDER", "").strip().lower()
    if not provider:
        raise RuntimeError("CAMPAIGN_CONSOLE_LLM_PROVIDER is not set.")
    if provider not in SUPPORTED_PROVIDERS:
        raise RuntimeError(f"Unsupported LLM provider: {provider}")
    if provider == "gemini" and gemini_is_disabled():
        raise RuntimeError("Gemini is disabled by GEMINI_DISABLED=true.")
    return provider


def get_active_provider_or_none() -> Optional[str]:
    try:
        return get_provider()
    except Exception:
        return None


def _normalize_mistral_model(model: str) -> str:
    cleaned = (model or "").strip()
    if not cleaned or cleaned.lower() == "mistral":
        return DEFAULT_MODELS["mistral"]
    return cleaned


def get_configured_model(provider: Optional[str] = None, model: Optional[str] = None) -> str:
    selected = (provider or get_provider()).lower()
    if model and model.strip():
        if selected == "mistral":
            return _normalize_mistral_model(model)
        return model.strip()
    env_key = MODEL_ENV_KEYS.get(selected)
    configured = os.getenv(env_key, "").strip() if env_key else ""
    if selected == "mistral":
        return _normalize_mistral_model(configured or DEFAULT_MODELS["mistral"])
    if configured:
        return configured
    return DEFAULT_MODELS.get(selected, selected)


def _api_key_for(provider: str) -> str:
    provider = provider.lower()
    key_spec = API_KEY_ENV_KEYS.get(provider)
    if isinstance(key_spec, tuple):
        for env_name in key_spec:
            value = os.getenv(env_name, "").strip()
            if value:
                return value
        return ""
    if key_spec:
        return os.getenv(key_spec, "").strip()
    return ""


def get_endpoint_url(provider: str, model: Optional[str] = None) -> str:
    provider = provider.lower()
    model_name = get_configured_model(provider, model)
    if provider in CHAT_ENDPOINT_URLS:
        override = os.getenv(
            {
                "mistral": "MISTRAL_API_URL",
                "deepseek": "DEEPSEEK_API_URL",
                "groq": "GROQ_API_URL",
            }[provider],
            "",
        ).strip()
        return override or CHAT_ENDPOINT_URLS[provider]
    if provider == "openai":
        return "https://api.openai.com/v1/chat/completions"
    if provider == "gemini":
        return f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
    if provider == "claude":
        return os.getenv("CLAUDE_API_URL") or os.getenv("ANTHROPIC_API_URL") or "https://api.anthropic.com/v1/messages"
    if provider == "ollama":
        base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        return f"{base}/api/generate"
    if provider == "copilot":
        return os.getenv("COPILOT_API_URL", "")
    return ""


def provider_available(provider: Optional[str] = None) -> bool:
    try:
        selected = (provider or get_provider()).lower()
    except Exception:
        return False
    if selected == "openai":
        return OpenAI is not None and bool(_api_key_for("openai"))
    if selected == "gemini":
        return not gemini_is_disabled() and bool(_api_key_for("gemini"))
    if selected == "ollama":
        return bool(os.getenv("OLLAMA_BASE_URL", "").strip() or True)
    if selected in {"mistral", "groq", "deepseek", "copilot", "claude"}:
        if selected == "copilot":
            return bool(_api_key_for("copilot") and get_endpoint_url("copilot"))
        if selected == "claude":
            return bool(_api_key_for("claude"))
        return bool(_api_key_for(selected))
    return False


def get_ollama_base_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")


def _get_openai_client() -> Any:
    global _openai_client
    if OpenAI is None:
        raise RuntimeError("The openai package is not installed.")
    api_key = _api_key_for("openai")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    if _openai_client is None:
        _openai_client = OpenAI(api_key=api_key)
    return _openai_client


def _parse_chat_completion_body(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    if isinstance(message, dict):
        return str(message.get("content") or "").strip()
    return ""


def _parse_gemini_body(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict)).strip()


def _call_openai(model: str, prompt: str, max_tokens: int) -> Dict[str, Any]:
    response = _get_openai_client().chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    text = response.choices[0].message.content or ""
    body = response.model_dump() if hasattr(response, "model_dump") else {"choices": [{"message": {"content": text}}]}
    return {
        "status_code": 200,
        "body": body,
        "parsed_text": str(text).strip(),
    }


def _call_gemini(model: str, prompt: str, max_tokens: int) -> Dict[str, Any]:
    api_key = _api_key_for("gemini")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "responseMimeType": "application/json"},
    }
    response = requests.post(url, params={"key": api_key}, json=payload, timeout=CHAT_TIMEOUT_SECONDS)
    body: Any
    try:
        body = response.json()
    except Exception:
        body = response.text
    parsed_text = _parse_gemini_body(body) if isinstance(body, dict) else ""
    if response.status_code >= 400:
        logger.error("gemini API error status=%s body=%s", response.status_code, response.text)
    return {
        "status_code": response.status_code,
        "body": body,
        "parsed_text": parsed_text,
    }


def _call_chat_endpoint(
    provider: str,
    model: str,
    prompt: str,
    max_tokens: int,
    api_url: str,
    api_key: str,
) -> Dict[str, Any]:
    if not api_key:
        raise RuntimeError(f"{provider.upper()}_API_KEY not set")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    response = requests.post(api_url, headers=headers, json=payload, timeout=CHAT_TIMEOUT_SECONDS)
    if response.status_code >= 400 and "response_format" in payload and (
        "response_format" in response.text.lower() or "json_object" in response.text.lower()
    ):
        payload.pop("response_format", None)
        response = requests.post(api_url, headers=headers, json=payload, timeout=CHAT_TIMEOUT_SECONDS)
    body: Any
    try:
        body = response.json()
    except Exception:
        body = response.text
    parsed_text = _parse_chat_completion_body(body) if isinstance(body, dict) else ""
    if response.status_code >= 400:
        logger.error("%s API error status=%s body=%s", provider, response.status_code, response.text)
    return {
        "status_code": response.status_code,
        "body": body,
        "parsed_text": parsed_text,
    }


def _call_ollama(model: str, prompt: str, max_tokens: int) -> Dict[str, Any]:
    url = get_endpoint_url("ollama", model)
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": max_tokens, "temperature": 0.7},
    }
    response = requests.post(url, json=payload, timeout=CHAT_TIMEOUT_SECONDS)
    body: Any
    try:
        body = response.json()
    except Exception:
        body = response.text
    parsed_text = ""
    if isinstance(body, dict):
        parsed_text = str(body.get("response") or "").strip()
    if response.status_code >= 400:
        logger.error("ollama API error status=%s body=%s", response.status_code, response.text)
    return {
        "status_code": response.status_code,
        "body": body,
        "parsed_text": parsed_text,
    }


def _call_claude(model: str, prompt: str, max_tokens: int) -> Dict[str, Any]:
    api_key = _api_key_for("claude")
    if not api_key:
        raise RuntimeError("CLAUDE_API_KEY or ANTHROPIC_API_KEY is not set.")
    url = get_endpoint_url("claude", model)
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    response = requests.post(url, json=payload, headers=headers, timeout=CHAT_TIMEOUT_SECONDS)
    body: Any
    try:
        body = response.json()
    except Exception:
        body = response.text
    parsed_text = ""
    if isinstance(body, dict):
        content = body.get("content") or []
        if content and isinstance(content[0], dict):
            parsed_text = str(content[0].get("text") or "").strip()
    if response.status_code >= 400:
        logger.error("claude API error status=%s body=%s", response.status_code, response.text)
    return {
        "status_code": response.status_code,
        "body": body,
        "parsed_text": parsed_text,
    }


def _dispatch_provider_call(provider: str, model: str, prompt: str, max_tokens: int) -> Dict[str, Any]:
    provider = provider.lower()
    if provider == "openai":
        return _call_openai(model, prompt, max_tokens)
    if provider == "gemini":
        return _call_gemini(model, prompt, max_tokens)
    if provider == "mistral":
        return _call_chat_endpoint(
            "mistral",
            model,
            prompt,
            max_tokens,
            get_endpoint_url("mistral", model),
            _api_key_for("mistral"),
        )
    if provider == "deepseek":
        return _call_chat_endpoint(
            "deepseek",
            model,
            prompt,
            max_tokens,
            get_endpoint_url("deepseek", model),
            _api_key_for("deepseek"),
        )
    if provider == "groq":
        return _call_chat_endpoint(
            "groq",
            model,
            prompt,
            max_tokens,
            get_endpoint_url("groq", model),
            _api_key_for("groq"),
        )
    if provider == "ollama":
        return _call_ollama(model, prompt, max_tokens)
    if provider == "claude":
        return _call_claude(model, prompt, max_tokens)
    if provider == "copilot":
        return _call_chat_endpoint(
            "copilot",
            model,
            prompt,
            max_tokens,
            get_endpoint_url("copilot", model),
            _api_key_for("copilot"),
        )
    raise RuntimeError(f"Unsupported LLM provider: {provider}")


def generate_raw(
    prompt: str,
    *,
    max_tokens: int = 1000,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    task_name: Optional[str] = None,
) -> Dict[str, Any]:
    selected_provider = (provider or get_provider()).lower()
    model_name = get_configured_model(selected_provider, model)
    endpoint_url = get_endpoint_url(selected_provider, model_name)
    logger.info(
        "LLM generate provider=%s model=%s task=%s max_tokens=%s endpoint=%s",
        selected_provider,
        model_name,
        task_name or "unknown",
        max_tokens,
        endpoint_url,
    )
    result = _dispatch_provider_call(selected_provider, model_name, prompt, max_tokens)
    return {
        "provider": selected_provider,
        "model": model_name,
        "endpoint_url": endpoint_url,
        "status_code": result["status_code"],
        "body": result["body"],
        "parsed_text": result.get("parsed_text") or "",
    }


def generate(
    prompt: str,
    *,
    max_tokens: int = 1000,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    task_name: Optional[str] = None,
    temperature: Optional[float] = None,
) -> str:
    del temperature  # AgentTrade router does not expose temperature overrides.
    result = generate_raw(
        prompt,
        max_tokens=max_tokens,
        model=model,
        provider=provider,
        task_name=task_name,
    )
    if result["status_code"] != 200:
        raise RuntimeError(f"{result['provider']} HTTP {result['status_code']}: {result['body']}")
    text = result.get("parsed_text") or ""
    if not text:
        raise RuntimeError(f"{result['provider']} response did not contain text.")
    return text


def list_provider_diagnostics() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for provider in sorted(SUPPORTED_PROVIDERS):
        model = get_configured_model(provider)
        rows.append(
            {
                "provider": provider,
                "model": model,
                "endpoint_url": get_endpoint_url(provider, model),
                "api_key_present": bool(_api_key_for(provider)) if provider != "ollama" else True,
            }
        )
    return rows


def run_provider_smoke_test(
    prompt: str = SMOKE_TEST_PROMPT,
    *,
    max_tokens: int = 20,
) -> Dict[str, Any]:
    return generate_raw(prompt, max_tokens=max_tokens, task_name="debug/provider-test")


def log_active_llm_config() -> None:
    try:
        provider = get_provider()
        model = get_configured_model(provider)
        logger.info("LLM provider=%s model=%s endpoint=%s", provider, model, get_endpoint_url(provider, model))
    except Exception as exc:
        logger.info("LLM provider not configured: %s", exc)
