"""OpenAI-compatible LLM client for translation and gap filling."""

from __future__ import annotations

import logging

from openai import OpenAI

from smart_subtitle.core.config import TranslationConfig
from smart_subtitle.core.exceptions import LLMError

logger = logging.getLogger("smart_subtitle.translation")


class LLMClient:
    """OpenAI-compatible LLM client. Works with OpenAI, Ollama, LM Studio, DeepSeek."""

    def __init__(self, config: TranslationConfig):
        self.config = config
        self.client = OpenAI(
            base_url=config.base_url,
            api_key=config.get_api_key(),
        )
        self.model = config.model

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Send a chat completion request and return the response text."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature or self.config.temperature,
                max_tokens=max_tokens or self.config.max_tokens,
            )
            content = response.choices[0].message.content
            if not content:
                raise LLMError("LLM returned empty response")
            return content.strip()
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"LLM request failed: {e}") from e

    def chat_with_usage(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> tuple[str, dict]:
        """Same as chat() but also returns token usage info."""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature or self.config.temperature,
                max_tokens=max_tokens or self.config.max_tokens,
            )
            content = response.choices[0].message.content
            if not content:
                raise LLMError("LLM returned empty response")
            usage = {}
            if response.usage:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
            return content.strip(), usage
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"LLM request failed: {e}") from e
