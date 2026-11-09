"""LLM backend interface and default OpenAI implementation.

The `LLMClient` abstracts provider-specific calls behind a simple `complete`
method. `LiteLLMClient` routes through LiteLLM for vendor-agnostic access with
automatic fallback; `OpenAIClient` is the direct provider implementation.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class LLMResponse(BaseModel):
    text: str
    prompt_tokens: int
    completion_tokens: int
    model: str
    provider: str
    raw: dict[str, Any] | None = None


class LLMClient(ABC):
    """Abstract LLM client."""

    @abstractmethod
    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        raise NotImplementedError


class OpenAIClient(LLMClient):
    """Direct OpenAI chat-completions client."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "gpt-4o",
    ) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover - dependency error
            raise ImportError("openai package is required for OpenAIClient") from exc

        self._client = AsyncOpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"), base_url=base_url)
        self.model = model
        self.provider = "openai"

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        choice = response.choices[0]
        text = choice.message.content or ""
        usage = response.usage
        return LLMResponse(
            text=text,
            prompt_tokens=getattr(usage, "prompt_tokens", 0),
            completion_tokens=getattr(usage, "completion_tokens", 0),
            model=getattr(response, "model", self.model),
            provider=self.provider,
            raw=response.model_dump() if hasattr(response, "model_dump") else None,
        )


class LiteLLMClient(LLMClient):
    """LiteLLm-routed client with provider fallback."""

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        try:
            from litellm import acompletion
        except ImportError as exc:  # pragma: no cover
            raise ImportError("litellm package is required for LiteLLMClient") from exc

        self._acompletion = acompletion
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.provider = "litellm"

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        response = await self._acompletion(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=self.api_key,
            api_base=self.base_url,
        )
        choice = response.choices[0]
        text = choice.message.content or ""
        usage = getattr(response, "usage", {}) or {}
        return LLMResponse(
            text=text,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            model=getattr(response, "model", self.model),
            provider=self.provider,
            raw=response.model_dump() if hasattr(response, "model_dump") else None,
        )


def build_llm_client() -> LLMClient:
    """Factory function: build the configured LLM client."""
    from factory.config import settings

    provider = settings.llm_provider.lower()
    if provider == "openai":
        return OpenAIClient(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
        )
    if provider == "litellm":
        return LiteLLMClient(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )
    # Default: treat any unknown provider as LiteLLM-routed for flexibility
    return LiteLLMClient(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
    )


__all__ = ["LLMClient", "LLMResponse", "OpenAIClient", "LiteLLMClient", "build_llm_client"]
