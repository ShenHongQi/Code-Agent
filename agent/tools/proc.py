"""后台进程管理：启动、查看状态、终止。"""

from __future__ import annotations
import atexit
import os
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from agent.tools import tool, ToolResult
from agent.workspace import Workspace
from agent.permission import check_permission, PermissionDenied

_workspace: Workspace | None = None
_processes: dict[str, "BackgroundProc"] = {}
_counter = 0


def init(workspace: Workspace) -> None:
    global _workspace
    _workspace = workspace
    atexit.register(_cleanup_all)


def _cleanup_all() -> None:
    for proc in list(_processes.values()):
        proc.kill()
    _processes.clear()


RING_BUFFER_SIZE = 32 * 1024  # 32KB


@dataclass
class BackgroundProc:
    pid: str
    label: str
    command: str
    process: subprocess.Popen
    started_at: float = field(default_factory=time.time)
    _buffer: deque = field(default_factory=lambda: deque(maxlen=512))
    _thread: threading.Thread | None = None

    def start_reader(self) -> None:
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def _read_loop(self) -> None:
        assert self.process.stdout
        while True:
            chunk = self.process.stdout.read(4096)
            if not chunk:
                break
            self._buffer.append(chunk.decode("utf-8", errors="replace"))

    @property
    def alive(self) -> bool:
        return self.process.poll() is None

    @property
    def output_tail(self) -> str:
        text = "".join(self._buffer)
        if len(text) > 4096:
            return "..." + text[-4096:]
        return text

    @property
    def exit_code(self) -> int | None:
        return self.process.poll()

    def kill(self) -> None:
        if self.alive:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except OSError:
                pass
            time.sleep(0.5)
            if self.alive:
                self.process.kill()


@tool
def spawn(command: str, label: str = "") -> ToolResult:
    """启动后台进程（dev server、watcher 等），返回进程 ID。

    command: 要在后台执行的 shell 命令
    label: 可选的进程标签
    """
    global _counter
    assert _workspace

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

    _counter += 1
    pid = f"bg_{_counter}"
    bp = BackgroundProc(pid=pid, label=label or command[:40], command=command, process=proc)
    bp.start_reader()
    _processes[pid] = bp

    return ToolResult(True, f"Started background process [{pid}]: {label or command[:60]}\nOS PID: {proc.pid}")


@tool
def proc_status(pid: str = "") -> ToolResult:
    """查看后台进程状态和最近输出。

    pid: 进程 ID（空则列出所有后台进程）
    """
    if not pid:
        if not _processes:
            return ToolResult(True, "(no background processes)")
        lines = []
        for p in _processes.values():
            status = "🟢 running" if p.alive else f"🔴 exited ({p.exit_code})"
            elapsed = time.time() - p.started_at
            lines.append(f"[{p.pid}] {status} ({elapsed:.0f}s) - {p.label}")
        return ToolResult(True, "\n".join(lines))

    bp = _processes.get(pid)
    if not bp:
        return ToolResult(False, f"Error: No process with ID '{pid}'. Use proc_status() to list all.")

    status = "running" if bp.alive else f"exited (code {bp.exit_code})"
    elapsed = time.time() - bp.started_at
    tail = bp.output_tail or "(no output yet)"

    return ToolResult(True, f"[{pid}] {status} | {elapsed:.0f}s | {bp.label}\n\nRecent output:\n{tail}")


@tool
def proc_kill(pid: str) -> ToolResult:
    """终止一个后台进程。

    pid: 要终止的进程 ID
    """
    bp = _processes.get(pid)
    if not bp:
        return ToolResult(False, f"Error: No process with ID '{pid}'.")

    if not bp.alive:
        del _processes[pid]
        return ToolResult(True, f"Process [{pid}] already exited (code {bp.exit_code}).")

    bp.kill()
    del _processes[pid]
    return ToolResult(True, f"Killed process [{pid}]: {bp.label}")
