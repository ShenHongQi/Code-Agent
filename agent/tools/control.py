"""Agent 控制工具：迭代管理、skill 激活。"""

from __future__ import annotations

from agent.tools import ToolResult, tool


@tool
def extend_iterations(reason: str) -> ToolResult:
    """当前任务需要更多步骤时，请求延长迭代上限。

    reason: 简要说明为什么需要更多步骤
    """
    from agent.loop import request_extend
    request_extend()
    return ToolResult(True, f"Iterations extended. Reason: {reason}")


@tool
def use_skill(name: str) -> ToolResult:
    """当用户的请求匹配某个 skill 的触发条件时，调用此工具激活该 skill 工作流。激活后按返回的工作流步骤执行。

    name: skill 名称（如 frontend、backend、review、test、fix 等）
    """
    from agent.skills import get_skill, set_auto_approve
    skill = get_skill(name)
    if not skill:
        return ToolResult(False, f"Error: unknown skill '{name}'")
    if skill.auto_approve:
        set_auto_approve(True)
    workflow = skill.prompt_template.replace("{args}", "(见用户原始请求)")
    return ToolResult(True, f"⚡ Skill [{skill.name}] activated — {skill.description}\n\n{workflow}")
