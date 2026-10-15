"""
LangSmith tracing bootstrap (standalone SDK, no LangChain dependency).

Active only if LANGSMITH_API_KEY is present in .env. OpenAI clients created
by key_pool are wrapped with wrap_openai, so every LLM call is traced
(model, tokens, cost, latency). Pipeline stages are annotated with
@stage(...) to get the nested per-query waterfall.

Settings loads .env via pydantic-settings with extra="ignore", so the SDK
would never see LANGSMITH_* by itself: init_tracing() copies the values
into os.environ before the first client is created.
"""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from langsmith import traceable as _traceable
    from langsmith.wrappers import wrap_openai as _wrap_openai
    _LANGSMITH_AVAILABLE = True
except ImportError:
    _LANGSMITH_AVAILABLE = False

_enabled: Optional[bool] = None


def init_tracing() -> bool:
    """Export LANGSMITH_* into os.environ from Settings. Idempotent."""
    global _enabled
    if _enabled is not None:
        return _enabled

    if not _LANGSMITH_AVAILABLE:
        _enabled = False
        return False

    # Lazy import to avoid cycles (same pattern as key_pool)
    from .config import get_settings
    settings = get_settings()

    api_key = (settings.langsmith_api_key or "").strip()
    if not api_key:
        _enabled = False
        logger.info("LangSmith tracing disabilitato (LANGSMITH_API_KEY assente)")
        return False

    os.environ.setdefault("LANGSMITH_API_KEY", api_key)
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)
    os.environ.setdefault("LANGSMITH_ENDPOINT", settings.langsmith_endpoint)
    _enabled = True
    logger.info(
        "LangSmith tracing attivo (project=%s, endpoint=%s)",
        os.environ["LANGSMITH_PROJECT"], os.environ["LANGSMITH_ENDPOINT"],
    )
    return True


def wrap_llm_client(client):
    """Wrap an OpenAI client for tracing; passthrough when disabled."""
    if not init_tracing():
        return client
    client = _wrap_openai(client)
    # wrap_openai (langsmith 0.11) covers chat/completions but not embeddings:
    # the pipeline calls embeddings in engine, coherence_validator and dedup
    if not hasattr(client.embeddings.create, "__wrapped__"):
        client.embeddings.create = _traceable(
            name="openai_embeddings", run_type="embedding"
        )(client.embeddings.create)
    return client


def _drop_self(inputs: dict) -> dict:
    return {k: v for k, v in inputs.items() if k != "self"}


def stage(name: str):
    """
    Decorator for pipeline stages: creates a nested run with the given name.
    No-op if langsmith is not installed or tracing is disabled
    (traceable records nothing without LANGSMITH_TRACING in the environment).
    """
    def deco(fn):
        if not _LANGSMITH_AVAILABLE:
            return fn
        return _traceable(name=name, run_type="chain", process_inputs=_drop_self)(fn)
    return deco
