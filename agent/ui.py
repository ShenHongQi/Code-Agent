"""ANSI 流式渲染：终端 UI。"""

from __future__ import annotations
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


class UI:
    def __init__(self, stream: bool = True):
        self._stream = stream
        self._in_stream = False

    def user_prompt(self) -> None:
        sys.stdout.write(f"\n{BOLD}{GREEN}> {RESET}")
        sys.stdout.flush()

    def assistant_start(self) -> None:
        sys.stdout.write(f"\n{BOLD}{CYAN}⏺ Assistant{RESET}\n")
        sys.stdout.flush()
        self._in_stream = True

    def stream_token(self, token: str) -> None:
        if self._stream:
            sys.stdout.write(token)
            sys.stdout.flush()

    def assistant_end(self, content: str) -> None:
        if self._in_stream:
            if not self._stream and content:
                sys.stdout.write(content)
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._in_stream = False

    def tool_start(self, name: str, args_summary: str) -> None:
        sys.stdout.write(f"\n  {DIM}⏺ {name}({args_summary}){RESET}\n")
        sys.stdout.flush()

    def tool_result(self, ok: bool, summary: str) -> None:
        color = GREEN if ok else RED
        icon = "⎿" if ok else "✗"
        # Show first line as summary
        first_line = summary.split("\n")[0][:120]
        sys.stdout.write(f"    {color}{icon} {first_line}{RESET}\n")
        sys.stdout.flush()

    def error(self, msg: str) -> None:
        sys.stdout.write(f"\n{RED}Error: {msg}{RESET}\n")
        sys.stdout.flush()

    def info(self, msg: str) -> None:
        sys.stdout.write(f"{DIM}{msg}{RESET}\n")
        sys.stdout.flush()

    def warning(self, msg: str) -> None:
        sys.stdout.write(f"{YELLOW}{msg}{RESET}\n")
        sys.stdout.flush()

    def iteration_info(self, iteration: int, max_iter: int) -> None:
        sys.stdout.write(f"{DIM}[iteration {iteration}/{max_iter}]{RESET} ")
        sys.stdout.flush()
