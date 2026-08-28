"""todo_write 工具：多步任务的显式计划。"""

from __future__ import annotations

from agent.tools import tool, ToolResult

_todos: list[dict[str, str]] = []


@tool
def todo_write(todos: str) -> ToolResult:
    """记录或更新多步任务计划，帮助追踪进度。每行一个步骤，用 [ ] 或 [x] 标记完成状态。

    todos: 多行文本，每行格式为 "[ ] 步骤描述" 或 "[x] 已完成步骤"
    """
    global _todos
    _todos = []
    for line in todos.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        done = line.startswith("[x]") or line.startswith("[X]")
        text = line.lstrip("[xX] ").strip()
        if text:
            _todos.append({"text": text, "done": "yes" if done else "no"})

    display = []
    for item in _todos:
        mark = "✓" if item["done"] == "yes" else "○"
        display.append(f"  {mark} {item['text']}")
    return ToolResult(True, f"Todo updated ({len(_todos)} items):\n" + "\n".join(display))


def get_todos() -> list[dict[str, str]]:
    return _todos
