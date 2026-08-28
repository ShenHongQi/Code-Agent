"""System prompt 与 subagent prompt。"""

from __future__ import annotations
import os
from pathlib import Path


SYSTEM_PROMPT_TEMPLATE = """\
You are a coding agent. You help the user accomplish programming tasks by reading \
files, writing code, and executing commands in the workspace.

## Workspace
- Root: {workspace_root}
{workspace_tree}

## Rules
- Always work within the workspace directory.
- Read files before editing them — edit_file requires an exact unique match.
- Use edit_file for modifying existing files; use write_file only for creating new files.
- Run tests after making changes when possible.
- Be concise in explanations; let code speak for itself.
- If a task requires multiple steps, use todo_write to plan them out.
- Use task to delegate read-only exploration to a sub-agent when it would generate too much context.

## Available tools
read_file, write_file, edit_file, glob, grep, bash, todo_write, task
"""

SUBAGENT_PROMPT = """\
You are a research sub-agent. Your job is to explore the codebase and report findings.
You have READ-ONLY access: read_file, glob, grep, and bash (read-only commands only).
You CANNOT write or edit files.
Be thorough but concise. Report your findings as your final message — that text is \
returned to the parent agent as the tool result.
"""


def build_system_prompt(workspace_root: str) -> str:
    """构建动态 system prompt，注入工作区路径和顶层文件结构。"""
    root = Path(workspace_root)
    tree_lines = []
    try:
        entries = sorted(root.iterdir())
        for entry in entries[:30]:
            if entry.name.startswith("."):
                continue
            prefix = "📁" if entry.is_dir() else "📄"
            tree_lines.append(f"  {prefix} {entry.name}")
        if len(entries) > 30:
            tree_lines.append(f"  ... ({len(entries) - 30} more)")
    except OSError:
        tree_lines.append("  (unable to list)")

    tree_str = "\n".join(tree_lines) if tree_lines else "  (empty)"
    return SYSTEM_PROMPT_TEMPLATE.format(
        workspace_root=workspace_root,
        workspace_tree=tree_str,
    )

