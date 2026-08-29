"""搜索工具：glob / grep。"""

from __future__ import annotations

import re
from pathlib import Path

from agent.tools import ToolResult, tool
from agent.workspace import Workspace, WorkspaceError

_workspace: Workspace | None = None


def init(workspace: Workspace) -> None:
    global _workspace
    _workspace = workspace


@tool
def glob(pattern: str) -> ToolResult:
    """按 glob 模式列出工作区内匹配的文件路径，按修改时间排序。

    pattern: glob 模式（如 "src/**/*.py"、"*.md"）
    """
    assert _workspace
    root = _workspace.root
    try:
        matches = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception as e:
        return ToolResult(False, f"Error: {e}")

    cap = 200
    paths = []
    for p in matches[:cap]:
        if p.is_file():
            rel = _workspace.relative(p)
            paths.append(rel)

    if not paths:
        return ToolResult(True, f"No files match pattern '{pattern}'")

    result = "\n".join(paths)
    if len(matches) > cap:
        result += f"\n\n... ({len(matches) - cap} more matches truncated)"
    return ToolResult(True, f"{len(paths)} files:\n{result}")


@tool
def grep(pattern: str, path: str = ".", include: str = "") -> ToolResult:
    """在工作区内搜索匹配正则表达式的文件内容。

    pattern: 正则表达式模式
    path: 搜索起点路径（相对于工作区根，默认整个工作区）
    include: 文件名 glob 过滤（如 "*.py"）
    """
    assert _workspace
    try:
        resolved = _workspace.resolve(path)
    except WorkspaceError as e:
        return ToolResult(False, f"Error: {e}")

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return ToolResult(False, f"Error: Invalid regex: {e}")

    matches: list[str] = []
    cap = 100
    line_cap = 400

    def _search_file(fpath: Path) -> None:
        if len(matches) >= cap:
            return
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            return
        for i, line in enumerate(text.split("\n"), 1):
            if len(matches) >= cap:
                return
            if regex.search(line):
                rel = _workspace.relative(fpath)
                display = line[:line_cap]
                if len(line) > line_cap:
                    display += "..."
                matches.append(f"{rel}:{i}: {display}")

    if resolved.is_file():
        _search_file(resolved)
    else:
        for fpath in sorted(resolved.rglob("*")):
            if not fpath.is_file():
                continue
            if ".git" in fpath.parts:
                continue
            if include:
                if not fpath.match(include):
                    continue
            _search_file(fpath)

    if not matches:
        return ToolResult(True, f"No matches for pattern '{pattern}'")

    result = "\n".join(matches)
    if len(matches) >= cap:
        result += f"\n\n... (results capped at {cap} matches)"
    return ToolResult(True, f"{len(matches)} matches:\n{result}")
