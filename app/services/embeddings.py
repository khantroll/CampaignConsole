import hashlib
import json
import logging
import math
import os
import re
from datetime import datetime, timezone
from typing import List, Optional

import httpx

from app.services.provider_router import OpenAI, get_ollama_base_url

logger = logging.getLogger(__name__)

LOCAL_EMBED_DIM = 256
DEFAULT_EMBEDDING_PROVIDER = "local_fallback"
DEFAULT_OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
DEFAULT_OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
OPENAI_EMBEDDING_BULK_LIMIT = 5


def _normalize(vector: List[float]) -> List[float]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return vector
    return [value / magnitude for value in vector]


def _local_embed(text: str, dim: int = LOCAL_EMBED_DIM) -> List[float]:
    vector = [0.0] * dim
    tokens = re.findall(r"[a-z0-9']+", text.lower())
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        index = int(digest[:8], 16) % dim
        vector[index] += 1.0
    return _normalize(vector)


def _configured_embedding_provider() -> str:
    raw = os.getenv("CAMPAIGN_CONSOLE_EMBEDDING_PROVIDER", DEFAULT_EMBEDDING_PROVIDER)
    if not raw or not raw.strip():
        return DEFAULT_EMBEDDING_PROVIDER
    return raw.strip().lower()


def _log_embedding_call(provider: str, texts: List[str], task_name: str) -> None:
    total_chars = sum(len(text) for text in texts)
    logger.info(
        "Embedding call provider=%s texts=%s chars=%s task=%s timestamp=%s",
        provider,
        len(texts),
        total_chars,
        task_name,
        datetime.now(timezone.utc).isoformat(),
    )


def _openai_embed(texts: List[str], model: Optional[str] = None) -> List[List[float]]:
    if OpenAI is None:
        raise RuntimeError("The openai package is not installed.")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    client = OpenAI(api_key=api_key)
    model_name = model or DEFAULT_OPENAI_EMBED_MODEL
    response = client.embeddings.create(model=model_name, input=texts)
    return [list(item.embedding) for item in response.data]


def _ollama_embed(texts: List[str], model: Optional[str] = None) -> List[List[float]]:
    model_name = model or DEFAULT_OLLAMA_EMBED_MODEL
    vectors: List[List[float]] = []
    for text in texts:
        response = httpx.post(
            f"{get_ollama_base_url()}/api/embeddings",
            json={"model": model_name, "prompt": text},
            timeout=90.0,
        )
        response.raise_for_status()
        data = response.json()
        embedding = data.get("embedding")
        if not embedding:
            raise RuntimeError("Ollama embeddings response did not include an embedding vector.")
        vectors.append(list(embedding))
    return vectors


def embedding_provider_available(provider: str) -> bool:
    if provider in {"local", "local_fallback"}:
        return True
    if provider == "openai":
        return OpenAI is not None and bool(os.getenv("OPENAI_API_KEY"))
    if provider == "ollama":
        return bool(get_ollama_base_url())
    return False


def resolve_embedding_provider() -> str:
    configured = _configured_embedding_provider()
    if configured in {"local", "local_fallback", "auto"}:
        return "local_fallback"
    if configured == "openai":
        return "local_fallback"
    if configured == "ollama":
        if not embedding_provider_available("ollama"):
            raise RuntimeError("Embedding provider 'ollama' is not available.")
        return "ollama"
    return "local_fallback"


def get_active_embedding_provider() -> str:
    configured = _configured_embedding_provider()
    if configured in {"local", "local_fallback", "auto"}:
        return "local_fallback"
    if configured == "openai":
        return "local_fallback"
    if configured == "ollama":
        if embedding_provider_available("ollama"):
            return "ollama"
        return "local_fallback"
    return "local_fallback"


def embeddings_available() -> bool:
    return get_active_embedding_provider() != "local_fallback"


def embed_texts(
    texts: List[str],
    provider: Optional[str] = None,
    task_name: str = "unknown",
) -> List[List[float]]:
    if not texts:
        return []
    selected = provider or resolve_embedding_provider()
    explicit = provider is not None
    configured = os.getenv("CAMPAIGN_CONSOLE_EMBEDDING_PROVIDER", DEFAULT_EMBEDDING_PROVIDER)
    logger.error(
        "EMBED CALL -> configured=%s provider=%s texts=%s task=%s",
        configured,
        selected,
        len(texts),
        task_name,
    )
    _log_embedding_call(selected, texts, task_name)
    if selected == "openai":
        if len(texts) > OPENAI_EMBEDDING_BULK_LIMIT and os.getenv("OPENAI_EMBEDDING_BULK_OK") != "true":
            raise RuntimeError(
                "OpenAI bulk embeddings blocked. Set OPENAI_EMBEDDING_BULK_OK=true to allow."
            )
        try:
            return _openai_embed(texts)
        except Exception:
            if explicit:
                raise
            return [_local_embed(text) for text in texts]
    if selected == "ollama":
        try:
            return _ollama_embed(texts)
        except Exception:
            if explicit:
                raise
            return [_local_embed(text) for text in texts]
    if selected in {"local", "local_fallback"}:
        return [_local_embed(text) for text in texts]
    return [_local_embed(text) for text in texts]


def embed_text(text: str, provider: Optional[str] = None, task_name: str = "unknown") -> List[float]:
    return embed_texts([text], provider=provider, task_name=task_name)[0]


def serialize_embedding(vector: List[float]) -> str:
    return json.dumps(vector)


def deserialize_embedding(raw: str) -> List[float]:
    return [float(value) for value in json.loads(raw)]


def cosine_similarity(left: List[float], right: List[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_mag = math.sqrt(sum(a * a for a in left))
    right_mag = math.sqrt(sum(b * b for b in right))
    if left_mag == 0 or right_mag == 0:
        return 0.0
    return dot / (left_mag * right_mag)
