"""ANSI 流式渲染：终端 UI + 脱敏过滤 + 动态状态指示器 + Markdown 渲染。"""

from __future__ import annotations
import os
import sys
import shutil
import threading
import time

from agent.markdown import StreamingMarkdownRenderer, render_markdown

# ANSI codes
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
ORANGE = "\033[38;5;196m"
RED_ORANGE = "\033[38;5;160m"
YELLOW = "\033[33m"
RED = "\033[31m"
GREEN = "\033[32m"

# 动态指示器帧
SPIN_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

THINKING_MAX_LINES = 3


def _build_redact_patterns() -> list[str]:
    patterns = []
    key = os.environ.get("AGENT_API_KEY", "")
    if key and len(key) >= 8:
        patterns.append(key)
    return patterns


class _StatusSpinner:
    """在 Assistant 行显示动态旋转指示器。"""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._running = False
        self._stop_event = threading.Event()
        self._label = ""
        self._state = ""
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

            line = f"\r{BOLD}{ORANGE}{frame} {self._label}{RESET}{state_text}  "

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
        self._redact_patterns = _build_redact_patterns()
        self._status = _StatusSpinner()
        self._thinking_total_lines = 0

    def _sanitize(self, text: str) -> str:
        for pattern in self._redact_patterns:
            if pattern in text:
                text = text.replace(pattern, "[REDACTED]")
        return text

    # ─── 思考阶段 ─────────────────────────────────────────────────────

    def assistant_start(self) -> None:
        """模型开始响应：显示动态旋转指示器。"""
        self._status.start("Assistant", "thinking")

    def assistant_end(self) -> None:
        """模型响应结束：停止指示器。"""
        self._status.stop()

    def show_thinking(self, content: str, max_lines: int = THINKING_MAX_LINES) -> None:
        """显示中间思考内容：DIM 淡化 + 截断。"""
        if not content or not content.strip():
            return

        content = self._sanitize(content)
        lines = content.strip().split("\n")
        total = len(lines)
        self._thinking_total_lines += total

        # 截取前 max_lines 行
        display_lines = lines[:max_lines]

        sys.stdout.write(f"{DIM}💭 ")
        for i, line in enumerate(display_lines):
            # 截断过长行
            truncated = line[:100] + ("..." if len(line) > 100 else "")
            if i == 0:
                sys.stdout.write(f"{truncated}\n")
            else:
                sys.stdout.write(f"   {truncated}\n")

        if total > max_lines:
            hidden = total - max_lines
            sys.stdout.write(f"   ... (省略 {hidden} 行)\n")

        sys.stdout.write(RESET)
        sys.stdout.flush()

    def show_response(self, content: str) -> None:
        """显示最终回答：完整 Markdown 渲染，突出显示。"""
        if not content or not content.strip():
            return

        content = self._sanitize(content)
        sys.stdout.write(f"\n{BOLD}{ORANGE}● Assistant{RESET}\n")
        rendered = render_markdown(content)
        sys.stdout.write(rendered + "\n")
        sys.stdout.flush()

    def show_thinking_summary(self) -> None:
        """轮次结束后显示思考统计提示。"""
        if self._thinking_total_lines > THINKING_MAX_LINES:
            sys.stdout.write(
                f"\n{DIM}(中间思考共 {self._thinking_total_lines} 行, "
                f"/think 查看完整内容){RESET}\n"
            )
            sys.stdout.flush()
        self._thinking_total_lines = 0

    def show_full_thinking(self, thinking_log: list[str]) -> None:
        """展开显示完整中间思考（/think 命令触发）。"""
        if not thinking_log:
            sys.stdout.write(f"{DIM}(无中间思考记录){RESET}\n")
            sys.stdout.flush()
            return

        sys.stdout.write(f"\n{DIM}{'─' * 40}\n")
        sys.stdout.write(f"📝 完整中间思考 ({len(thinking_log)} 段)\n")
        sys.stdout.write(f"{'─' * 40}{RESET}\n\n")

        for i, block in enumerate(thinking_log, 1):
            sys.stdout.write(f"{DIM}[{i}] {block.strip()}{RESET}\n\n")

        sys.stdout.write(f"{DIM}{'─' * 40}{RESET}\n")
        sys.stdout.flush()

    # ─── 工具调用 ─────────────────────────────────────────────────────

    def tool_start(self, name: str, args_summary: str) -> None:
        self._status.stop()
        args_summary = self._sanitize(args_summary)
        sys.stdout.write(f"\n  {DIM}⏺ {name}({args_summary}){RESET}\n")
        sys.stdout.flush()

    def tool_result(self, ok: bool, summary: str) -> None:
        self._status.stop()
        color = GREEN if ok else RED
        icon = "⎿" if ok else "✗"
        first_line = self._sanitize(summary.split("\n")[0][:120])
        sys.stdout.write(f"    {color}{icon} {first_line}{RESET}\n")
        sys.stdout.flush()
        self._status.start("Assistant", "thinking")

    # ─── 会话重放 ─────────────────────────────────────────────────────

    def replay_history(self, messages: list[dict]) -> None:
        """DIM 样式重放历史消息到终端。"""
        sys.stdout.write(f"\n{DIM}{'─' * 50}\n")
        sys.stdout.write(f"  ⏪ 恢复会话历史\n")
        sys.stdout.write(f"{'─' * 50}{RESET}\n\n")

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")

            if role == "system":
                continue
            elif role == "user":
                # 截断到第一行
                first_line = content.split("\n")[0][:80]
                sys.stdout.write(f"{DIM}{ORANGE}> {first_line}{RESET}\n")
            elif role == "assistant":
                if content:
                    lines = content.strip().split("\n")
                    preview = lines[0][:100]
                    sys.stdout.write(f"{DIM}● {preview}")
                    if len(lines) > 1:
                        sys.stdout.write(f" (+{len(lines) - 1} lines)")
                    sys.stdout.write(f"{RESET}\n")
                # 显示工具调用
                tool_calls = msg.get("tool_calls", [])
                for tc in tool_calls:
                    func = tc.get("function", {})
                    name = func.get("name", "?")
                    sys.stdout.write(f"{DIM}  ⏺ {name}(...){RESET}\n")
            elif role == "tool":
                continue  # 不显示工具结果详情

        sys.stdout.write(f"\n{DIM}{'─' * 50}\n")
        sys.stdout.write(f"  ✅ 已恢复 ({len(messages)} 条消息)\n")
        sys.stdout.write(f"{'─' * 50}{RESET}\n\n")
        sys.stdout.flush()

    # ─── 通用消息 ─────────────────────────────────────────────────────

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
