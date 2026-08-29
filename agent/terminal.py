"""终端交互：readline 历史、Spinner 动画、ESC 检测、命令补全。"""

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
ORANGE = "\033[38;5;196m"
RED_ORANGE = "\033[38;5;160m"
YELLOW = "\033[33m"


class EscInterrupt(Exception):
    """ESC 键触发的中断。"""
    pass


def _visual_width(s: str) -> int:
    """计算字符串在终端中的视觉宽度（CJK字符占2列）。"""
    import unicodedata
    w = 0
    for ch in s:
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            w += 2
        else:
            w += 1
    return w


def _truncate_to_width(s: str, max_width: int) -> str:
    """截断字符串至不超过 max_width 列宽。"""
    import unicodedata
    w = 0
    for i, ch in enumerate(s):
        cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if w + cw > max_width:
            return s[:i]
        w += cw
    return s


# ─── InputManager ───────────────────────────────────────────────────────────

class InputManager:
    """readline 集成 + 持久化历史 + 斜杠命令补全。"""

    def __init__(self):
        self._readline_available = False
        self._commands: list[tuple[str, str]] = []  # [(name, description), ...]
        self._setup_readline()

    def set_commands(self, commands: list[tuple[str, str]]) -> None:
        """设置可用斜杠命令列表，用于自动补全。"""
        self._commands = commands

    def _setup_readline(self) -> None:
        try:
            import readline
            self._readline = readline

            if "libedit" in (readline.__doc__ or ""):
                readline.parse_and_bind("bind ^I rl_complete")
            else:
                readline.parse_and_bind("tab: complete")

            readline.set_history_length(HISTORY_SIZE)

            if HISTORY_FILE.exists():
                readline.read_history_file(str(HISTORY_FILE))

            self._readline_available = True
        except (ImportError, OSError):
            self._readline = None

    def styled_input(self, prefill: str = "", model: str = "") -> str:
        """显示上下分隔线框住的输入区域。检测 / 开头触发命令补全。"""
        width = shutil.get_terminal_size().columns
        sep = f"{ORANGE}{'─' * width}{RESET}"

        # 画框架
        sys.stdout.write(f"\n{sep}\n")
        sys.stdout.write("\n")
        sys.stdout.write(f"{sep}\n")
        model_line = f"{DIM}  model: {model}{RESET}" if model else ""
        if model_line:
            sys.stdout.write(f"{model_line}\n")

        up = 3 if model else 2
        sys.stdout.write(f"\033[{up}A\r")
        sys.stdout.flush()

        # 如果有 prefill 且以 / 开头 — _slash_input 自行处理框架底部和光标
        if prefill and prefill.startswith("/") and self._commands:
            return self._slash_input(prefill, model)

        if prefill and self._readline_available:
            self._readline.set_startup_hook(lambda: self._readline.insert_text(prefill))

        slash_used = False
        try:
            if not prefill and self._commands and sys.stdin.isatty() and os.name != "nt":
                result, slash_used = self._input_with_slash_detect(model)
            else:
                result = input(f"{BOLD}{ORANGE}> {RESET}")
        finally:
            if self._readline_available:
                self._readline.set_startup_hook()

        if not slash_used:
            # 普通输入后，光标在输入行下一行（底线处），跳过剩余框架
            down = 2 if model else 1
            sys.stdout.write(f"\033[{down}B\r")
            sys.stdout.flush()

        return result.strip()

    def _input_with_slash_detect(self, model: str) -> tuple[str, bool]:
        """读取第一个字符，如果是 / 则进入命令补全模式。

        返回 (result, slash_used):
          slash_used=True 时，_slash_input 已自行处理光标和框架底部重绘。
          slash_used=False 时，调用者需自行跳过框架底部。
        """
        import termios
        import tty

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)

        sys.stdout.write(f"{BOLD}{ORANGE}> {RESET}")
        sys.stdout.flush()

        try:
            tty.setcbreak(fd)
            first_char = sys.stdin.read(1)
        except (termios.error, OSError, KeyboardInterrupt):
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            raise EOFError()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

        if first_char == "/":
            result = self._slash_input("/", model)
            return (result, True)

        # 非 / 开头：用 readline 继续
        if self._readline_available:
            self._readline.set_startup_hook(
                lambda: self._readline.insert_text(first_char)
            )

        try:
            sys.stdout.write(f"\r\033[K")
            sys.stdout.flush()
            result = input(f"{BOLD}{ORANGE}> {RESET}")
        finally:
            if self._readline_available:
                self._readline.set_startup_hook()

        return (result, False)

    def _slash_input(self, initial: str = "/", model: str = "") -> str:
        """斜杠命令补全模式：实时下拉框 + 过滤。

        在输入行下方绘制下拉框。每次重绘时先用 \\033[J 清除输入行下方所有内容，
        然后重新绘制框架底部（分隔线+model）和下拉框，最后用相对移动回到输入行。
        这种方式不依赖 \\033[s/u 光标保存，对终端滚动免疫。
        """
        import termios
        import tty

        if not sys.stdin.isatty() or os.name == "nt":
            return input(f"{BOLD}{ORANGE}> {RESET}{initial}")

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)

        buffer = initial
        selected = 0

        def _get_matches():
            query = buffer[1:].lower()
            if not query:
                return self._commands[:]
            return [(n, d) for n, d in self._commands if n.startswith(query)]

        def _render():
            cols = shutil.get_terminal_size().columns

            # 1. 重绘输入行
            sys.stdout.write(f"\r\033[K")
            sys.stdout.write(f"{BOLD}{ORANGE}> {buffer}{RESET}")

            # 2. 清除输入行下方所有内容
            sys.stdout.write(f"\033[J")

            # 3. 重新绘制框架底部
            lines_below = 0
            sys.stdout.write(f"\n{ORANGE}{'─' * cols}{RESET}")
            lines_below += 1
            if model:
                sys.stdout.write(f"\n{DIM}  model: {model}{RESET}")
                lines_below += 1

            # 4. 绘制下拉框
            matches = _get_matches()
            if matches:
                # box_inner: │和│之间的字符宽度
                box_inner = min(cols - 8, 48)
                # 条目可用宽度 = box_inner - 前缀3(" ❯ "或"   ") - 后缀1(" ")
                entry_max = box_inner - 4

                sys.stdout.write(f"\n  {DIM}┌{'─' * box_inner}┐{RESET}")
                lines_below += 1
                for i, (name, desc) in enumerate(matches):
                    raw_entry = f"/{name}  {desc}"
                    entry = _truncate_to_width(raw_entry, entry_max)
                    vw = _visual_width(entry)
                    pad = " " * max(0, entry_max - vw)
                    if i == selected:
                        sys.stdout.write(
                            f"\n  {DIM}│{RESET}{BOLD}{ORANGE} ❯ {entry}{pad} {RESET}{DIM}│{RESET}"
                        )
                    else:
                        sys.stdout.write(
                            f"\n  {DIM}│{RESET}   {entry}{pad} {DIM}│{RESET}"
                        )
                    lines_below += 1
                sys.stdout.write(f"\n  {DIM}└{'─' * box_inner}┘{RESET}")
                lines_below += 1

            # 5. 相对移动回输入行
            if lines_below > 0:
                sys.stdout.write(f"\033[{lines_below}A")
            cursor_col = _visual_width(buffer) + 2
            sys.stdout.write(f"\r\033[{cursor_col}C")
            sys.stdout.flush()

        def _finish(result: str):
            """退出时清理：清除下方内容，重绘框架底部，输出结果。"""
            cols = shutil.get_terminal_size().columns
            sys.stdout.write(f"\r\033[K")
            sys.stdout.write(f"{BOLD}{ORANGE}> {result}{RESET}")
            sys.stdout.write(f"\033[J")
            # 重绘框架底部
            sys.stdout.write(f"\n{ORANGE}{'─' * cols}{RESET}")
            if model:
                sys.stdout.write(f"\n{DIM}  model: {model}{RESET}")
            sys.stdout.write(f"\n")
            sys.stdout.flush()

        try:
            tty.setcbreak(fd)
            _render()

            while True:
                ch = sys.stdin.read(1)

                if ch == "\x1b":
                    import select
                    r, _, _ = select.select([sys.stdin], [], [], 0.05)
                    if r:
                        seq = sys.stdin.read(2)
                        matches = _get_matches()
                        if seq == "[A" and matches:  # 上
                            selected = (selected - 1) % len(matches)
                            _render()
                        elif seq == "[B" and matches:  # 下
                            selected = (selected + 1) % len(matches)
                            _render()
                    else:
                        # 裸 ESC — 取消
                        _finish("")
                        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                        return ""

                elif ch in ("\r", "\n"):  # Enter
                    matches = _get_matches()
                    if matches and selected < len(matches):
                        result = "/" + matches[selected][0]
                    else:
                        result = buffer
                    _finish(result)
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                    return result

                elif ch in ("\x7f", "\x08"):  # Backspace
                    if len(buffer) > 1:
                        buffer = buffer[:-1]
                        selected = 0
                        _render()
                    else:
                        _finish("")
                        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                        return ""

                elif ch == "\x03":  # Ctrl+C
                    _finish("")
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                    raise KeyboardInterrupt()

                elif ch == "\t":  # Tab 填充
                    matches = _get_matches()
                    if matches and selected < len(matches):
                        buffer = "/" + matches[selected][0]
                        _render()

                elif ch.isprintable():
                    buffer += ch
                    selected = 0
                    _render()

        except (termios.error, OSError):
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            return buffer
        finally:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            except (termios.error, OSError):
                pass

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
        if not self._running:
            return
        self._paused.set()
        time.sleep(0.05)
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
                    try:
                        r, _, _ = select.select([sys.stdin], [], [], 0.05)
                    except (OSError, ValueError):
                        break
                    if r:
                        try:
                            sys.stdin.read(2)
                        except (OSError, ValueError):
                            pass
                    else:
                        self.event.set()
                        break


