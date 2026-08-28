"""ANSI 流式渲染：终端 UI + 脱敏过滤 + 动态状态指示器 + Markdown 渲染。"""

from __future__ import annotations
import os
import sys
import shutil
import threading
import time

from agent.markdown import StreamingMarkdownRenderer

# ANSI codes
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"

# 动态指示器帧（用于 Assistant 行）
SPIN_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def _build_redact_patterns() -> list[str]:
    """收集环境变量中可能是密钥的值，用于输出脱敏。"""
    patterns = []
    key = os.environ.get("AGENT_API_KEY", "")
    if key and len(key) >= 8:
        patterns.append(key)
    return patterns


class _StatusSpinner:
    """在 Assistant 行头部显示动态旋转指示器。

    渲染效果：
      ⠋ Assistant (thinking...)
    动态刷新星号部分，不换行，使用 \\r 覆写。
    当流内容开始后停止并清除该行，让位给内容输出。
    """

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._running = False
        self._stop_event = threading.Event()
        self._label = ""
        self._state = ""  # "thinking" | "streaming" | "tool"
        self._lock = threading.Lock()
        self._start_time = 0.0

    def start(self, label: str = "Assistant", state: str = "thinking") -> None:
        self._label = label
        self._state = state
        self._start_time = time.time()

        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def update_state(self, state: str) -> None:
        self._state = state
        self._start_time = time.time()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1)
            self._thread = None
        self._clear_line()

    def _animate(self) -> None:
        idx = 0
        while not self._stop_event.is_set():
            elapsed = time.time() - self._start_time
            frame = SPIN_FRAMES[idx % len(SPIN_FRAMES)]

            state_text = ""
            if self._state == "thinking":
                state_text = f" {DIM}({elapsed:.1f}s){RESET}"
            elif self._state == "tool":
                state_text = f" {DIM}(running tool...){RESET}"

            line = f"\r{BOLD}{CYAN}{frame} {self._label}{RESET}{state_text}  "

            with self._lock:
                sys.stdout.write(line)
                sys.stdout.flush()

            idx += 1
            time.sleep(0.08)

    def _clear_line(self) -> None:
        with self._lock:
            cols = shutil.get_terminal_size().columns
            sys.stdout.write("\r" + " " * cols + "\r")
            sys.stdout.flush()


class UI:
    def __init__(self, stream: bool = True):
        self._stream = stream
        self._in_stream = False
        self._first_token = False
        self._redact_patterns = _build_redact_patterns()
        self._status = _StatusSpinner()
        self._md_renderer: StreamingMarkdownRenderer | None = None
        self._has_content = False

    def _sanitize(self, text: str) -> str:
        """替换输出中的敏感信息。"""
        for pattern in self._redact_patterns:
            if pattern in text:
                text = text.replace(pattern, "[REDACTED]")
        return text

    def assistant_start(self) -> None:
        """模型开始响应：显示动态旋转指示器。"""
        self._in_stream = True
        self._first_token = True
        self._has_content = False
        self._md_renderer = StreamingMarkdownRenderer()
        self._status.start("Assistant", "thinking")

    def stream_token(self, token: str) -> None:
        """接收流式 token，渲染 Markdown 并输出。"""
        if not self._stream:
            return

        if self._first_token:
            self._first_token = False
            # 停止旋转指示器，打印 Assistant 标题行
            self._status.stop()
            sys.stdout.write(f"{BOLD}{CYAN}● Assistant{RESET}\n")
            sys.stdout.flush()

        # 通过 Markdown 渲染器处理
        token = self._sanitize(token)
        rendered = self._md_renderer.feed(token)
        if rendered:
            self._has_content = True
            sys.stdout.write(rendered)
            sys.stdout.flush()

    def assistant_end(self, content: str) -> None:
        """模型响应结束。"""
        self._status.stop()

        if self._in_stream:
            if self._first_token:
                # 没有任何 token（纯工具调用情况）
                self._first_token = False
            elif self._md_renderer:
                # 刷出 Markdown 渲染器剩余缓冲
                remaining = self._md_renderer.flush()
                if remaining:
                    sys.stdout.write(remaining)

            if not self._stream and content:
                # 非流式模式：一次性渲染完整内容
                from agent.markdown import render_markdown
                rendered = render_markdown(self._sanitize(content))
                sys.stdout.write(f"{BOLD}{CYAN}● Assistant{RESET}\n")
                sys.stdout.write(rendered)

            sys.stdout.write("\n")
            sys.stdout.flush()
            self._in_stream = False
            self._md_renderer = None

    def tool_start(self, name: str, args_summary: str) -> None:
        """工具开始执行。"""
        self._status.stop()
        args_summary = self._sanitize(args_summary)
        sys.stdout.write(f"\n  {DIM}⏺ {name}({args_summary}){RESET}\n")
        sys.stdout.flush()
        self._status.start("Assistant", "tool")

    def tool_result(self, ok: bool, summary: str) -> None:
        """工具执行结果。"""
        self._status.stop()
        color = GREEN if ok else RED
        icon = "⎿" if ok else "✗"
        first_line = self._sanitize(summary.split("\n")[0][:120])
        sys.stdout.write(f"    {color}{icon} {first_line}{RESET}\n")
        sys.stdout.flush()
        # 恢复思考状态
        self._status.start("Assistant", "thinking")

    def error(self, msg: str) -> None:
        self._status.stop()
        sys.stdout.write(f"\n{RED}Error: {msg}{RESET}\n")
        sys.stdout.flush()

    def info(self, msg: str) -> None:
        sys.stdout.write(f"{DIM}{msg}{RESET}\n")
        sys.stdout.flush()

    def warning(self, msg: str) -> None:
        self._status.stop()
        sys.stdout.write(f"{YELLOW}{msg}{RESET}\n")
        sys.stdout.flush()

    def iteration_info(self, iteration: int, max_iter: int) -> None:
        sys.stdout.write(f"{DIM}[iteration {iteration}/{max_iter}]{RESET} ")
        sys.stdout.flush()
