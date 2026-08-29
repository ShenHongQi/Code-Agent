"""终端交互：readline 历史、Spinner 动画、ESC 检测、命令补全、resize 处理。"""

from __future__ import annotations

import os
import shutil
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Callable

HISTORY_FILE = Path.home() / ".megumin" / "history"
HISTORY_SIZE = 1000

# ANSI — 与 theme.py OpenCode 配色对齐
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
ORANGE = "\033[38;5;167m"       # #d75f5f ≈ Primary #e05252 (惠惠红)
RED_ORANGE = "\033[38;5;180m"   # #d7af87 ≈ Primary dimmed
YELLOW = "\033[33m"

# Readline-safe prompt: \001..\002 wrap non-printable sequences so readline
# calculates cursor position correctly (required for arrow-key navigation).
RL_PROMPT = f"\001{BOLD}{ORANGE}\002> \001{RESET}\002"


# ─── 终端 Resize 处理 ──────────────────────────────────────────────────────

_resize_banner_cb: Callable | None = None   # 重绘 banner
_resize_input_cb: Callable | None = None    # 重绘当前输入区域
_resize_stream_cb: Callable | None = None   # 重绘流式输出内容
_prev_sigwinch = None                       # 保存之前的 handler (readline)


def install_resize_handler(banner_cb: Callable) -> None:
    """安装 SIGWINCH handler。banner_cb 负责输出 banner 文本。"""
    global _resize_banner_cb, _prev_sigwinch
    _resize_banner_cb = banner_cb
    if hasattr(signal, "SIGWINCH"):
        _prev_sigwinch = signal.getsignal(signal.SIGWINCH)
        signal.signal(signal.SIGWINCH, _handle_sigwinch)


def _set_input_resize_cb(cb: Callable | None) -> None:
    """注册/取消当前输入区域的 resize 回调。由 InputManager 在进出输入时调用。"""
    global _resize_input_cb
    _resize_input_cb = cb


def set_resize_stream_cb(cb: Callable | None) -> None:
    """注册/取消流式输出的 resize 回调。由 UI 在流式输出期间调用。"""
    global _resize_stream_cb
    _resize_stream_cb = cb


