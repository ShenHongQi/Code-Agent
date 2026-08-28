"""批量编辑与差异查看工具。"""

from __future__ import annotations
import json
import subprocess

from agent.tools import tool, ToolResult
from agent.workspace import Workspace, FileRegistry, WorkspaceError

_workspace: Workspace | None = None
_registry: FileRegistry | None = None


def init(workspace: Workspace, registry: FileRegistry) -> None:
    global _workspace, _registry
    _workspace = workspace
    _registry = registry


@tool
def multi_edit(path: str, edits: str) -> ToolResult:
    """对一个文件执行多处非重叠的精确替换，原子操作。

    path: 相对于工作区根目录的文件路径
    edits: JSON 数组，每项为 {"old": "原文", "new": "替换文"}
    """
    assert _workspace and _registry
    try:
        resolved = _workspace.resolve(path)
        _workspace.check_sensitive(resolved)
    except WorkspaceError as e:
        return ToolResult(False, f"Error: {e}")

    if not resolved.is_file():
        return ToolResult(False, f"Error: '{path}' does not exist.")

    freshness = _registry.check_freshness(resolved)
    if freshness:
        return ToolResult(False, f"Error: {freshness}")

    # Parse edits JSON
    try:
        edit_list = json.loads(edits)
    except json.JSONDecodeError as e:
        return ToolResult(False, f"Error: Invalid JSON in edits: {e}")

    if not isinstance(edit_list, list) or not edit_list:
        return ToolResult(False, "Error: edits must be a non-empty JSON array.")

    # Validate each edit
    for i, edit in enumerate(edit_list):
        if not isinstance(edit, dict) or "old" not in edit or "new" not in edit:
            return ToolResult(False, f"Error: edit[{i}] must have 'old' and 'new' keys.")

    # Read file
    try:
        content = resolved.read_text(encoding="utf-8")
    except Exception as e:
        return ToolResult(False, f"Error reading file: {e}")

    # Validate all old strings exist exactly once and don't overlap
    positions: list[tuple[int, int, str]] = []
    for i, edit in enumerate(edit_list):
        old = edit["old"]
        count = content.count(old)
        if count == 0:
            return ToolResult(False, f"Error: edit[{i}].old not found in file.")
        if count > 1:
            return ToolResult(False, f"Error: edit[{i}].old appears {count} times (must be unique).")
        start = content.index(old)
        positions.append((start, start + len(old), edit["new"]))

    # Check for overlaps
    positions.sort(key=lambda x: x[0])
    for i in range(len(positions) - 1):
        if positions[i][1] > positions[i + 1][0]:
            return ToolResult(False, "Error: edits overlap in the file.")

    # Apply in reverse order to preserve positions
    result = content
    for start, end, new_text in reversed(positions):
        result = result[:start] + new_text + result[end:]

    # Write atomically
    new_raw = result.encode("utf-8")
    resolved.write_bytes(new_raw)
    _registry.update_after_write(resolved, new_raw)

    return ToolResult(True, f"Applied {len(edit_list)} edits to '{path}'")


@tool
def view_diff(path: str = ".") -> ToolResult:
    """查看工作区的 git diff（未暂存的更改）。

    path: 文件路径或 "." 查看所有更改
    """
    assert _workspace
    cmd = ["git", "diff", "--stat"]
    if path != ".":
        try:
            resolved = _workspace.resolve(path)
            cmd = ["git", "diff", str(resolved)]
        except WorkspaceError as e:
            return ToolResult(False, f"Error: {e}")
    else:
        cmd.append("--")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(_workspace.root),
            timeout=30,
        )
        output = result.stdout
        if not output.strip():
            return ToolResult(True, "(no changes)")
        # 限制输出大小
        if len(output) > 32000:
            output = output[:32000] + "\n... (truncated)"
        return ToolResult(True, output)
    except subprocess.TimeoutExpired:
        return ToolResult(False, "Error: git diff timed out.")
    except FileNotFoundError:
        return ToolResult(False, "Error: git not found.")
