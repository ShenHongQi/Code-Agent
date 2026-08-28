"""文件系统工具：read_file / write_file / edit_file。"""

from __future__ import annotations
from pathlib import Path

from agent.tools import tool, ToolResult
from agent.workspace import Workspace, FileRegistry, WorkspaceError

_workspace: Workspace | None = None
_registry: FileRegistry | None = None


def init(workspace: Workspace, registry: FileRegistry) -> None:
    global _workspace, _registry
    _workspace = workspace
    _registry = registry


@tool
def read_file(path: str, offset: int = 0, limit: int = 2000) -> ToolResult:
    """读取工作区内的文本文件，返回带行号的内容。

    path: 相对于工作区根目录的文件路径
    offset: 起始行号（从 0 开始）
    limit: 最多读取的行数（默认 2000）
    """
    assert _workspace and _registry
    try:
        resolved = _workspace.resolve(path)
        _workspace.check_sensitive(resolved)
    except WorkspaceError as e:
        return ToolResult(False, f"Error: {e}")

    if not resolved.is_file():
        return ToolResult(False, f"Error: '{path}' is not a file or does not exist.")

    try:
        raw = resolved.read_bytes()
        content = raw.decode("utf-8", errors="replace")
    except Exception as e:
        return ToolResult(False, f"Error reading file: {e}")

    _registry.register_read(resolved, raw)

    lines = content.split("\n")
    total = len(lines)
    selected = lines[offset: offset + limit]

    numbered = []
    for i, line in enumerate(selected, start=offset):
        numbered.append(f"{i:>5} | {line}")

    result = "\n".join(numbered)
    if offset + limit < total:
        result += f"\n\n... ({total - offset - limit} more lines. Use offset={offset + limit} to continue)"

    header = f"[{path}] {total} lines total, showing {offset}-{min(offset + limit, total) - 1}"
    return ToolResult(True, f"{header}\n{result}")


@tool
def write_file(path: str, content: str) -> ToolResult:
    """创建新文件或覆盖已有文件（仅用于新建文件；已存在的文件请用 edit_file）。

    path: 相对于工作区根目录的文件路径
    content: 要写入的完整文件内容
    """
    assert _workspace and _registry
    try:
        resolved = _workspace.resolve(path)
        _workspace.check_sensitive(resolved)
    except WorkspaceError as e:
        return ToolResult(False, f"Error: {e}")

    if resolved.exists():
        return ToolResult(
            False,
            f"Error: '{path}' already exists. Use edit_file to modify existing files, "
            f"or delete it first with bash if you need to rewrite completely."
        )

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        raw = content.encode("utf-8")
        resolved.write_bytes(raw)
        _registry.update_after_write(resolved, raw)
    except Exception as e:
        return ToolResult(False, f"Error writing file: {e}")

    lines = content.count("\n") + 1
    return ToolResult(True, f"Created '{path}' ({lines} lines)")


@tool
def edit_file(path: str, old_string: str, new_string: str) -> ToolResult:
    """精确字符串替换编辑文件。old_string 必须在文件中恰好出现一次。

    path: 相对于工作区根目录的文件路径
    old_string: 要被替换的精确字符串（必须唯一出现）
    new_string: 替换后的新字符串
    """
    assert _workspace and _registry
    try:
        resolved = _workspace.resolve(path)
        _workspace.check_sensitive(resolved)
    except WorkspaceError as e:
        return ToolResult(False, f"Error: {e}")

    if not resolved.is_file():
        return ToolResult(False, f"Error: '{path}' does not exist. Use write_file to create new files.")

    freshness = _registry.check_freshness(resolved)
    if freshness:
        return ToolResult(False, f"Error: {freshness}")

    try:
        raw = resolved.read_bytes()
        content = raw.decode("utf-8", errors="replace")
    except Exception as e:
        return ToolResult(False, f"Error reading file: {e}")

    count = content.count(old_string)
    if count == 0:
        return ToolResult(
            False,
            f"Error: The specified old_string was not found in '{path}' (0 occurrences). "
            f"Please read_file first to verify the exact content including whitespace and indentation."
        )
    if count > 1:
        return ToolResult(
            False,
            f"Error: old_string appears {count} times in '{path}'. "
            f"Please provide a more specific (longer) string that occurs exactly once."
        )

    new_content = content.replace(old_string, new_string, 1)
    new_raw = new_content.encode("utf-8")
    resolved.write_bytes(new_raw)
    _registry.update_after_write(resolved, new_raw)

    old_lines = old_string.count("\n") + 1
    new_lines = new_string.count("\n") + 1
    return ToolResult(True, f"Edited '{path}': replaced {old_lines} lines with {new_lines} lines")
