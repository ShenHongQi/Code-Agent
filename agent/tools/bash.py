"""bash 工具：在工作区内执行 shell 命令。"""

from __future__ import annotations
import os
import signal
import subprocess
import threading

from agent.tools import tool, ToolResult
from agent.workspace import Workspace
from agent.permission import check_permission, PermissionDenied

_workspace: Workspace | None = None

DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 600
MAX_OUTPUT = 64 * 1024  # 64KB


def init(workspace: Workspace) -> None:
    global _workspace
    _workspace = workspace


def _drain(pipe, buffer: list[bytes], limit: int) -> None:
    """在独立线程中持续读取管道，防止缓冲区写满阻塞子进程。"""
    total = 0
    while True:
        chunk = pipe.read(4096)
        if not chunk:
            break
        total += len(chunk)
        if total <= limit:
            buffer.append(chunk)


@tool
def bash(command: str, timeout: int = 120) -> ToolResult:
    """在工作区目录下执行 shell 命令并返回输出。

    command: 要执行的完整 shell 命令
    timeout: 超时秒数（默认 120，最大 600）
    """
    assert _workspace
    timeout = min(max(timeout, 1), MAX_TIMEOUT)

    try:
        check_permission(command)
    except PermissionDenied as e:
        return ToolResult(False, f"Permission denied: {e}")

    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(_workspace.root),
            start_new_session=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
    except Exception as e:
        return ToolResult(False, f"Error starting process: {e}")

    buffer: list[bytes] = []
    reader = threading.Thread(target=_drain, args=(proc.stdout, buffer, MAX_OUTPUT))
    reader.daemon = True
    reader.start()

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            pass
        proc.kill()
        reader.join(timeout=2)
        output = b"".join(buffer).decode("utf-8", errors="replace")
        return ToolResult(
            False,
            f"Error: Command timed out after {timeout}s.\n"
            f"Partial output:\n{_truncate(output)}"
        )

    reader.join(timeout=5)
    output = b"".join(buffer).decode("utf-8", errors="replace")
    code = proc.returncode

    truncated = _truncate(output)
    if code == 0:
        return ToolResult(True, truncated if truncated else "(no output)")
    else:
        return ToolResult(False, f"Exit code {code}:\n{truncated}")


def _truncate(output: str) -> str:
    if len(output) <= MAX_OUTPUT:
        return output
    head_size = MAX_OUTPUT // 2
    tail_size = MAX_OUTPUT // 2
    head = output[:head_size]
    tail = output[-tail_size:]
    omitted = len(output) - head_size - tail_size
    return f"{head}\n\n... ({omitted} bytes omitted) ...\n\n{tail}"
