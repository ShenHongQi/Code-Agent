"""Agent 控制工具：迭代管理。"""

from __future__ import annotations

from agent.tools import tool, ToolResult


@tool
def extend_iterations(reason: str) -> ToolResult:
    """当前任务需要更多步骤时，请求延长迭代上限。

    reason: 简要说明为什么需要更多步骤
    """
    from agent.loop import request_extend
    request_extend()
    return ToolResult(True, f"Iterations extended. Reason: {reason}")
