"""终端 Markdown 渲染：将 Markdown 文本转换为 ANSI 格式化输出。"""

from __future__ import annotations
import re
import shutil

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
            return f"{indent}{CYAN}•{RESET} {self._render_inline(content)}"

        # 有序列表
        olist_match = re.match(r'^(\s*)(\d+)[.)]\s+(.+)$', line)
        if olist_match:
            indent = olist_match.group(1)
            num = olist_match.group(2)
            content = olist_match.group(3)
            return f"{indent}{CYAN}{num}.{RESET} {self._render_inline(content)}"

        # 引用块
        if stripped.startswith(">"):
            content = re.sub(r'^>\s?', '', line)
            return f"{DIM}│{RESET} {ITALIC}{self._render_inline(content)}{RESET}"

        # 普通段落
        return self._render_inline(line)

    def _render_header(self, level: int, text: str) -> str:
        """渲染标题。"""
        colors = {1: BOLD + CYAN, 2: BOLD + GREEN, 3: BOLD + YELLOW,
                  4: BOLD + MAGENTA, 5: BOLD + BLUE, 6: BOLD + WHITE}
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
            lines.append(f"{DIM}│{RESET} {BG_CODE}{GREEN}{display}{padding}{RESET}{DIM}│{RESET}")

        # 底部边框
        bottom = f"{DIM}└{'─' * (width + 1)}┘{RESET}"
        lines.append(bottom)

        return "\n".join(lines)

    def _render_inline(self, text: str) -> str:
        """渲染行内格式：粗体、斜体、行内代码、链接、删除线。"""
        # 行内代码 (先处理，避免内部格式被解析)
        text = re.sub(
            r'`([^`]+)`',
            lambda m: f"{BG_GRAY}{CYAN}{m.group(1)}{RESET}",
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
