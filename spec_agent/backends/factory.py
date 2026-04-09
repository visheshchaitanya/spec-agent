from __future__ import annotations

from spec_agent.backends.base import LLMBackend
from spec_agent.config import Config


def get_backend(cfg: Config) -> LLMBackend:
    """Instantiate and return the configured LLM backend.

    Backends are imported lazily so that optional dependencies (e.g.
    google-genai, requests) are only required when the matching backend
    is actually selected.

    Args:
        cfg: Loaded spec-agent configuration.

    Returns:
        A concrete LLMBackend instance.

    Raises:
        ValueError: If cfg.llm_backend is not a recognised backend name.
    """
    match cfg.llm_backend:
        case "anthropic":
            from spec_agent.backends.anthropic_backend import AnthropicBackend
            return AnthropicBackend(model=cfg.model)
        case "ollama":
            from spec_agent.backends.ollama_backend import OllamaBackend
            return OllamaBackend(base_url=cfg.ollama_url, model=cfg.ollama_model)
        case "gemini":
            from spec_agent.backends.gemini_backend import GeminiBackend
            return GeminiBackend(model=cfg.gemini_model)
        case _:
            raise ValueError(
                f"Unknown llm_backend: {cfg.llm_backend!r}. "
                "Choose from: anthropic, ollama, gemini"
            )
