"""ANSI 流式渲染：终端 UI + 脱敏过滤 + Spinner 协调。"""

from __future__ import annotations
import os
import sys


# ANSI codes
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"


def _build_redact_patterns() -> list[str]:
    """收集环境变量中可能是密钥的值，用于输出脱敏。"""
    patterns = []
    key = os.environ.get("AGENT_API_KEY", "")
    if key and len(key) >= 8:
        patterns.append(key)
    return patterns


class UI:
    def __init__(self, stream: bool = True):
        self._stream = stream
        self._in_stream = False
        self._first_token = False
        self._redact_patterns = _build_redact_patterns()
        self._spinner = None

    def set_spinner(self, spinner) -> None:
        self._spinner = spinner

    def _sanitize(self, text: str) -> str:
        """替换输出中的敏感信息。"""
        for pattern in self._redact_patterns:
            if pattern in text:
                text = text.replace(pattern, "[REDACTED]")
        return text

    def user_prompt(self) -> None:
        sys.stdout.write(f"\n{BOLD}{GREEN}> {RESET}")
        sys.stdout.flush()

    def assistant_start(self) -> None:
        sys.stdout.write(f"{BOLD}{CYAN}⏺ Assistant{RESET}\n")
        sys.stdout.flush()
        self._in_stream = True
        self._first_token = True
        if self._spinner:
            self._spinner.start("Thinking...")

    def stream_token(self, token: str) -> None:
        if self._stream:
            if self._first_token:
                self._first_token = False
                if self._spinner:
                    self._spinner.pause()
            sys.stdout.write(self._sanitize(token))
            sys.stdout.flush()

    def assistant_end(self, content: str) -> None:
        if self._spinner:
            self._spinner.stop()
        if self._in_stream:
            if not self._stream and content:
                sys.stdout.write(self._sanitize(content))
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._in_stream = False

    def tool_start(self, name: str, args_summary: str) -> None:
        if self._spinner:
            self._spinner.pause()
        args_summary = self._sanitize(args_summary)
        sys.stdout.write(f"\n  {DIM}⏺ {name}({args_summary}){RESET}\n")
        sys.stdout.flush()
        if self._spinner:
            self._spinner.resume(f"Running {name}...")

    def tool_result(self, ok: bool, summary: str) -> None:
        if self._spinner:
            self._spinner.pause()
        color = GREEN if ok else RED
        icon = "⎿" if ok else "✗"
        first_line = self._sanitize(summary.split("\n")[0][:120])
        sys.stdout.write(f"    {color}{icon} {first_line}{RESET}\n")
        sys.stdout.flush()
        if self._spinner:
            self._spinner.resume("Thinking...")

    def error(self, msg: str) -> None:
        if self._spinner:
            self._spinner.stop()
        sys.stdout.write(f"\n{RED}Error: {msg}{RESET}\n")
        sys.stdout.flush()

    def info(self, msg: str) -> None:
        sys.stdout.write(f"{DIM}{msg}{RESET}\n")
        sys.stdout.flush()

    def warning(self, msg: str) -> None:
        if self._spinner:
            self._spinner.stop()
        sys.stdout.write(f"{YELLOW}{msg}{RESET}\n")
        sys.stdout.flush()

    def iteration_info(self, iteration: int, max_iter: int) -> None:
        sys.stdout.write(f"{DIM}[iteration {iteration}/{max_iter}]{RESET} ")
        sys.stdout.flush()
