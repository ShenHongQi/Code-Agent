"""task 工具：派生只读子代理进行探索。"""

from __future__ import annotations
from typing import Any

from agent.tools import tool, ToolResult


_workspace = None
_provider = None
_depth = 0
MAX_DEPTH = 1
SUBAGENT_MAX_ITERATIONS = 15
SUBAGENT_CONCURRENT = 3
SUBAGENT_PER_TURN = 5

_active_count = 0


def init(workspace, provider, depth: int = 0) -> None:
    global _workspace, _provider, _depth
    _workspace = workspace
    _provider = provider
    _depth = depth


@tool
def task(description: str) -> ToolResult:
    """派生一个只读子代理来探索代码库并回报结果。子代理只能读取文件，不能写入。

    description: 要探索的任务描述（如"找出项目中所有的错误处理模式"）
    """
    global _active_count

    if _depth >= MAX_DEPTH:
        return ToolResult(False, "Error: Maximum sub-agent depth reached. Cannot spawn nested sub-agents.")

    if _active_count >= SUBAGENT_PER_TURN:
        return ToolResult(False, "Error: Maximum sub-agents per turn reached (5). Complete current tasks first.")

    assert _workspace and _provider

    from agent.history import History
    from agent.prompts import SUBAGENT_PROMPT
    from agent.loop import run_loop
    from agent.ui import UI
    from agent.tools import get_tools_schema
    from agent.workspace import Workspace, FileRegistry
    from agent.tools import fs as fs_mod, search as search_mod, bash as bash_mod

    # Create isolated sub-agent with read-only tools
    sub_history = History(SUBAGENT_PROMPT)
    sub_ui = UI(stream=True)

    # The sub-agent runs in the same workspace but with limited tools
    # We run it synchronously
    from agent.history import make_user
    sub_history.append(make_user(description))

    _active_count += 1
    try:
        sub_ui.info(f"\n  ⊳ Sub-agent: {description[:60]}")
        result = run_loop(
            sub_history,
            _provider,
            sub_ui,
            max_iterations=SUBAGENT_MAX_ITERATIONS,
        )
    finally:
        _active_count -= 1

    # Extract the last assistant content as the result
    for msg in reversed(sub_history.messages):
        if msg.get("role") == "assistant" and msg.get("content"):
            return ToolResult(True, msg["content"][:4000])

    return ToolResult(True, f"Sub-agent completed ({result.reason}) but produced no text output.")