# ─── InteractiveSelector ────────────────────────────────────────────────────

def select_menu(items: list[str], title: str = "选择:") -> int | None:
    """交互式上下键选择菜单。返回选中索引，ESC/q 取消返回 None。"""
    if not items:
        return None

    if not sys.stdin.isatty() or os.name == "nt":
        sys.stdout.write(f"{BOLD}{title}{RESET}\n")
        for i, item in enumerate(items):
            sys.stdout.write(f"  {i + 1}. {item}\n")
        sys.stdout.write(f"{DIM}输入序号 (ESC 取消): {RESET}")
        sys.stdout.flush()
        try:
            choice = input().strip()
            idx = int(choice) - 1
            if 0 <= idx < len(items):
                return idx
        except (ValueError, EOFError, KeyboardInterrupt):
            pass
        return None

    import termios
    import tty

    selected = 0
    total = len(items)

    cols = shutil.get_terminal_size().columns
    max_item_width = cols - 6
    display_items = []
    for item in items:
        clean = item.replace("\n", " ").replace("\r", "")
        if len(clean) > max_item_width:
            clean = clean[:max_item_width] + "…"
        display_items.append(clean)

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    render_lines = total + 1

    def _render():
        sys.stdout.write(f"\033[{render_lines}A")
        sys.stdout.write("\033[J")
        sys.stdout.write(f"{BOLD}{title}{RESET}\n")
        for i, item in enumerate(display_items):
            if i == selected:
                sys.stdout.write(f"  {BOLD}{ORANGE}❯ {item}{RESET}\n")
            else:
                sys.stdout.write(f"  {DIM}  {item}{RESET}\n")
        sys.stdout.flush()

    try:
        tty.setcbreak(fd)

        sys.stdout.write(f"{BOLD}{title}{RESET}\n")
        for i, item in enumerate(display_items):
            if i == selected:
                sys.stdout.write(f"  {BOLD}{ORANGE}❯ {item}{RESET}\n")
            else:
                sys.stdout.write(f"  {DIM}  {item}{RESET}\n")
        sys.stdout.flush()

        while True:
            ch = sys.stdin.read(1)

            if ch == "\x1b":
                seq = sys.stdin.read(2)
                if seq == "[A":
                    selected = (selected - 1) % total
                    _render()
                elif seq == "[B":
                    selected = (selected + 1) % total
                    _render()
                elif seq == "" or seq[0] != "[":
                    return None
            elif ch in ("\r", "\n"):
                return selected
            elif ch in ("q", "Q"):
                return None
            elif ch == "\x03":
                return None

    except (termios.error, OSError, KeyboardInterrupt):
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
