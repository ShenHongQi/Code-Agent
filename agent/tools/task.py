"""Sub-agent 工具：委托子任务给独立 agent 执行。"""

from __future__ import annotations

from agent.llm import Provider
from agent.tools import ToolResult, tool
from agent.workspace import Workspace

_workspace: Workspace | None = None
_provider: Provider | None = None
_depth: int = 0
_active_count: int = 0

MAX_DEPTH = 1
SUBAGENT_MAX_ITERATIONS = 25
SUBAGENT_PER_TURN = 5

# 三级工具权限
TOOL_TIERS = {
    "read_only": {"read_file", "glob", "grep", "bash", "list_dir", "view_diff", "web_fetch"},
    "write": {"read_file", "write_file", "edit_file", "multi_edit", "delete_file",
              "rename_file", "glob", "grep", "bash", "list_dir", "view_diff", "web_fetch"},
    "full": None,  # None = 除 task 外全部
}


def init(workspace: Workspace, provider: Provider, depth: int = 0) -> None:
    global _workspace, _provider, _depth
    _workspace = workspace
    _provider = provider
    _depth = depth


@tool
def task(description: str, tools: str = "read_only") -> ToolResult:
    """委托一个聚焦子任务给 sub-agent 执行。

    description: 详细的任务描述
    tools: 工具权限级别 - "read_only"（默认只读）、"write"（可修改文件）、"full"（全部工具）
    """
    global _active_count
    assert _workspace and _provider

    if _depth >= MAX_DEPTH:
        return ToolResult(False, "Error: Sub-agent nesting depth exceeded (max 1).")

    if _active_count >= SUBAGENT_PER_TURN:
        return ToolResult(False, f"Error: Maximum sub-agents per turn reached ({SUBAGENT_PER_TURN}).")

    if tools not in TOOL_TIERS:
        return ToolResult(False, "Error: Invalid tools tier. Use: read_only, write, or full.")

    # 确定可用工具集
    allowed = TOOL_TIERS[tools]
    if allowed is None:
        # "full" = 除了 task 本身和 extend_iterations
        from agent.tools import get_registry
        allowed = set(get_registry().keys()) - {"task", "extend_iterations"}

    # 构建 sub-agent prompt
    from agent.prompts import SUBAGENT_PROMPT
    if tools == "read_only":
        prompt = SUBAGENT_PROMPT
    elif tools == "write":
        prompt = (
            "You are a sub-agent with file read AND write access. "
            "Complete the task described below. You can read, write, edit, and delete files. "
            "Be careful with modifications — verify before writing. "
            "Report your findings and actions as your final message."
        )
    else:
        prompt = (
            "You are a sub-agent with full tool access. "
            "Complete the task described below autonomously. "
            "Report your findings and actions as your final message."
        )

    from agent.history import History, make_user
    from agent.loop import run_loop
    from agent.ui import UI

    sub_history = History(prompt)
    sub_history.append(make_user(description))
    sub_ui = UI(stream=True)

    _active_count += 1
    try:
        result = run_loop(
            sub_history,
            _provider,
            sub_ui,
            max_iterations=SUBAGENT_MAX_ITERATIONS,
            allowed_tools=allowed,
        )
    finally:
        _active_count -= 1

    # 提取 sub-agent 最后的输出
    last_content = ""
    for msg in reversed(sub_history.messages):
        if msg.get("role") == "assistant" and msg.get("content"):
            last_content = msg["content"]
            break

    if not last_content:
        last_content = f"(Sub-agent finished: {result.reason}, {result.iterations} iterations)"

    # 限制结果长度
    if len(last_content) > 6000:
        last_content = last_content[:6000] + "\n... (truncated)"

    return ToolResult(True, last_content)
