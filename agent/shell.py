"""ShellRunner：超时、进程组 kill、有界输出。

留出 Sandbox 接缝——run(cmd) -> Result 协议，
后续可在不改调用方的前提下接入容器执行。
"""

from __future__ import annotations
import os
import signal
import subprocess
import threading
from dataclasses import dataclass


DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 600
MAX_OUTPUT = 64 * 1024  # 64KB


@dataclass
class ShellResult:
    exit_code: int
    output: str
    timed_out: bool = False


class ShellRunner:
    """在指定 cwd 下执行 shell 命令。

    设计要点（§6.3）：
    - stdin=DEVNULL: 防 npm init 等交互命令挂死
    - start_new_session: 超时后 killpg 整棵进程树
    - stderr=STDOUT + 有界 drain: 防管道缓冲写满阻塞
    - 输出封顶 64KB (head+tail)
    """

    def __init__(self, cwd: str):
        self.cwd = cwd

    def run(self, command: str, timeout: int = DEFAULT_TIMEOUT) -> ShellResult:
        timeout = min(max(timeout, 1), MAX_TIMEOUT)

        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=self.cwd,
                start_new_session=True,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
        except Exception as e:
            return ShellResult(exit_code=-1, output=f"Failed to start: {e}")

        buffer: list[bytes] = []
        reader = threading.Thread(
            target=self._drain, args=(proc.stdout, buffer, MAX_OUTPUT)
        )
        reader.daemon = True
        reader.start()

        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except OSError:
                pass
            proc.kill()

        reader.join(timeout=5)
        output = b"".join(buffer).decode("utf-8", errors="replace")
        output = self._truncate(output)

        return ShellResult(
            exit_code=proc.returncode if not timed_out else -1,
            output=output,
            timed_out=timed_out,
        )

    @staticmethod
    def _drain(pipe, buffer: list[bytes], limit: int) -> None:
        total = 0
        while True:
            chunk = pipe.read(4096)
            if not chunk:
                break
            total += len(chunk)
            if total <= limit:
                buffer.append(chunk)

    @staticmethod
    def _truncate(output: str) -> str:
        if len(output) <= MAX_OUTPUT:
            return output
        head_size = MAX_OUTPUT // 2
        tail_size = MAX_OUTPUT // 2
        head = output[:head_size]
        tail = output[-tail_size:]
        omitted = len(output) - head_size - tail_size
        return f"{head}\n\n... ({omitted} bytes omitted) ...\n\n{tail}"
