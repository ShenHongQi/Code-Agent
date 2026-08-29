"""终端 UI：基于 Rich 的流式渲染、工具展示、状态指示。

设计参考：
- OpenCode 的彩色左边框角色标识
- Rich Panel/Syntax/Markdown 组件
- 流式输出保持自定义增量渲染器（性能优先）
"""

from __future__ import annotations
import os
import sys
import shutil
import threading
import time
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.text import Text

from agent.markdown import StreamingMarkdownRenderer, render_markdown
from agent.theme import (
    MEGUMIN_THEME, ACCENT, ACCENT_DIM, ACCENT_BRIGHT,
    MUTED, SUCCESS, ERROR, WARNING, INFO,
    RESET, BOLD, DIM, ORANGE,
)

THINKING_MAX_LINES = 3

# ─── 流式输出用的轻量 ANSI 常量 ─────────────────────────────────────
_STREAM_HEADER = f"\n{BOLD}\033[38;5;208m◆ Assistant{RESET}\n"


def _build_redact_patterns() -> list[str]:
    patterns = []
    key = os.environ.get("AGENT_API_KEY", "")
    if key and len(key) >= 8:
        patterns.append(key)
    return patterns


class UI:
    def __init__(self, stream: bool = True):
        self._stream = stream
        self._redact_patterns = _build_redact_patterns()
        self._thinking_total_lines = 0
        self._console = Console(theme=MEGUMIN_THEME, highlight=False)
        self._streaming_active = False
        self._md_renderer: StreamingMarkdownRenderer | None = None
        self._status_active = False
        self._status_thread: threading.Thread | None = None
        self._status_stop = threading.Event()
        self._status_label = ""
        self._status_start_time = 0.0

    def _sanitize(self, text: str) -> str:
        for pattern in self._redact_patterns:
            if pattern in text:
                text = text.replace(pattern, "[REDACTED]")
        return text

    # ─── Spinner 状态指示 ─────────────────────────────────────────────

    def _start_spinner(self, label: str = "thinking") -> None:
        if self._status_thread and self._status_thread.is_alive():
            self._status_label = label
            self._status_start_time = time.time()
            return
        self._status_label = label
        self._status_start_time = time.time()
        self._status_stop.clear()
        self._status_active = True
        self._status_thread = threading.Thread(target=self._spin_loop, daemon=True)
        self._status_thread.start()

    def _stop_spinner(self) -> None:
        if not self._status_active:
            return
        self._status_active = False
        self._status_stop.set()
        if self._status_thread:
            self._status_thread.join(timeout=1)
            self._status_thread = None
        cols = shutil.get_terminal_size().columns
        sys.stdout.write("\r" + " " * cols + "\r")
        sys.stdout.flush()

    def _spin_loop(self) -> None:
        frames = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"]
        idx = 0
        while not self._status_stop.is_set():
            elapsed = time.time() - self._status_start_time
            frame = frames[idx % len(frames)]
            label = self._status_label
            line = f"\r\033[38;5;208m{frame}\033[0m \033[2m{label} ({elapsed:.1f}s)\033[0m   "
            sys.stdout.write(line)
            sys.stdout.flush()
            idx += 1
            time.sleep(0.08)

    # ─── 思考阶段 ─────────────────────────────────────────────────────

    def assistant_start(self) -> None:
        self._streaming_active = False
        self._md_renderer = None
        self._start_spinner("thinking")

    def assistant_end(self) -> None:
        self._stop_spinner()
        if self._streaming_active and self._md_renderer:
            tail = self._md_renderer.flush()
            if tail:
                sys.stdout.write(tail)
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._streaming_active = False

    def stream_token(self, token: str) -> None:
        if not self._stream:
            return
        if not self._streaming_active:
            self._stop_spinner()
            sys.stdout.write(_STREAM_HEADER)
            sys.stdout.flush()
            self._md_renderer = StreamingMarkdownRenderer()
            self._streaming_active = True
        rendered = self._md_renderer.feed(token)
        if rendered:
            sys.stdout.write(rendered)
            sys.stdout.flush()

    def show_thinking(self, content: str, max_lines: int = THINKING_MAX_LINES) -> None:
        if not content or not content.strip():
            return
        content = self._sanitize(content)
        lines = content.strip().split("\n")
        total = len(lines)
        self._thinking_total_lines += total

        display = lines[:max_lines]
        text = Text()
        text.append("💭 ", style="dim")
        for i, line in enumerate(display):
            truncated = line[:120] + ("…" if len(line) > 120 else "")
            if i > 0:
                text.append("\n   ")
            text.append(truncated, style="thinking")
        if total > max_lines:
            text.append(f"\n   … (省略 {total - max_lines} 行)", style="dim")
        self._console.print(text)

    def show_response(self, content: str) -> None:
        if not content or not content.strip():
            return
        content = self._sanitize(content)
        # 用 Rich Panel + 橙色左边框（参考 OpenCode 风格）
        rendered = render_markdown(content)
        panel = Panel(
            rendered,
            title="[bold]◆ Assistant[/bold]",
            title_align="left",
            border_style=ACCENT,
            padding=(0, 1),
        )
        self._console.print()
        self._console.print(panel)

    def show_thinking_summary(self) -> None:
        if self._thinking_total_lines > THINKING_MAX_LINES:
            self._console.print(
                f"[muted](中间思考共 {self._thinking_total_lines} 行, "
                f"/think 查看完整内容)[/muted]"
            )
        self._thinking_total_lines = 0

    def show_full_thinking(self, thinking_log: list[str]) -> None:
        if not thinking_log:
            self._console.print("[muted](无中间思考记录)[/muted]")
            return
        self._console.print()
        self._console.print(Rule("📝 完整中间思考", style="muted"))
        for i, block in enumerate(thinking_log, 1):
            self._console.print(f"[muted]\\[{i}] {escape(block.strip())}[/muted]\n")
        self._console.print(Rule(style="muted"))

    # ─── 工具调用 ─────────────────────────────────────────────────────

    def tool_start(self, name: str, args_summary: str) -> None:
        self._stop_spinner()
        args_summary = self._sanitize(args_summary)
        text = Text()
        text.append("  ⏺ ", style=ACCENT_DIM)
        text.append(name, style=f"bold {ACCENT_DIM}")
        if args_summary:
            display_args = args_summary[:80] + ("…" if len(args_summary) > 80 else "")
            text.append(f"  {display_args}", style=MUTED)
        self._console.print(text)

    def tool_result(self, ok: bool, summary: str) -> None:
        self._stop_spinner()
        icon = "⎿" if ok else "✗"
        style = SUCCESS if ok else ERROR
        first_line = self._sanitize(summary.split("\n")[0][:120])
        text = Text()
        text.append(f"    {icon} ", style=style)
        text.append(first_line, style=style if not ok else "default")
        self._console.print(text)
        self._start_spinner("thinking")

    # ─── 会话重放 ─────────────────────────────────────────────────────

    def replay_history(self, messages: list[dict]) -> None:
        self._console.print()
        self._console.print(Rule("⏪ 恢复会话历史", style=ACCENT_DIM))
        self._console.print()

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")

            if role == "system":
                continue
            elif role == "user":
                first_line = content.split("\n")[0][:80]
                self._console.print(f"  [accent]>[/accent] [muted]{escape(first_line)}[/muted]")
            elif role == "assistant":
                if content:
                    lines = content.strip().split("\n")
                    preview = lines[0][:100]
                    extra = f" (+{len(lines) - 1} lines)" if len(lines) > 1 else ""
                    self._console.print(f"  [muted]◆ {escape(preview)}{extra}[/muted]")
                for tc in msg.get("tool_calls", []):
                    name = tc.get("function", {}).get("name", "?")
                    self._console.print(f"    [muted]⏺ {name}(…)[/muted]")
            elif role == "tool":
                continue

        self._console.print()
        self._console.print(
            f"  [success]✅ 已恢复 ({len(messages)} 条消息)[/success]"
        )
        self._console.print(Rule(style=ACCENT_DIM))
        self._console.print()

    # ─── 通用消息 ─────────────────────────────────────────────────────

    def error(self, msg: str) -> None:
        self._stop_spinner()
        self._console.print(f"\n[error]Error: {escape(msg)}[/error]")

    def info(self, msg: str) -> None:
        self._console.print(f"[muted]{escape(msg)}[/muted]")

    def warning(self, msg: str) -> None:
        self._stop_spinner()
        self._console.print(f"[warning]{escape(msg)}[/warning]")

    def iteration_info(self, iteration: int, max_iter: int) -> None:
        self._console.print(f"[muted]\\[iteration {iteration}/{max_iter}][/muted]", end=" ")
