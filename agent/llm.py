"""Provider 抽象；重试与错误分类。"""

from __future__ import annotations
import random
import time
from typing import Any, Iterator

from agent.config import config
from agent.stream import StreamAccumulator


class LLMError(Exception):
    def __init__(self, message: str, status_code: int = 0, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class ContextLengthExceeded(LLMError):
    pass


def _classify_error(status_code: int, body: str) -> LLMError:
    if status_code == 400 and "context_length" in body.lower():
        return ContextLengthExceeded(
            f"Context length exceeded: {body}", status_code, retryable=False
        )
    if status_code in (429, 408, 500, 502, 503, 504):
        return LLMError(f"Retryable error {status_code}: {body}", status_code, retryable=True)
    return LLMError(f"Fatal error {status_code}: {body}", status_code, retryable=False)


def _full_jitter(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    return random.uniform(0, min(cap, base * (2 ** attempt)))


class Provider:
    """基于 openai SDK 的 provider 实现。"""

    def __init__(self):
        import openai
        self._client = openai.OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            max_retries=0,
        )

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "model": config.model,
            "messages": messages,
            "max_tokens": config.max_output_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools

        try:
            response = self._client.chat.completions.create(**kwargs)
            for chunk in response:
                yield chunk.model_dump()
        except Exception as e:
            status = getattr(e, "status_code", 0)
            body = str(e)
            raise _classify_error(status, body) from e

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": config.model,
            "messages": messages,
            "max_tokens": config.max_output_tokens,
            "stream": False,
        }
        if tools:
            kwargs["tools"] = tools

        try:
            response = self._client.chat.completions.create(**kwargs)
            return response.model_dump()
        except Exception as e:
            status = getattr(e, "status_code", 0)
            body = str(e)
            raise _classify_error(status, body) from e


def stream_with_retry(
    provider: Provider,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    max_retries: int = 5,
) -> StreamAccumulator:
    """带重试的流式调用，返回累积后的完整结果。"""
    last_error: LLMError | None = None

    for attempt in range(max_retries + 1):
        try:
            acc = StreamAccumulator()
            for chunk in provider.stream_chat(messages, tools):
                acc.feed(chunk)
            return acc
        except LLMError as e:
            last_error = e
            if not e.retryable or attempt == max_retries:
                raise
            delay = _full_jitter(attempt)
            time.sleep(delay)

    raise last_error  # type: ignore


def create_provider() -> Provider:
    if config.transport == "raw":
        from agent.transport import RawProvider
        return RawProvider()  # type: ignore
    return Provider()
