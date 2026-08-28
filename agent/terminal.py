"""终端交互：readline 历史、Spinner 动画、ESC 检测。"""

from __future__ import annotations
import os
import sys
import shutil
import threading
import time
from pathlib import Path

HISTORY_FILE = Path.home() / ".megumin" / "history"
HISTORY_SIZE = 1000

# ANSI
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
CYAN = "\033[36m"
YELLOW = "\033[33m"


class EscInterrupt(Exception):
    """ESC 键触发的中断。"""
    pass


# ─── InputManager ───────────────────────────────────────────────────────────

class InputManager:
    """readline 集成 + 持久化历史 + 视觉化输入框。"""

    def __init__(self):
        self._readline_available = False
        self._setup_readline()

    def _setup_readline(self) -> None:
        try:
            import readline
            self._readline = readline

            # macOS libedit 兼容
            if "libedit" in (readline.__doc__ or ""):
                readline.parse_and_bind("bind ^I rl_complete")
            else:
                readline.parse_and_bind("tab: complete")

            readline.set_history_length(HISTORY_SIZE)

            # 加载历史
            if HISTORY_FILE.exists():
                readline.read_history_file(str(HISTORY_FILE))

            self._readline_available = True
        except (ImportError, OSError):
            self._readline = None

    def styled_input(self, prefill: str = "") -> str:
        """显示视觉化输入框并读取用户输入。"""
        width = min(shutil.get_terminal_size().columns, 60)
        bar = "─" * (width - 6)

        # 顶线
        sys.stdout.write(f"\n{BOLD}{GREEN}╭─ You {bar}{RESET}\n")
        sys.stdout.write(f"{BOLD}{GREEN}│{RESET} ")
        sys.stdout.flush()

        # 预填支持
        if prefill and self._readline_available:
            self._readline.set_startup_hook(lambda: self._readline.insert_text(prefill))

        try:
            user_input = input()
        finally:
            if self._readline_available:
                self._readline.set_startup_hook()

        # 底线
        sys.stdout.write(f"{BOLD}{GREEN}╰{bar}──────{RESET}\n")
        sys.stdout.flush()

        return user_input.strip()

    def save_history(self) -> None:
        if self._readline_available:
            try:
                HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
                self._readline.write_history_file(str(HISTORY_FILE))
                HISTORY_FILE.chmod(0o600)
            except OSError:
                pass


# ─── Spinner ────────────────────────────────────────────────────────────────

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class Spinner:
    """后台线程 spinner 动画，用 \\r 覆写当前行。"""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._running = False
        self._paused = threading.Event()
        self._stop_event = threading.Event()
        self._label = ""
        self._start_time = 0.0
        self._lock = threading.Lock()

    def start(self, label: str = "Thinking...") -> None:
        if self._thread and self._thread.is_alive():
            self.resume(label)
            return
        self._label = label
        self._start_time = time.time()
        self._running = True
        self._paused.clear()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def pause(self) -> None:
        """暂停 spinner 并清除其显示行。"""
        if not self._running:
            return
        self._paused.set()
        time.sleep(0.05)  # 等待渲染循环感知
        self._clear_line()

    def resume(self, label: str = "") -> None:
        if label:
            self._label = label
        self._start_time = time.time()
        self._paused.clear()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        self._paused.set()
        if self._thread:
            self._thread.join(timeout=1)
            self._thread = None
        self._clear_line()

    def _spin(self) -> None:
        idx = 0
        while not self._stop_event.is_set():
            if self._paused.is_set():
                time.sleep(0.05)
                continue
            elapsed = time.time() - self._start_time
            frame = SPINNER_FRAMES[idx % len(SPINNER_FRAMES)]
            text = f"\r{DIM}{frame} {self._label} ({elapsed:.1f}s){RESET}   "
            with self._lock:
                sys.stdout.write(text)
                sys.stdout.flush()
            idx += 1
            time.sleep(0.08)

    def _clear_line(self) -> None:
        with self._lock:
            cols = shutil.get_terminal_size().columns
            sys.stdout.write("\r" + " " * cols + "\r")
            sys.stdout.flush()


# ─── EscDetector ────────────────────────────────────────────────────────────

class EscDetector:
    """后台线程检测 ESC 按键（仅 Unix TTY）。"""

    def __init__(self):
        self.event = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self._old_settings = None
        self._available = (
            sys.stdin.isatty()
            and os.name != "nt"
            and hasattr(sys.stdin, "fileno")
        )

    def start(self) -> None:
        if not self._available:
            return
        import termios
        import tty

        self.event.clear()
        self._running = True
        try:
            self._old_settings = termios.tcgetattr(sys.stdin.fileno())
            tty.setcbreak(sys.stdin.fileno())
        except (termios.error, OSError):
            self._available = False
            return

        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._available or not self._running:
            return
        self._running = False
        if self._thread:
            self._thread.join(timeout=0.5)
            self._thread = None
        self._restore()

    def _restore(self) -> None:
        if self._old_settings:
            import termios
            try:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._old_settings)
            except (termios.error, OSError):
                pass
            self._old_settings = None

    def _monitor(self) -> None:
        import select

        while self._running:
            try:
                ready, _, _ = select.select([sys.stdin], [], [], 0.1)
            except (OSError, ValueError):
                break

            if ready:
                try:
                    ch = sys.stdin.read(1)
                except (OSError, ValueError):
                    break

                if ch == "\x1b":
                    # 区分裸 ESC 和 ANSI 转义序列
                    try:
                        r, _, _ = select.select([sys.stdin], [], [], 0.05)
                    except (OSError, ValueError):
                        break
                    if r:
                        # 是转义序列的一部分（如方向键），消耗剩余字节
                        try:
                            sys.stdin.read(2)
                        except (OSError, ValueError):
                            pass
                    else:
                        # 裸 ESC
                        self.event.set()
                        break
