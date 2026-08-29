"""流式 delta 重组：将 SSE chunk 累积为完整的 assistant 消息。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PartialToolCall:
    index: int = 0
    id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass
class StreamAccumulator:
    """累积流式 chunk，最终输出完整 assistant 消息。"""

    content: str = ""
    tool_calls: dict[int, PartialToolCall] = field(default_factory=dict)
    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)

    def feed(self, chunk: dict[str, Any]) -> str | None:
        """喂入一个 chunk，返回新增的 content 文本（用于实时渲染）。"""
        if chunk.get("usage"):
            self.usage = chunk["usage"]

        choices = chunk.get("choices")
        if not choices:
            return None

        choice = choices[0]
        self.finish_reason = choice.get("finish_reason") or self.finish_reason
        delta = choice.get("delta", {})

        new_text = None
        if delta.get("content"):
            new_text = delta["content"]
            self.content += new_text

        if delta.get("tool_calls"):
            for tc_delta in delta["tool_calls"]:
                idx = tc_delta.get("index", 0)
                if idx not in self.tool_calls:
                    self.tool_calls[idx] = PartialToolCall(index=idx)
                partial = self.tool_calls[idx]

                if tc_delta.get("id"):
                    partial.id += tc_delta["id"]
                func = tc_delta.get("function", {})
                if func.get("name"):
                    partial.name += func["name"]
                if func.get("arguments"):
                    partial.arguments += func["arguments"]

        return new_text

    def to_message(self) -> dict[str, Any]:
        """流结束后，构造完整的 assistant 消息。"""
        msg: dict[str, Any] = {"role": "assistant"}
        if self.content:
            msg["content"] = self.content

        if self.tool_calls:
            calls = []
            for idx in sorted(self.tool_calls):
                tc = self.tool_calls[idx]
                calls.append({
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.arguments,
                    },
                })
            msg["tool_calls"] = calls
        return msg

    def get_tool_calls(self) -> list[dict[str, Any]]:
        """返回解析后的 tool_call 列表（含 parsed arguments）。"""
        result = []
        for idx in sorted(self.tool_calls):
            tc = self.tool_calls[idx]
            try:
                args = json.loads(tc.arguments) if tc.arguments else {}
            except json.JSONDecodeError:
                args = {"__raw__": tc.arguments}
            result.append({
                "id": tc.id,
                "name": tc.name,
                "arguments": args,
            })
        return result

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    @property
    def is_natural_stop(self) -> bool:
        return self.finish_reason == "stop" and not self.has_tool_calls
