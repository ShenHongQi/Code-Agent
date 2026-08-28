"""事件钩子系统：允许插件和内部模块扩展 agent 行为。"""

from __future__ import annotations
from enum import Enum
from typing import Any, Callable


class Event(Enum):
    BEFORE_LLM_CALL = "before_llm_call"
    AFTER_LLM_CALL = "after_llm_call"
    BEFORE_TOOL_EXEC = "before_tool_exec"
    AFTER_TOOL_EXEC = "after_tool_exec"
    ON_ERROR = "on_error"
    ON_STUCK = "on_stuck"
    ON_TURN_START = "on_turn_start"
    ON_TURN_END = "on_turn_end"
    ON_COMPACTION = "on_compaction"


_hooks: dict[Event, list[Callable]] = {e: [] for e in Event}


def register(event: Event, handler: Callable) -> None:
    """注册事件处理函数。"""
    _hooks[event].append(handler)


def unregister(event: Event, handler: Callable) -> None:
    """取消注册事件处理函数。"""
    try:
        _hooks[event].remove(handler)
    except ValueError:
        pass


def emit(event: Event, **kwargs: Any) -> list[Any]:
    """触发事件，执行所有已注册的处理函数。"""
    results = []
    for handler in _hooks[event]:
        try:
            result = handler(**kwargs)
            results.append(result)
        except Exception:
            pass
    return results


def clear_all() -> None:
    """清除所有钩子（测试用）。"""
    for e in Event:
        _hooks[e].clear()
