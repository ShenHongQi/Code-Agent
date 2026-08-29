"""bash 工具：在工作区内执行 shell 命令。"""

from __future__ import annotations

from agent.permission import PermissionDenied, check_permission
from agent.shell import MAX_TIMEOUT, ShellRunner
from agent.tools import ToolResult, tool
from agent.workspace import Workspace

_runner: ShellRunner | None = None


def init(workspace: Workspace) -> None:
    global _runner
    _runner = ShellRunner(str(workspace.root))


@tool
def bash(command: str, timeout: int = 120) -> ToolResult:
    """在工作区目录下执行 shell 命令并返回输出。

    command: 要执行的完整 shell 命令
    timeout: 超时秒数（默认 120，最大 600）
    """
    assert _runner
    timeout = min(max(timeout, 1), MAX_TIMEOUT)

    try:
        check_permission(command)
    except PermissionDenied as e:
        return ToolResult(False, f"Permission denied: {e}")

    result = _runner.run(command, timeout=timeout)

    if result.timed_out:
        return ToolResult(
            False,
            f"Error: Command timed out after {timeout}s.\n"
            f"Partial output:\n{result.output}",
        )
    if result.exit_code == 0:
        return ToolResult(True, result.output or "(no output)")
    return ToolResult(False, f"Exit code {result.exit_code}:\n{result.output}")
