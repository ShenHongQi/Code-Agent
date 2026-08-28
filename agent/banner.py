"""启动 Banner：深浅像素块拼出 MEGUMIN + 橙红色主题。"""

from __future__ import annotations

# 像素块字符：从亮到暗
# █ = 最亮, ▓ = 次亮, ▒ = 中, ░ = 暗

# 每个字母用 5行×宽度 的像素矩阵表示
# 3 = █(亮), 2 = ▓, 1 = ▒, 0 = 空格
_M = [
    [3, 2, 0, 0, 0, 2, 3],
    [3, 3, 2, 0, 2, 3, 3],
    [3, 1, 3, 2, 3, 1, 3],
    [3, 1, 0, 3, 0, 1, 3],
    [3, 0, 0, 0, 0, 0, 3],
    [2, 0, 0, 0, 0, 0, 2],
]

_E = [
    [3, 3, 3, 3, 3],
    [3, 2, 0, 0, 0],
    [3, 3, 3, 2, 0],
    [3, 2, 0, 0, 0],
    [3, 3, 3, 3, 3],
    [0, 1, 1, 1, 1],
]

_G = [
    [0, 2, 3, 3, 3, 2],
    [3, 2, 0, 0, 0, 0],
    [3, 0, 0, 3, 3, 2],
    [3, 2, 0, 0, 2, 3],
    [0, 3, 3, 3, 3, 1],
    [0, 0, 1, 1, 0, 0],
]

_U = [
    [3, 0, 0, 0, 3],
    [3, 1, 0, 1, 3],
    [3, 1, 0, 1, 3],
    [3, 2, 0, 2, 3],
    [0, 3, 3, 3, 1],
    [0, 0, 1, 0, 0],
]

_I = [
    [3, 3, 3],
    [0, 3, 0],
    [0, 3, 0],
    [0, 3, 0],
    [3, 3, 3],
    [1, 1, 1],
]

_N = [
    [3, 2, 0, 0, 3],
    [3, 3, 1, 0, 3],
    [3, 2, 3, 0, 3],
    [3, 0, 2, 3, 3],
    [3, 0, 0, 2, 3],
    [2, 0, 0, 0, 2],
]

LETTERS = [_M, _E, _G, _U, _M, _I, _N]
LETTER_GAP = 1  # 字母间距

# 橙红色梯度 (256-color): 深→浅
_SHADES = {
    0: None,           # 空格
    1: 52,             # 最暗红
    2: 166,            # 中橙红
    3: 208,            # 亮橙
}

# 行级底色偏移：顶部亮、底部暗
_ROW_OFFSETS = {
    0: 208,  # 亮橙
    1: 202,  # 橙红
    2: 196,  # 红
    3: 160,  # 深红
    4: 166,  # 回升橙红
    5: 52,   # 阴影暗红
}

TAGLINE = "⚡ Explosion-class Coding Agent"


def _pixel_char(level: int) -> str:
    if level == 3:
        return "██"
    elif level == 2:
        return "▓▓"
    elif level == 1:
        return "░░"
    return "  "


def _colored(text: str, fg: int | None) -> str:
    if fg is None:
        return text
    return f"\033[38;5;{fg}m{text}\033[0m"


def _render_logo() -> list[str]:
    """将字母矩阵拼合为带颜色的行。"""
    num_rows = 6
    output_lines = []

    for row in range(num_rows):
        line_parts = []
        row_color = _ROW_OFFSETS.get(row, 166)

        for li, letter in enumerate(LETTERS):
            if li > 0:
                line_parts.append("  ")  # 字母间隔
            for col_val in letter[row]:
                char = _pixel_char(col_val)
                if col_val == 0:
                    line_parts.append(char)
                elif col_val == 1:
                    line_parts.append(_colored(char, 52))
                elif col_val == 2:
                    line_parts.append(_colored(char, max(88, row_color - 20)))
                else:
                    line_parts.append(_colored(char, row_color))

        output_lines.append("    " + "".join(line_parts))

    return output_lines


def render_banner(model: str = "", workspace: str = "") -> str:
    """渲染带橙红渐变色像素块的启动 banner。"""
    lines = _render_logo()
    lines.append("")
    lines.append(_colored(f"    {TAGLINE}", 245))

    if model or workspace:
        info_parts = []
        if model:
            info_parts.append(f"model: {model}")
        if workspace:
            info_parts.append(f"workspace: {workspace}")
        info_line = "    " + " │ ".join(info_parts)
        lines.append(_colored(info_line, 240))

    lines.append(_colored("    Type your request, or 'exit' / Ctrl+D to quit. ESC to interrupt.", 240))
    lines.append("")

    return "\n".join(lines)
