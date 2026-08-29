"""启动 Banner：Rich Panel + 渐变 MEGUMIN 艺术字。"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from agent.theme import MEGUMIN_THEME, ACCENT, ACCENT_DIM, MUTED

LOGO_LINES = [
    "█   █ █████ █████ █   █ █   █ █ █   █",
    "██ ██ █     █     █   █ ██ ██ █ ██  █",
    "█ █ █ ████  █ ███ █   █ █ █ █ █ █ █ █",
    "█   █ █     █   █ █   █ █   █ █ █  ██",
    "█   █ █████ █████ █████ █   █ █ █   █",
]

ROW_COLORS = ["#ff8700", "#ff5f00", "#d75f00", "#ff5f00", "#ff8700"]

TAGLINE = "⚡ Explosion-class Coding Agent"


def render_banner(model: str = "", workspace: str = "") -> str:
    """渲染启动 banner，返回字符串。"""
    console = Console(theme=MEGUMIN_THEME, force_terminal=True)

    logo = Text()
    for i, line in enumerate(LOGO_LINES):
        logo.append(line, style=f"bold {ROW_COLORS[i]}")
        if i < len(LOGO_LINES) - 1:
            logo.append("\n")

    body = Text()
    body.append(logo)
    body.append(f"\n\n{TAGLINE}", style=f"italic {MUTED}")

    if model or workspace:
        parts = []
        if model:
            parts.append(f"model: {model}")
        if workspace:
            parts.append(f"workspace: {workspace}")
        body.append(f"\n{' │ '.join(parts)}", style=MUTED)

    body.append(f"\nType your request, or 'exit' / Ctrl+D to quit. ESC to interrupt.", style=MUTED)

    panel = Panel(
        body,
        border_style=ACCENT_DIM,
        padding=(1, 2),
    )

    with console.capture() as capture:
        console.print(panel)
    return capture.get().rstrip("\n")
