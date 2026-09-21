import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / ".env"

MANAGED_KEYS: List[str] = [
    "CAMPAIGN_CONSOLE_LLM_PROVIDER",
    "CAMPAIGN_CONSOLE_DISABLED_LLM_PROVIDERS",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OLLAMA_BASE_URL",
    "OLLAMA_MODEL",
    "ANTHROPIC_API_KEY",
    "CLAUDE_API_KEY",
    "CLAUDE_MODEL",
    "CLAUDE_API_URL",
    "ANTHROPIC_API_URL",
    "GEMINI_API_URL",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GEMINI_FAST_MODEL",
    "GEMINI_REASONING_MODEL",
    "GEMINI_DISABLED",
    "GEMINI_MIN_INTERVAL_SECONDS",
    "MISTRAL_API_URL",
    "MISTRAL_API_KEY",
    "MISTRAL_MODEL",
    "GROQ_MODEL",
    "DEEPSEEK_MODEL",
    "NVIDIA_API_KEY",
    "NVIDIA_BASE_URL",
    "NVIDIA_MODEL",
    "COPILOT_API_URL",
    "COPILOT_API_KEY",
    "GROQ_API_URL",
    "GROQ_API_KEY",
    "DEEPSEEK_API_URL",
    "DEEPSEEK_API_KEY",
    "CAMPAIGN_CONSOLE_EMBEDDING_PROVIDER",
    "OPENAI_EMBEDDING_MODEL",
    "OPENAI_EMBEDDING_BULK_OK",
    "OLLAMA_EMBED_MODEL",
    "OLLAMA_EMBED_ENABLED",
]

SECRET_KEYS = {
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "CLAUDE_API_KEY",
    "GEMINI_API_KEY",
    "MISTRAL_API_KEY",
    "COPILOT_API_KEY",
    "GROQ_API_KEY",
    "DEEPSEEK_API_KEY",
    "NVIDIA_API_KEY",
}

_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$")


def parse_env_file(path: Optional[Path] = None) -> Dict[str, str]:
    env_path = path or ENV_FILE
    values: Dict[str, str] = {}
    if not env_path.exists():
        return values

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ENV_LINE.match(line)
        if not match:
            continue
        key, raw_value = match.group(1), match.group(2)
        values[key] = _unquote(raw_value)
    return values


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _quote_if_needed(value: str) -> str:
    if not value:
        return ""
    if any(char.isspace() for char in value) or "#" in value:
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "••••"
    return f"{'•' * 8}{value[-4:]}"


def get_llm_settings_for_form() -> Dict[str, str]:
    values = parse_env_file()
    form_values: Dict[str, str] = {}
    for key in MANAGED_KEYS:
        raw = values.get(key, "")
        if key in SECRET_KEYS and raw:
            form_values[key] = ""
            form_values[f"{key}__masked"] = mask_secret(raw)
            form_values[f"{key}__configured"] = "1"
        else:
            form_values[key] = raw
    return form_values


def update_env_file(updates: Dict[str, Optional[str]], path: Optional[Path] = None) -> None:
    env_path = path or ENV_FILE
    current = parse_env_file(env_path)

    for key, value in updates.items():
        if key not in MANAGED_KEYS:
            continue
        if key in SECRET_KEYS:
            if value is None or value == "":
                continue
            current[key] = value
        elif value is None:
            current.pop(key, None)
        else:
            current[key] = value.strip()

    managed_set = set(MANAGED_KEYS)
    unknown = {key: val for key, val in current.items() if key not in managed_set}

    lines: List[str] = [
        "# Campaign Console environment settings",
        "# Managed from /settings/llm or edit manually",
        "",
    ]
    for key in MANAGED_KEYS:
        if key in current and current[key] != "":
            lines.append(f"{key}={_quote_if_needed(current[key])}")
    if unknown:
        lines.append("")
        lines.append("# Additional settings")
        for key in sorted(unknown):
            lines.append(f"{key}={_quote_if_needed(unknown[key])}")
    lines.append("")

    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(lines), encoding="utf-8")


def apply_env_to_process(path: Optional[Path] = None) -> None:
    env_path = path or ENV_FILE
    if env_path.exists():
        load_dotenv(env_path, override=True)
    from app.services.provider_router import reload_settings

    reload_settings()
