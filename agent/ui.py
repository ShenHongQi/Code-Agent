"""终端 UI：基于 Rich 的流式渲染、工具展示、状态指示。

设计参考：OpenCode TUI — ThickBorder 左边框角色标识、动态宽度适配。
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
import time

from rich.console import Console
from rich.markup import escape
from rich.rule import Rule
from rich.text import Text

from agent.markdown import StreamingMarkdownRenderer, render_markdown
from agent.theme import (
    ANSI_PRIMARY,
    BOLD,
    DIM,
    ERROR,
    MEGUMIN_THEME,
    PRIMARY,
    RESET,
    SUCCESS,
    TEXT_MUTED,
)

THINKING_MAX_LINES = 3

# ThickBorder 左侧标识符（参考 OpenCode）
_THICK_BAR = "┃"
_STREAM_HEADER = f"\n{BOLD}{ANSI_PRIMARY}{_THICK_BAR} ◆ Assistant{RESET}\n"

# 工具执行时的 spinner 标签
TOOL_STATUS: dict[str, str] = {
    "read_file": "reading",
    "write_file": "writing",
    "edit_file": "editing",
    "multi_edit": "editing",
    "delete_file": "deleting",
    "rename_file": "renaming",
    "bash": "running",
    "spawn": "spawning",
    "glob": "searching",
    "grep": "searching",
    "web_fetch": "fetching",
    "task": "delegating",
    "list_dir": "listing",
    "view_diff": "diffing",
    "memory_read": "recalling",
    "memory_write": "memorizing",
    "todo_write": "planning",
    "proc_status": "checking",
    "proc_kill": "killing",
}


def _build_redact_patterns() -> list[str]:
    patterns = []
    key = os.environ.get("AGENT_API_KEY", "")
    if key and len(key) >= 8:
        patterns.append(key)
    return patterns


def _term_width() -> int:
    return shutil.get_terminal_size().columns


class UI:
    def __init__(self, stream: bool = True):
        self._stream = stream
        self._redact_patterns = _build_redact_patterns()
        self._thinking_total_lines = 0
        self._console = Console(theme=MEGUMIN_THEME, highlight=False)
        self._streaming_active = False
        self._md_renderer: StreamingMarkdownRenderer | None = None
        self._stream_full_text = ""
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
        cols = _term_width()
        sys.stdout.write("\r" + " " * cols + "\r")
        sys.stdout.flush()

    def _spin_loop(self) -> None:
        frames = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"]
        idx = 0
        while not self._status_stop.is_set():
            elapsed = time.time() - self._status_start_time
            frame = frames[idx % len(frames)]
            label = self._status_label
            line = f"\r{ANSI_PRIMARY}{frame}{RESET} {DIM}{label} ({elapsed:.1f}s){RESET}   "
            sys.stdout.write(line)
            sys.stdout.flush()
            idx += 1
            time.sleep(0.08)

    # ─── 思考阶段 ─────────────────────────────────────────────────────

    def assistant_start(self) -> None:
        self._streaming_active = False
        self._md_renderer = None
        self._stream_full_text = ""
        self._start_spinner("thinking")

    def assistant_end(self) -> None:
        self._stop_spinner()
        from agent.terminal import set_resize_stream_cb
        set_resize_stream_cb(None)
        if self._streaming_active and self._md_renderer:
            tail = self._md_renderer.flush()
            if tail:
                sys.stdout.write(tail)
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._streaming_active = False
        self._stream_full_text = ""

    def stream_token(self, token: str) -> None:
        if not self._stream:
            return
        if not self._streaming_active:
            self._stop_spinner()
            sys.stdout.write(_STREAM_HEADER)
            sys.stdout.flush()
            self._md_renderer = StreamingMarkdownRenderer()
            self._streaming_active = True
            from agent.terminal import set_resize_stream_cb
            set_resize_stream_cb(self._handle_stream_resize)
        self._stream_full_text += token
        rendered = self._md_renderer.feed(token)
        if rendered:
            sys.stdout.write(rendered)
            sys.stdout.flush()

    def _handle_stream_resize(self) -> None:
        """SIGWINCH 期间调用：用新宽度重新渲染已累积的流式内容。"""
        if not self._streaming_active or not self._stream_full_text:
            return
        sys.stdout.write(_STREAM_HEADER)
        # 批量渲染已累积的全部文本（新宽度）
        rendered = render_markdown(self._stream_full_text)
        sys.stdout.write(rendered)
        # 重建流式渲染器并静默回放，恢复内部状态以继续接收后续 token
        self._md_renderer = StreamingMarkdownRenderer()
        self._md_renderer.feed(self._stream_full_text)
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
        rendered = render_markdown(content)
        # OpenCode 风格：左侧 ThickBorder 标记 assistant 消息
        lines = rendered.split("\n")
        body = Text()
        for i, line in enumerate(lines):
            if i > 0:
                body.append("\n")
            body.append(f" {_THICK_BAR} ", style=f"bold {PRIMARY}")
            body.append(line)
        self._console.print()
        title = Text()
        title.append(f" {_THICK_BAR} ", style=f"bold {PRIMARY}")
        title.append("◆ Assistant", style=f"bold {PRIMARY}")
        self._console.print(title)
        self._console.print(body)

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
        text.append("  ⏺ ", style=TEXT_MUTED)
        text.append(name, style=f"bold {TEXT_MUTED}")
        if args_summary:
            display_args = args_summary[:80] + ("…" if len(args_summary) > 80 else "")
            text.append(f"  {display_args}", style=TEXT_MUTED)
        self._console.print(text)
        self._start_spinner(TOOL_STATUS.get(name, f"⚙ {name}"))

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

    def replay_history(self, messages: list[dict], model: str = "") -> None:
        """重放历史消息，完全还原对话时的视觉效果。"""

        if not model:
            from agent.config import config as _cfg
            model = _cfg.model

        tool_results: dict[str, str] = {}
        for msg in messages:
            if msg.get("role") == "tool":
                tool_results[msg.get("tool_call_id", "")] = msg.get("content", "")

        user_turns = sum(
            1 for m in messages
            if m.get("role") == "user" and not self._is_system_injected(m.get("content", ""))
        )
        self._console.print(f"\n[muted]↻ 恢复会话 ({user_turns} 轮对话)[/muted]")

        for i, msg in enumerate(messages):
            role = msg.get("role")
            content = msg.get("content", "")

            if role in ("system", "tool"):
                continue

            if role == "user":
                if self._is_system_injected(content):
                    continue
                self._replay_user_input(content, model)
                continue

            if role == "assistant":
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    if content:
                        self.show_thinking(content)
                    self._replay_tool_calls(tool_calls, tool_results)
                elif content:
                    is_intermediate = (
                        i + 1 < len(messages)
                        and messages[i + 1].get("role") == "user"
                        and self._is_system_injected(messages[i + 1].get("content", ""))
                    )
                    if is_intermediate:
                        self.show_thinking(content)
                    else:
                        self._replay_assistant_response(content)

        self._console.print()

    @staticmethod
    def _is_system_injected(content: str) -> bool:
        return (
            content.startswith("[System]")
            or content.startswith("## 🎯 自动目标模式")
            or content.startswith("## 📋 设计方案模式")
            or "用户已批准上述方案" in content[:50]
        )

    def _replay_user_input(self, content: str, model: str = "") -> None:
        content = self._sanitize(content)
        _BG = "\033[48;5;236m"
        sys.stdout.write("\n")
        for line in content.split("\n"):
            sys.stdout.write(f"{_BG} {BOLD}{ANSI_PRIMARY}>{RESET}{_BG} {line}\033[K{RESET}\n")
        sys.stdout.flush()

    def _replay_tool_calls(self, tool_calls: list[dict], tool_results: dict[str, str]) -> None:
        import json

        from agent.loop import _summarize_args

        for tc in tool_calls:
            func = tc.get("function", {})
            name = func.get("name", "?")
            args_str = func.get("arguments", "{}")
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
            except json.JSONDecodeError:
                args = {}
            summary = self._sanitize(_summarize_args(name, args))

            text = Text()
            text.append("  ⏺ ", style=TEXT_MUTED)
            text.append(name, style=f"bold {TEXT_MUTED}")
            if summary:
                display = summary[:80] + ("…" if len(summary) > 80 else "")
                text.append(f"  {display}", style=TEXT_MUTED)
            self._console.print(text)

            tc_id = tc.get("id", "")
            result_content = self._sanitize(tool_results.get(tc_id, ""))
            ok = not result_content.startswith("Error:")
            icon = "⎿" if ok else "✗"
            style = SUCCESS if ok else ERROR
            first_line = result_content.split("\n")[0][:120]
            text = Text()
            text.append(f"    {icon} ", style=style)
            text.append(first_line, style=style if not ok else "default")
            self._console.print(text)

    def _replay_assistant_response(self, content: str) -> None:
        content = self._sanitize(content)
        sys.stdout.write(_STREAM_HEADER)
        rendered = render_markdown(content)
        sys.stdout.write(rendered)
        sys.stdout.write("\n")
        sys.stdout.flush()

    # ─── Token 用量 ────────────────────────────────────────────────────

    @staticmethod
    def _fmt_tokens(n: int) -> str:
        if n >= 10_000:
            return f"{n / 1000:.0f}k"
        if n >= 1_000:
            return f"{n / 1000:.1f}k"
        return str(n)

    def show_usage(self, prompt_tokens: int, completion_tokens: int, context_limit: int) -> None:
        if not prompt_tokens:
            return
        pct = prompt_tokens / context_limit * 100 if context_limit else 0
        ctx_str = f"{self._fmt_tokens(prompt_tokens)}/{self._fmt_tokens(context_limit)}"
        self._console.print(
            f"[muted]  ctx {ctx_str} ({pct:.0f}%) · output {self._fmt_tokens(completion_tokens)}[/muted]"
        )

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
