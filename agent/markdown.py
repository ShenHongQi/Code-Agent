"""终端 Markdown 渲染：流式增量 + Rich Syntax/Table 组件。

流式模式（StreamingMarkdownRenderer）：逐 token 喂入，立即输出普通行，
缓冲代码块和表格待完整后用 Rich 渲染。

批量模式（render_markdown）：一次性渲染完整文本。
"""

from __future__ import annotations
import re
import shutil
import unicodedata

from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from agent.theme import MEGUMIN_THEME, ACCENT, ACCENT_DIM, MUTED

# 轻量 ANSI（仅流式渲染用，避免每 token 构造 Rich 对象）
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
ITALIC = "\033[3m"
UNDERLINE = "\033[4m"
STRIKETHROUGH = "\033[9m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
GRAY = "\033[90m"
ORANGE = "\033[38;5;208m"
LIGHT_ORANGE = "\033[38;5;215m"
BG_CODE = "\033[48;5;235m"

_console = Console(theme=MEGUMIN_THEME, highlight=False, force_terminal=True)


class StreamingMarkdownRenderer:
    """流式 Markdown 渲染器：逐 token 缓冲，按行/块输出。

    普通行 → 立即 ANSI 渲染输出
    代码块 → 缓冲完整后用 Rich Syntax 高亮
    表格   → 缓冲完整后用 Rich Table 渲染
    """

    def __init__(self):
        self._buffer = ""
        self._in_code_block = False
        self._code_lang = ""
        self._code_lines: list[str] = []
        self._in_table = False
        self._table_rows: list[str] = []
        self._width = shutil.get_terminal_size().columns

    def feed(self, token: str) -> str:
        self._buffer += token
        output = ""

        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            rendered = self._process_line(line)
            if rendered is not None:
                output += rendered + "\n"

        return output

    def flush(self) -> str:
        output = ""
        if self._buffer:
            rendered = self._process_line(self._buffer)
            if rendered is not None:
                output += rendered
            self._buffer = ""

        if self._in_code_block:
            output += self._render_code_block()
            self._in_code_block = False
            self._code_lines = []

        if self._in_table:
            output += self._render_table()
            self._in_table = False
            self._table_rows = []

        return output

    def _process_line(self, line: str) -> str | None:
        stripped = line.strip()

        # ─── 代码块 ───
        if stripped.startswith("```"):
            if not self._in_code_block:
                # 如果正在收集表格，先输出
                if self._in_table:
                    table_out = self._render_table()
                    self._in_table = False
                    self._table_rows = []
                    self._in_code_block = True
                    self._code_lang = stripped[3:].strip()
                    self._code_lines = []
                    return table_out
                self._in_code_block = True
                self._code_lang = stripped[3:].strip()
                self._code_lines = []
                return None
            else:
                rendered = self._render_code_block()
                self._in_code_block = False
                self._code_lines = []
                self._code_lang = ""
                return rendered

        if self._in_code_block:
            self._code_lines.append(line)
            return None

        # ─── 表格 ───
        if "|" in stripped and not stripped.startswith(">"):
            if self._in_table:
                self._table_rows.append(stripped)
                return None
            # 开始表格
            self._in_table = True
            self._table_rows = [stripped]
            return None

        # 表格结束
        if self._in_table:
            rendered = self._render_table()
            self._in_table = False
            self._table_rows = []
            current = self._process_line(line)
            return rendered + ("\n" + current if current else "")

        # ─── 普通行 ───
        if not stripped:
            return ""

        # 水平线
        if re.match(r'^[-*_]{3,}\s*$', stripped):
            return f"{DIM}{'─' * min(self._width - 2, 60)}{RESET}"

        # 标题
        header_match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if header_match:
            level = len(header_match.group(1))
            text = header_match.group(2)
            return self._render_header(level, text)

        # 无序列表
        list_match = re.match(r'^(\s*)([-*+])\s+(.+)$', line)
        if list_match:
            indent = list_match.group(1)
            content = list_match.group(3)
            return f"{indent}{ORANGE}•{RESET} {self._render_inline(content)}"

        # 有序列表
        olist_match = re.match(r'^(\s*)(\d+)[.)]\s+(.+)$', line)
        if olist_match:
            indent = olist_match.group(1)
            num = olist_match.group(2)
            content = olist_match.group(3)
            return f"{indent}{ORANGE}{num}.{RESET} {self._render_inline(content)}"

        # 引用
        if stripped.startswith(">"):
            content = re.sub(r'^>\s?', '', line)
            return f"{DIM}│{RESET} {ITALIC}{self._render_inline(content)}{RESET}"

        # 普通段落
        return self._render_inline(line)

    def _render_header(self, level: int, text: str) -> str:
        colors = {
            1: f"{BOLD}{ORANGE}", 2: f"{BOLD}\033[38;5;209m",
            3: f"{BOLD}{LIGHT_ORANGE}", 4: f"{BOLD}{YELLOW}",
        }
        color = colors.get(level, BOLD)
        if level <= 2:
            width = min(self._width - 2, 60)
            return f"\n{color}{text}{RESET}\n{DIM}{'─' * width}{RESET}"
        return f"\n{color}{text}{RESET}"

    def _render_code_block(self) -> str:
        """用 Rich Syntax 渲染代码块（带语法高亮）。"""
        code = "\n".join(self._code_lines)
        lang = self._code_lang or "text"

        # 映射常见别名
        lang_map = {"sh": "bash", "shell": "bash", "js": "javascript",
                     "ts": "typescript", "py": "python"}
        lang = lang_map.get(lang, lang)

        try:
            syntax = Syntax(
                code, lang,
                theme="monokai",
                line_numbers=len(self._code_lines) > 5,
                word_wrap=True,
                padding=(0, 1),
            )
            with _console.capture() as capture:
                _console.print(syntax)
            return capture.get().rstrip("\n")
        except Exception:
            # fallback: 简单框线
            return self._render_code_block_fallback(code)

    def _render_code_block_fallback(self, code: str) -> str:
        width = min(self._width - 4, 80)
        lines = [f"{DIM}┌{'─' * (width + 1)}┐{RESET}"]
        for line in code.split("\n"):
            display = line[:width]
            pad = " " * max(0, width - len(display))
            lines.append(f"{DIM}│{RESET} {BG_CODE}{LIGHT_ORANGE}{display}{pad}{RESET}{DIM}│{RESET}")
        lines.append(f"{DIM}└{'─' * (width + 1)}┘{RESET}")
        return "\n".join(lines)

    # ─── 表格渲染（Rich Table）───

    def _render_table(self) -> str:
        if not self._table_rows:
            return ""

        def parse_row(row: str) -> list[str]:
            cells = row.split("|")
            if cells and not cells[0].strip():
                cells = cells[1:]
            if cells and not cells[-1].strip():
                cells = cells[:-1]
            return [c.strip() for c in cells]

        def is_separator(row: str) -> bool:
            return bool(re.match(r'^[\s|:\-]+$', row)) and "--" in row

        parsed: list[list[str]] = []
        aligns: list[str] = []
        has_header = False

        for i, row in enumerate(self._table_rows):
            if is_separator(row):
                if i == 1:
                    has_header = True
                for cell in parse_row(row):
                    cell = cell.strip()
                    if cell.startswith(":") and cell.endswith(":"):
                        aligns.append("center")
                    elif cell.endswith(":"):
                        aligns.append("right")
                    else:
                        aligns.append("left")
                continue
            parsed.append(parse_row(row))

        if not parsed:
            return "\n".join(self._table_rows)

        num_cols = max(len(r) for r in parsed)

        # 用 Rich Table 构建
        table = Table(
            border_style=MUTED,
            show_header=has_header,
            header_style=f"bold {ACCENT}",
            padding=(0, 1),
            expand=False,
        )

        while len(aligns) < num_cols:
            aligns.append("left")

        # 添加列
        if has_header and parsed:
            header_row = parsed[0]
            for j in range(num_cols):
                col_name = header_row[j] if j < len(header_row) else ""
                # 去掉 markdown 粗体语法
                col_name = re.sub(r'\*\*(.+?)\*\*', r'\1', col_name)
                table.add_column(col_name, justify=aligns[j])
            data_rows = parsed[1:]
        else:
            for j in range(num_cols):
                table.add_column(f"Col {j+1}", justify=aligns[j])
            data_rows = parsed

        for row in data_rows:
            while len(row) < num_cols:
                row.append("")
            table.add_row(*row)

        try:
            with _console.capture() as capture:
                _console.print(table)
            return capture.get().rstrip("\n")
        except Exception:
            return "\n".join(self._table_rows)

    # ─── 行内格式 ───

    def _render_inline(self, text: str) -> str:
        # 行内代码
        text = re.sub(
            r'`([^`]+)`',
            lambda m: f"{BG_CODE}\033[38;5;215m{m.group(1)}{RESET}",
            text
        )
        # 粗斜体
        text = re.sub(r'\*\*\*(.+?)\*\*\*', lambda m: f"{BOLD}{ITALIC}{m.group(1)}{RESET}", text)
        # 粗体
        text = re.sub(r'\*\*(.+?)\*\*', lambda m: f"{BOLD}{m.group(1)}{RESET}", text)
        # 斜体
        text = re.sub(r'(?<!\*)\*([^*]+?)\*(?!\*)', lambda m: f"{ITALIC}{m.group(1)}{RESET}", text)
        # 删除线
        text = re.sub(r'~~(.+?)~~', lambda m: f"{STRIKETHROUGH}{m.group(1)}{RESET}", text)
        # 链接
        text = re.sub(
            r'\[([^\]]+)\]\(([^)]+)\)',
            lambda m: f"{UNDERLINE}{BLUE}{m.group(1)}{RESET}{DIM}({m.group(2)}){RESET}",
            text
        )
        return text

    # ─── 工具方法 ───

    @staticmethod
    def _visual_width(s: str) -> int:
        w = 0
        for ch in s:
            if unicodedata.east_asian_width(ch) in ("W", "F"):
                w += 2
            else:
                w += 1
        return w

    @staticmethod
    def _strip_ansi(s: str) -> str:
        return re.sub(r'\033\[[0-9;]*m', '', s)


def render_markdown(text: str) -> str:
    """一次性渲染完整 Markdown 文本。"""
    renderer = StreamingMarkdownRenderer()
    output = renderer.feed(text + "\n")
    output += renderer.flush()
    return output.rstrip("\n")
