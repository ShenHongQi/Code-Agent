"""启动 Banner：像素风 MEGUMIN 艺术字 + 渐变色。"""

from __future__ import annotations

# 256-color ANSI: 渐变从红→橙→黄（火焰/爆炸主题）
_GRADIENT = [196, 202, 208, 214, 220, 226]

LOGO = r"""
    ╔══╦══╗╔═══╗╔═══╗╔╗ ╔╗╔══╦══╗╔══╗╔═╗ ╔╗
    ║  ║  ║║╔══╝║╔═╗║║║ ║║║  ║  ║╚╗╔╝║ ╚╗║║
    ║  ║  ║║╚══╗║║ ╚╝║║ ║║║  ║  ║ ║║ ║╔╗╚╝║
    ║  ║  ║║╔══╝║║╔═╗║║ ║║║  ║  ║ ║║ ║║╚╗║║
    ║  ╚  ║║╚══╗║╚╩═║║╚═╝║║  ╚  ║╔╝╚╗║║ ║║║
    ╚══╩══╝╚═══╝╚═══╝╚═══╝╚══╩══╝╚══╝╚╝ ╚═╝
"""

TAGLINE = "⚡ Explosion-class Coding Agent"


def _color(text: str, color_code: int) -> str:
    return f"\033[38;5;{color_code}m{text}\033[0m"


def render_banner(model: str = "", workspace: str = "") -> str:
    """渲染带渐变色的启动 banner。"""
    lines = LOGO.strip("\n").split("\n")
    colored_lines = []

    for i, line in enumerate(lines):
        color = _GRADIENT[i % len(_GRADIENT)]
        colored_lines.append(_color(line, color))

    # 标语
    colored_lines.append("")
    colored_lines.append(_color(f"  {TAGLINE}", 245))

    # 系统信息
    if model or workspace:
        info_parts = []
        if model:
            info_parts.append(f"model: {model}")
        if workspace:
            info_parts.append(f"workspace: {workspace}")
        info_line = "  " + " │ ".join(info_parts)
        colored_lines.append(_color(info_line, 240))

    colored_lines.append(_color("  Type your request, or 'exit' / Ctrl+D to quit. ESC to interrupt.", 240))
    colored_lines.append("")

    return "\n".join(colored_lines)
