"""记忆管理工具：跨会话持久化知识。"""

from __future__ import annotations
from agent.tools import tool, ToolResult
from agent.memory import MemoryManager

_memory_mgr: MemoryManager | None = None


def init(memory_mgr: MemoryManager) -> None:
    global _memory_mgr
    _memory_mgr = memory_mgr


@tool
def memory_write(content: str, scope: str = "project") -> ToolResult:
    """保存信息到记忆中，供后续会话使用。

    content: 要记住的内容
    scope: "project"（当前项目）或 "global"（全局偏好）
    """
    if not _memory_mgr:
        return ToolResult(False, "Error: Memory system not initialized.")
    if scope not in ("project", "global"):
        return ToolResult(False, "Error: scope must be 'project' or 'global'.")
    _memory_mgr.append(content, scope)
    return ToolResult(True, f"已保存到{scope}记忆: {content}")


@tool
def memory_read(scope: str = "project") -> ToolResult:
    """读取当前记忆内容。

    scope: "project"（当前项目）或 "global"（全局）
    """
    if not _memory_mgr:
        return ToolResult(False, "Error: Memory system not initialized.")
    content = _memory_mgr.read(scope)
    if not content:
        return ToolResult(True, f"({scope} 记忆为空)")
    return ToolResult(True, content)


@tool
def memory_forget(keyword: str, scope: str = "project") -> ToolResult:
    """删除包含关键词的记忆条目。

    keyword: 要删除的记忆中包含的关键词
    scope: "project" 或 "global"
    """
    if not _memory_mgr:
        return ToolResult(False, "Error: Memory system not initialized.")
    removed = _memory_mgr.remove(keyword, scope)
    if removed:
        return ToolResult(True, f"已删除包含 '{keyword}' 的记忆条目。")
    return ToolResult(True, f"未找到包含 '{keyword}' 的记忆条目。")