def _handle_sigwinch(signum, frame):
    """SIGWINCH 信号处理：只重绘当前活跃区域，不清屏、不清 scrollback。

    输入状态：擦除输入框（3-4 行），新宽度重绘。
    流式状态：擦除当前可见流式内容，新宽度重新渲染已累积文本。
    其他状态：什么都不做（旧内容已定，新输出会用新宽度）。
    """
    try:
        if _resize_input_cb:
            # 输入框: sep + input + sep + model，光标在 input 行
            # 上移 1 行到 top sep，清到屏幕底部，callback 用 leading_newline=False 重绘
            sys.stdout.write("\033[A\r\033[J")
            sys.stdout.flush()
            _resize_input_cb()
        elif _resize_stream_cb:
            # 流式输出：只清可见区域（不清 scrollback），重绘累积内容
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()
            _resize_stream_cb()
    except Exception:
        pass
    # 链式调用之前的 handler（如 readline 的），让其更新内部终端宽度
    if callable(_prev_sigwinch) and _prev_sigwinch not in (signal.SIG_DFL, signal.SIG_IGN):
        try:
            _prev_sigwinch(signum, frame)
        except Exception:
            pass


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
        self._ctx_info: str = ""
        self._setup_readline()

    def update_ctx_usage(self, prompt_tokens: int, context_limit: int) -> None:
        if not prompt_tokens:
            return
        pct = prompt_tokens / context_limit * 100 if context_limit else 0
        def _f(n: int) -> str:
            if n >= 10_000:
                return f"{n / 1000:.0f}k"
            if n >= 1_000:
                return f"{n / 1000:.1f}k"
            return str(n)
        self._ctx_info = f"ctx {_f(prompt_tokens)}/{_f(context_limit)} ({pct:.0f}%)"

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
        self._draw_input_frame(model)

        # 如果有 prefill 且以 / 开头 — _slash_input 自行处理框架底部和光标
        if prefill and prefill.startswith("/") and self._commands:
            return self._slash_input(prefill, model)

        if prefill and self._readline_available:
            self._readline.set_startup_hook(lambda: self._readline.insert_text(prefill))

        # 注册 resize 回调：SIGWINCH 时重绘输入框
        _set_input_resize_cb(lambda: self._draw_input_frame(model, leading_newline=False))

        slash_used = False
        try:
            if not prefill and self._commands and sys.stdin.isatty() and os.name != "nt":
                result, slash_used = self._input_with_slash_detect(model)
            else:
                result = input(RL_PROMPT)
        finally:
            _set_input_resize_cb(None)
            if self._readline_available:
                self._readline.set_startup_hook()

        result = result.strip()
        if not slash_used:
            sys.stdout.write("\033[1A\r\033[J")
            if result:
                _BG = "\033[48;5;236m"
                for ln in result.split("\n"):
                    sys.stdout.write(f"{_BG} {BOLD}{ORANGE}>{RESET}{_BG} {ln}\033[K{RESET}\n")
            sys.stdout.flush()

        return result

    def _draw_input_frame(self, model: str = "", *, leading_newline: bool = True) -> None:
        """绘制输入区域框架：上分隔线 + 输入行 + 下分隔线 + model，光标停在输入行。

        leading_newline=False 用于 resize 重绘——光标已在 top sep 位置，无需额外换行。
        """
        width = shutil.get_terminal_size().columns
        sep = f"{ORANGE}{'─' * width}{RESET}"

        if leading_newline:
            sys.stdout.write(f"\n{sep}\n")
        else:
            sys.stdout.write(f"{sep}\n")
        sys.stdout.write("\n")
        sys.stdout.write(f"{sep}\n")
        has_info = model or self._ctx_info
        if has_info:
            left = f"  model: {model}" if model else ""
            right = self._ctx_info
            if left and right:
                pad = max(2, width - len(left) - len(right))
                sys.stdout.write(f"{DIM}{left}{' ' * pad}{right}{RESET}\n")
            elif left:
                sys.stdout.write(f"{DIM}{left}{RESET}\n")
            else:
                sys.stdout.write(f"{DIM}{right:>{width}}{RESET}\n")

        up = 3 if has_info else 2
        sys.stdout.write(f"\033[{up}A\r")
        sys.stdout.flush()

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
            first_byte = os.read(fd, 1)
            if first_byte and first_byte[0] == 0x1B:
                # Escape sequence (arrow key, etc.) — drain remaining bytes and ignore
                import fcntl
                flags = fcntl.fcntl(fd, fcntl.F_GETFL)
                fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
                try:
                    os.read(fd, 8)
                except (BlockingIOError, OSError):
                    pass
                finally:
                    fcntl.fcntl(fd, fcntl.F_SETFL, flags)
                first_char = ""
            elif first_byte and first_byte[0] >= 0xC0:
                # Multi-byte UTF-8 — read remaining continuation bytes
                n = 1 if first_byte[0] < 0xE0 else (2 if first_byte[0] < 0xF0 else 3)
                data = first_byte
                for _ in range(n):
                    extra = os.read(fd, 1)
                    if not extra:
                        break
                    data += extra
                first_char = data.decode("utf-8", errors="replace")
            else:
                first_char = first_byte.decode("utf-8", errors="replace") if first_byte else ""
        except (termios.error, OSError, KeyboardInterrupt):
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            raise EOFError()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

        if first_char == "/":
            result = self._slash_input("/", model)
            return (result, True)

        # 非 / 开头：用 readline 继续
        if first_char and self._readline_available:
            self._readline.set_startup_hook(
                lambda: self._readline.insert_text(first_char)
            )

        try:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
            result = input(RL_PROMPT)
        finally:
            if self._readline_available:
                self._readline.set_startup_hook()

        return (result, False)

    def _slash_input(self, initial: str = "/", model: str = "") -> str:
        """斜杠命令补全模式：实时下拉框 + 过滤。

        使用 os.read(fd) 做无缓冲读取，避免 Python 层缓冲导致
        select() 误判 escape sequence 为裸 ESC。
        """
        import fcntl
        import termios
        import tty

        if not sys.stdin.isatty() or os.name == "nt":
            return input(f"{BOLD}{ORANGE}> {RESET}{initial}")

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)

        buffer = initial
        selected = 0
        cursor = len(initial)

        def _in_skill_mode():
            return buffer.lower().startswith("/skill ") or buffer.lower() == "/skill"

        def _get_matches():
            # 二级补全：/skill 后展开 skill 列表
            if buffer.lower().startswith("/skill "):
                from agent.skills import get_all_skills
                query = buffer[7:].lower()  # "/skill " 之后的部分
                skills = get_all_skills()
                if not query:
                    return [(s.name, s.description) for s in skills]
                return [(s.name, s.description) for s in skills
                        if s.name.startswith(query) or any(a.startswith(query) for a in s.aliases)]

            # 一级补全：命令列表
            query = buffer[1:].lower()
            if not query:
                return self._commands[:]
            return [(n, d) for n, d in self._commands if n.startswith(query)]

        def _read_key() -> str:
            """读取一个按键（处理多字节 UTF-8 和 escape sequence）。

            返回:
              普通字符 → 该字符 (如 'a', '/', '请')
              方向键   → '[A', '[B', '[C', '[D'
              裸 ESC   → 'ESC'
              其他转义  → 'ESC'
            """
            b = os.read(fd, 1)
            if not b:
                return ""
            ch = b[0]

            if ch != 0x1b:
                # UTF-8 多字节序列：根据首字节判断还需读几个字节
                if ch >= 0xC0:
                    if ch < 0xE0:
                        remaining = 1
                    elif ch < 0xF0:
                        remaining = 2
                    else:
                        remaining = 3
                    data = b
                    while remaining > 0:
                        extra = os.read(fd, 1)
                        if not extra:
                            break
                        data += extra
                        remaining -= 1
                    return data.decode("utf-8", errors="replace")
                return b.decode("utf-8", errors="replace")

            # 读到 \x1b，用非阻塞读检查是否有后续字节
            flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            try:
                rest = os.read(fd, 4)
            except (BlockingIOError, OSError):
                rest = b""
            finally:
                fcntl.fcntl(fd, fcntl.F_SETFL, flags)

            if rest and rest[0:1] == b"[" and len(rest) >= 2:
                return rest[:2].decode("ascii", errors="replace")
            return "ESC"

        def _render():
            cols = shutil.get_terminal_size().columns

            sys.stdout.write("\r\033[K")
            sys.stdout.write(f"{BOLD}{ORANGE}> {buffer}{RESET}")
            sys.stdout.write("\033[J")

            lines_below = 0
            sys.stdout.write(f"\n{ORANGE}{'─' * cols}{RESET}")
            lines_below += 1
            if model:
                sys.stdout.write(f"\n{DIM}  model: {model}{RESET}")
                lines_below += 1

            matches = _get_matches()
            skill_mode = _in_skill_mode()
            if matches:
                box_inner = min(cols - 8, 48)
                entry_max = box_inner - 4

                sys.stdout.write(f"\n  {DIM}┌{'─' * box_inner}┐{RESET}")
                lines_below += 1
                for i, (name, desc) in enumerate(matches):
                    prefix = "" if skill_mode else "/"
                    raw_entry = f"{prefix}{name}  {desc}"
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

            if lines_below > 0:
                sys.stdout.write(f"\033[{lines_below}A")
            cursor_col = _visual_width(buffer[:cursor]) + 2
            sys.stdout.write(f"\r\033[{cursor_col}C")
            sys.stdout.flush()

        def _finish(result: str):
            sys.stdout.write("\033[1A\r\033[J")
            if result:
                _BG = "\033[48;5;236m"
                for ln in result.split("\n"):
                    sys.stdout.write(f"{_BG} {BOLD}{ORANGE}>{RESET}{_BG} {ln}\033[K{RESET}\n")
            sys.stdout.flush()

        try:
            tty.setcbreak(fd)
            last_cols = shutil.get_terminal_size().columns
            _render()

            while True:
                # 用 select 超时检测：即使没有按键也能响应 resize
                import select as _sel
                try:
                    ready, _, _ = _sel.select([fd], [], [], 0.3)
                except (OSError, ValueError):
                    ready = []

                # 检查 resize（无论是否有按键）
                cur_cols = shutil.get_terminal_size().columns
                if cur_cols != last_cols:
                    last_cols = cur_cols
                    _render()

                if not ready:
                    continue

                key = _read_key()
                if not key:
                    continue

                if key == "[A":  # 上
                    matches = _get_matches()
                    if matches:
                        selected = (selected - 1) % len(matches)
                        _render()

                elif key == "[B":  # 下
                    matches = _get_matches()
                    if matches:
                        selected = (selected + 1) % len(matches)
                        _render()

                elif key == "[C":  # 右
                    if cursor < len(buffer):
                        cursor += 1
                        _render()

                elif key == "[D":  # 左
                    if cursor > 0:
                        cursor -= 1
                        _render()

                elif key == "ESC":  # 裸 ESC — 取消
                    _finish("")
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                    return ""

                elif key in ("\r", "\n"):  # Enter
                    matches = _get_matches()
                    if matches and selected < len(matches):
                        chosen_name = matches[selected][0]
                        if _in_skill_mode():
                            # 二级：选中 skill → 填入名称，用户继续输入参数
                            buffer = "/skill " + chosen_name + " "
                            selected = 0
                            cursor = len(buffer)
                            _render()
                            continue
                        elif chosen_name == "skill":
                            # 一级选中 /skill → 进入二级模式
                            buffer = "/skill "
                            selected = 0
                            cursor = len(buffer)
                            _render()
                            continue
                        else:
                            result = "/" + chosen_name
                    else:
                        result = buffer
                    _finish(result)
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                    return result

                elif key in ("\x7f", "\x08"):  # Backspace
                    if cursor > 0 and len(buffer) > 1:
                        buffer = buffer[:cursor - 1] + buffer[cursor:]
                        cursor -= 1
                        selected = 0
                        _render()
                    elif len(buffer) <= 1:
                        _finish("")
                        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                        return ""

                elif key == "\x03":  # Ctrl+C
                    _finish("")
                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                    raise KeyboardInterrupt()

                elif key == "\t":  # Tab 填充
                    matches = _get_matches()
                    if matches and selected < len(matches):
                        chosen_name = matches[selected][0]
                        if _in_skill_mode():
                            buffer = "/skill " + chosen_name
                        elif chosen_name == "skill":
                            buffer = "/skill "
                            selected = 0
                        else:
                            buffer = "/" + chosen_name
                        cursor = len(buffer)
                        _render()

                elif len(key) == 1 and key.isprintable():
                    buffer = buffer[:cursor] + key + buffer[cursor:]
                    cursor += 1
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
