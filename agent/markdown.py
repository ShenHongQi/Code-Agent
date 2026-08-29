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

from agent.theme import (
    MEGUMIN_THEME,
    PRIMARY, SECONDARY, ACCENT, TEXT_MUTED,
    MD_HEADING, MD_LINK, MD_CODE, MD_BLOCKQUOTE, MD_LIST, MD_STRONG,
    RESET, BOLD, DIM, ITALIC,
    ANSI_PRIMARY, ANSI_SECONDARY, ANSI_ACCENT, ANSI_MUTED,
)

# 轻量 ANSI（仅流式渲染用，避免每 token 构造 Rich 对象）
UNDERLINE = "\033[4m"
STRIKETHROUGH = "\033[9m"
BLUE = "\033[34m"
BG_CODE = "\033[48;5;235m"

# 从主题色派生的 ANSI 常量
_H1_COLOR = f"{BOLD}{ANSI_SECONDARY}"          # 标题用副色调蓝
_H2_COLOR = f"{BOLD}{ANSI_SECONDARY}"
_H3_COLOR = f"{BOLD}{ANSI_PRIMARY}"             # 三级标题用主色调
_H4_COLOR = f"{BOLD}{ANSI_ACCENT}"              # 四级标题用强调紫
_LINK_COLOR = f"{UNDERLINE}{ANSI_PRIMARY}"      # 链接用主色调
_CODE_INLINE = f"{BG_CODE}{ANSI_PRIMARY}"       # 行内代码
_LIST_MARKER = ANSI_PRIMARY                     # 列表标记
_QUOTE_COLOR = f"{ITALIC}{ANSI_ACCENT}"         # 引用用强调色

_console = Console(theme=MEGUMIN_THEME, highlight=False, force_terminal=True)

MAX_RENDER_WIDTH = 90


def _get_width() -> int:
    return min(shutil.get_terminal_size().columns, MAX_RENDER_WIDTH)


class StreamingMarkdownRenderer:
    """流式 Markdown 渲染器：逐 token 缓冲，按行/块输出。

    普通行 → 立即 ANSI 渲染输出
    代码块 → 缓冲完整后用 Rich Syntax 高亮
    表格   → 缓冲完整后用 Rich Table 渲染

    每次渲染时动态获取终端宽度，确保 resize 后立即适配。
    """

    def __init__(self):
        self._buffer = ""
        self._in_code_block = False
        self._code_lang = ""
        self._code_lines: list[str] = []
        self._in_table = False
        self._table_rows: list[str] = []

    @property
    def _width(self) -> int:
        return _get_width()

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
            self._in_table = True
            self._table_rows = [stripped]
            return None

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
            w = self._width
            return f"{DIM}{'─' * min(w - 2, 60)}{RESET}"

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
            return f"{indent}{_LIST_MARKER}•{RESET} {self._render_inline(content)}"

        # 有序列表
        olist_match = re.match(r'^(\s*)(\d+)[.)]\s+(.+)$', line)
        if olist_match:
            indent = olist_match.group(1)
            num = olist_match.group(2)
            content = olist_match.group(3)
            return f"{indent}{_LIST_MARKER}{num}.{RESET} {self._render_inline(content)}"

        # 引用
        if stripped.startswith(">"):
            content = re.sub(r'^>\s?', '', line)
            return f"{ANSI_MUTED}│{RESET} {_QUOTE_COLOR}{self._render_inline(content)}{RESET}"

        # 普通段落
        return self._render_inline(line)

    def _render_header(self, level: int, text: str) -> str:
        w = self._width
        colors = {1: _H1_COLOR, 2: _H2_COLOR, 3: _H3_COLOR, 4: _H4_COLOR}
        color = colors.get(level, BOLD)
        if level <= 2:
            width = min(w - 2, 60)
            return f"\n{color}{text}{RESET}\n{DIM}{'─' * width}{RESET}"
        return f"\n{color}{text}{RESET}"

    def _render_code_block(self) -> str:
        code = "\n".join(self._code_lines)
        lang = self._code_lang or "text"

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
            return self._render_code_block_fallback(code)

    def _render_code_block_fallback(self, code: str) -> str:
        w = self._width
        width = min(w - 4, 80)
        lines = [f"{DIM}┌{'─' * (width + 1)}┐{RESET}"]
        for line in code.split("\n"):
            display = line[:width]
            pad = " " * max(0, width - len(display))
            lines.append(f"{DIM}│{RESET} {BG_CODE}{ANSI_PRIMARY}{display}{pad}{RESET}{DIM}│{RESET}")
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

        table = Table(
            border_style=TEXT_MUTED,
            show_header=has_header,
            header_style=f"bold {PRIMARY}",
            padding=(0, 1),
            expand=False,
        )

        while len(aligns) < num_cols:
            aligns.append("left")

        if has_header and parsed:
            header_row = parsed[0]
            for j in range(num_cols):
                col_name = header_row[j] if j < len(header_row) else ""
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
            lambda m: f"{_CODE_INLINE}{m.group(1)}{RESET}",
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
            lambda m: f"{_LINK_COLOR}{m.group(1)}{RESET}{DIM}({m.group(2)}){RESET}",
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
