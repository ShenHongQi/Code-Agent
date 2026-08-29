"""消息构造与会话状态管理。"""

from __future__ import annotations

from typing import Any


def make_system(content: str) -> dict[str, Any]:
    return {"role": "system", "content": content}


def make_user(content: str) -> dict[str, Any]:
    return {"role": "user", "content": content}


def make_assistant(content: str | None = None, tool_calls: list | None = None) -> dict[str, Any]:
    msg: dict[str, Any] = {"role": "assistant"}
    if content is not None:
        msg["content"] = content
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def make_tool(tool_call_id: str, content: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


class History:
    """会话历史容器。"""

    def __init__(self, system_prompt: str):
        self._system = make_system(system_prompt)
        self._messages: list[dict[str, Any]] = []

    def append(self, message: dict[str, Any]) -> None:
        self._messages.append(message)

    @property
    def messages(self) -> list[dict[str, Any]]:
        return self._messages

    def get_messages_for_api(self) -> list[dict[str, Any]]:
        return [self._system] + self._messages

    def seal_pending_tool_calls(self) -> None:
        """为所有未配对的 tool_call 补齐占位 tool 消息。"""
        pending_ids = self._find_orphan_tool_call_ids()
        for tc_id in pending_ids:
            self.append(make_tool(tc_id, "Interrupted before execution."))

    def _find_orphan_tool_call_ids(self) -> list[str]:
        """找出有 tool_call 但缺对应 tool 结果的 id（保持原始顺序）。"""
        called: list[str] = []
        answered: set[str] = set()
        for msg in self._messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    called.append(tc["id"])
            elif msg.get("role") == "tool":
                answered.add(msg["tool_call_id"])
        return [tc_id for tc_id in called if tc_id not in answered]

    def to_serializable(self) -> list[dict[str, Any]]:
        """返回可 JSON 序列化的消息列表（不含 system）。"""
        return list(self._messages)

    @classmethod
    def from_serializable(cls, system_prompt: str, messages: list[dict[str, Any]]) -> "History":
        """从序列化数据恢复 History。"""
        h = cls(system_prompt)
        h._messages = list(messages)
        return h

    def update_system(self, system_prompt: str) -> None:
        """热更新 system prompt。"""
        self._system = make_system(system_prompt)

    def __len__(self) -> int:
        return len(self._messages)
