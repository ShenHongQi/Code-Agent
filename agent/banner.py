"""启动 Banner：方正像素块拼出 MEGUMIN 艺术字 + 橙红色主题。"""

from __future__ import annotations

# 方正外轮廓：每个字母等高等宽(5x5格)，用 █ 和空格构成
# 整体外形是规整的矩形块
LOGO_RAW = r"""
█   █ █████ █████ █   █ █   █ █ █   █
██ ██ █     █     █   █ ██ ██ █ ██  █
█ █ █ ████  █ ███ █   █ █ █ █ █ █ █ █
█   █ █     █   █ █   █ █   █ █ █  ██
█   █ █████ █████ █████ █   █ █ █   █
"""

# 橙红渐变行色
_ROW_COLORS = [208, 196, 160, 196, 208]

TAGLINE = "⚡ Explosion-class Coding Agent"


def _colored(text: str, fg: int) -> str:
    return f"\033[38;5;{fg}m{text}\033[0m"


def render_banner(model: str = "", workspace: str = "") -> str:
    """渲染启动 banner。"""
    lines = [l for l in LOGO_RAW.split("\n") if l.strip()]
    colored_lines = []

    for i, line in enumerate(lines):
        color = _ROW_COLORS[i % len(_ROW_COLORS)]
        colored_lines.append("    " + _colored(line, color))

    colored_lines.append("")
    colored_lines.append(_colored(f"    {TAGLINE}", 245))

    if model or workspace:
        info_parts = []
        if model:
            info_parts.append(f"model: {model}")
        if workspace:
            info_parts.append(f"workspace: {workspace}")
        info_line = "    " + " │ ".join(info_parts)
        colored_lines.append(_colored(info_line, 240))

    colored_lines.append(_colored("    Type your request, or 'exit' / Ctrl+D to quit. ESC to interrupt.", 240))
    colored_lines.append("")

    return "\n".join(colored_lines)
