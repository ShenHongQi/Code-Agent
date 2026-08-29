"""终端 Markdown 渲染：将 Markdown 文本转换为 ANSI 格式化输出。"""

from __future__ import annotations
import re
import shutil
import unicodedata

# ANSI codes
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
ITALIC = "\033[3m"
UNDERLINE = "\033[4m"
STRIKETHROUGH = "\033[9m"

# Colors
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"
GRAY = "\033[90m"
ORANGE = "\033[38;5;196m"
RED_ORANGE = "\033[38;5;160m"
LIGHT_ORANGE = "\033[38;5;208m"

# Background
BG_GRAY = "\033[48;5;236m"
BG_CODE = "\033[48;5;235m"


class StreamingMarkdownRenderer:
    """流式 Markdown 渲染器，逐行缓冲并输出 ANSI 格式化文本。

    设计原则：
    - 逐 token 喂入，按行/块输出
    - 代码块需要完整缓冲后再输出（带边框）
    - 普通行在换行符到达时渲染
    """

    def __init__(self):
        self._buffer = ""
        self._in_code_block = False
        self._code_lang = ""
        self._code_lines: list[str] = []
        self._output_lines: list[str] = []
        self._in_table = False
        self._table_rows: list[str] = []
        self._width = shutil.get_terminal_size().columns

    def feed(self, token: str) -> str:
        """喂入一个 token，返回可以立即输出的渲染文本（可能为空）。"""
        self._buffer += token
        output = ""

        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            rendered = self._process_line(line)
            if rendered is not None:
                output += rendered + "\n"

        return output

    def flush(self) -> str:
        """流结束时刷出剩余缓冲。"""
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
        """处理一行，返回渲染结果或 None（缓冲中）。"""
        # 代码块开始/结束
        stripped = line.strip()
        if stripped.startswith("```"):
            if not self._in_code_block:
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

        # 空行
        if not stripped:
            return ""

        # 水平分割线
        if re.match(r'^[-*_]{3,}\s*$', stripped):
            return f"{DIM}{'─' * min(self._width, 60)}{RESET}"

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

        # 引用块
        if stripped.startswith(">"):
            content = re.sub(r'^>\s?', '', line)
            return f"{DIM}│{RESET} {ITALIC}{self._render_inline(content)}{RESET}"

        # 表格行（含 | 且不是引用块）
        if "|" in stripped:
            if not self._in_table:
                self._in_table = True
                self._table_rows = []
            self._table_rows.append(stripped)
            return None

        # 表格结束（上一行是表格，当前行不是）
        if self._in_table:
            rendered = self._render_table()
            self._in_table = False
            self._table_rows = []
            current = self._process_line(line)
            return rendered + ("\n" + current if current else "")

        # 普通段落
        return self._render_inline(line)

    def _render_header(self, level: int, text: str) -> str:
        """渲染标题。"""
        colors = {1: BOLD + ORANGE, 2: BOLD + RED_ORANGE, 3: BOLD + LIGHT_ORANGE,
                  4: BOLD + YELLOW, 5: BOLD + MAGENTA, 6: BOLD + WHITE}
        color = colors.get(level, BOLD)
        prefix = "━" * level + " " if level <= 2 else ""
        return f"\n{color}{prefix}{text}{RESET}"

    def _render_code_block(self) -> str:
        """渲染代码块，带边框和语言标签。"""
        width = min(self._width - 4, 80)
        lines = []

        # 顶部边框 + 语言标签
        lang_label = f" {self._code_lang} " if self._code_lang else ""
        top = f"{DIM}┌{'─' * 2}{lang_label}{'─' * max(0, width - 3 - len(lang_label))}┐{RESET}"
        lines.append(top)

        # 代码内容
        for code_line in self._code_lines:
            # 截断过长行
            display = code_line[:width - 2]
            padding = " " * max(0, width - 1 - len(display))
            lines.append(f"{DIM}│{RESET} {BG_CODE}{LIGHT_ORANGE}{display}{padding}{RESET}{DIM}│{RESET}")

        # 底部边框
        bottom = f"{DIM}└{'─' * (width + 1)}┘{RESET}"
        lines.append(bottom)

        return "\n".join(lines)

    @staticmethod
    def _visual_width(s: str) -> int:
        """计算字符串的终端可视宽度（CJK 字符占 2 列）。"""
        w = 0
        for ch in s:
            if unicodedata.east_asian_width(ch) in ("W", "F"):
                w += 2
            else:
                w += 1
        return w

    @staticmethod
    def _strip_ansi(s: str) -> str:
        """去除 ANSI 转义码，返回纯文本。"""
        return re.sub(r'\033\[[0-9;]*m', '', s)

    def _ansi_visual_width(self, s: str) -> int:
        """计算含 ANSI 码字符串的可视宽度。"""
        return self._visual_width(self._strip_ansi(s))

    @staticmethod
    def _truncate_to_visual_width(s: str, max_w: int) -> str:
        """截断纯文本至不超过 max_w 列宽，附加 … 标记。"""
        w = 0
        for i, ch in enumerate(s):
            cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
            if w + cw > max_w - 1:  # 留 1 列给 …
                return s[:i] + "…"
            w += cw
        return s

    def _render_table(self) -> str:
        """渲染 Markdown 表格为带边框的终端表格。

        核心修复：先渲染行内格式再计算可视宽度和填充，
        避免 ANSI 码干扰列对齐。
        """
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

        # ── 解析行和对齐 ──
        parsed: list[list[str]] = []
        sep_idx = -1
        aligns: list[str] = []

        for i, row in enumerate(self._table_rows):
            if is_separator(row):
                sep_idx = i
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
        for r in parsed:
            while len(r) < num_cols:
                r.append("")
        while len(aligns) < num_cols:
            aligns.append("left")

        has_header = sep_idx == 1

        # ── 先渲染行内格式，再测量可视宽度 ──
        rendered: list[list[str]] = []
        for i, row in enumerate(parsed):
            rendered_row = []
            for cell in row:
                inline = self._render_inline(cell)
                if has_header and i == 0:
                    rendered_row.append(f"{BOLD}{self._strip_ansi(inline)}{RESET}")
                else:
                    rendered_row.append(inline)
            rendered.append(rendered_row)

        avw = self._ansi_visual_width

        # ── 基于渲染后可视宽度计算列宽 ──
        col_widths = [3] * num_cols
        for row in rendered:
            for j, cell in enumerate(row):
                col_widths[j] = max(col_widths[j], avw(cell))

        # ── 限制总宽度不超过终端 ──
        border_overhead = num_cols * 3 + 1  # │ + 2 padding per col + closing │
        max_content_w = self._width - border_overhead - 2  # 留 2 列余量
        total_content = sum(col_widths)

        if total_content > max_content_w and num_cols > 0:
            # 按比例缩减，每列最少 4 列宽
            scale = max_content_w / total_content
            col_widths = [max(4, int(w * scale)) for w in col_widths]
            # 微调：多余的宽度补回最宽列
            remainder = max_content_w - sum(col_widths)
            if remainder > 0:
                widest = col_widths.index(max(col_widths))
                col_widths[widest] += remainder

        # ── 对齐填充（在 ANSI 渲染后的文本上操作） ──
        def pad_cell(rendered_text: str, width: int, alignment: str) -> str:
            vw = avw(rendered_text)
            if vw > width:
                # 截断：先去 ANSI 截断纯文本，再重新渲染
                plain = self._strip_ansi(rendered_text)
                truncated = self._truncate_to_visual_width(plain, width)
                # 重新简单渲染截断后的文本（可能丢失部分格式，但对齐正确）
                rendered_text = truncated
                vw = self._visual_width(truncated)
            pad = width - vw
            if alignment == "center":
                left = pad // 2
                return " " * left + rendered_text + " " * (pad - left)
            elif alignment == "right":
                return " " * pad + rendered_text
            return rendered_text + " " * pad

        # ── 生成输出 ──
        def hline(left: str, mid: str, right: str) -> str:
            segs = ["─" * (w + 2) for w in col_widths]
            return f"{DIM}{left}{mid.join(segs)}{right}{RESET}"

        lines = [hline("┌", "┬", "┐")]

        for i, row in enumerate(rendered):
            cells = []
            for j, cell in enumerate(row):
                cells.append(pad_cell(cell, col_widths[j], aligns[j]))
            inner = f"{DIM}│{RESET}".join(f" {c} " for c in cells)
            lines.append(f"{DIM}│{RESET}{inner}{DIM}│{RESET}")

            if has_header and i == 0:
                lines.append(hline("├", "┼", "┤"))

        lines.append(hline("└", "┴", "┘"))
        return "\n".join(lines)

    def _render_inline(self, text: str) -> str:
        """渲染行内格式：粗体、斜体、行内代码、链接、删除线。"""
        # 行内代码 (先处理，避免内部格式被解析)
        text = re.sub(
            r'`([^`]+)`',
            lambda m: f"{BG_GRAY}{ORANGE}{m.group(1)}{RESET}",
            text
        )

        # 粗斜体
        text = re.sub(
            r'\*\*\*(.+?)\*\*\*',
            lambda m: f"{BOLD}{ITALIC}{m.group(1)}{RESET}",
            text
        )

        # 粗体
        text = re.sub(
            r'\*\*(.+?)\*\*',
            lambda m: f"{BOLD}{m.group(1)}{RESET}",
            text
        )

        # 斜体
        text = re.sub(
            r'(?<!\*)\*([^*]+?)\*(?!\*)',
            lambda m: f"{ITALIC}{m.group(1)}{RESET}",
            text
        )

        # 删除线
        text = re.sub(
            r'~~(.+?)~~',
            lambda m: f"{STRIKETHROUGH}{m.group(1)}{RESET}",
            text
        )

        # 链接 [text](url)
        text = re.sub(
            r'\[([^\]]+)\]\(([^)]+)\)',
            lambda m: f"{UNDERLINE}{BLUE}{m.group(1)}{RESET}{DIM}({m.group(2)}){RESET}",
            text
        )

        return text


def render_markdown(text: str) -> str:
    """一次性渲染完整的 Markdown 文本。"""
    renderer = StreamingMarkdownRenderer()
    output = renderer.feed(text + "\n")
    output += renderer.flush()
    return output.rstrip("\n")
