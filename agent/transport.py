"""纯标准库的第二个 Provider 实现：urllib + 手写 SSE 行解析。

通过 AGENT_TRANSPORT=raw 切换。证明 SDK 只是可替换的 HTTP client。
"""

from __future__ import annotations
import json
import urllib.request
import urllib.error
from typing import Any, Iterator

from agent.config import config
from agent.llm import Provider, LLMError, _classify_error


class RawProvider(Provider):
    """基于 urllib.request 的 Provider 实现，不依赖 openai SDK。"""

    def __init__(self):
        self._api_key = config.api_key
        self._base_url = config.base_url.rstrip("/")

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[dict[str, Any]]:
        url = f"{self._base_url}/chat/completions"

        body: dict[str, Any] = {
            "model": config.model,
            "messages": messages,
            "max_tokens": config.max_output_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            body["tools"] = tools

        data = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "text/event-stream",
        }

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            resp = urllib.request.urlopen(req, timeout=180)
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")
            raise _classify_error(e.code, body_text) from e
        except Exception as e:
            raise LLMError(f"Connection error: {e}", 0, retryable=True) from e

        yield from self._parse_sse(resp)

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/chat/completions"

        body: dict[str, Any] = {
            "model": config.model,
            "messages": messages,
            "max_tokens": config.max_output_tokens,
            "stream": False,
        }
        if tools:
            body["tools"] = tools

        data = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            resp = urllib.request.urlopen(req, timeout=180)
            return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")
            raise _classify_error(e.code, body_text) from e
        except Exception as e:
            raise LLMError(f"Connection error: {e}", 0, retryable=True) from e

    def _parse_sse(self, resp) -> Iterator[dict[str, Any]]:
        """手写 SSE 行解析。"""
        buffer = ""
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace")
            buffer += line

            while "\n" in buffer:
                text_line, buffer = buffer.split("\n", 1)
                text_line = text_line.rstrip("\r")

                if text_line.startswith("data: "):
                    payload = text_line[6:]
                    if payload.strip() == "[DONE]":
                        return
                    try:
                        chunk = json.loads(payload)
                        yield chunk
                    except json.JSONDecodeError:
                        continue
