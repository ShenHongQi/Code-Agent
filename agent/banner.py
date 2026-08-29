"""启动 Banner：Rich Panel + 渐变 MEGUMIN 艺术字。"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from agent.theme import MEGUMIN_THEME, PRIMARY, TEXT_MUTED, BORDER

LOGO_LINES = [
    "█   █ █████ █████ █   █ █   █ █ █   █",
    "██ ██ █     █     █   █ ██ ██ █ ██  █",
    "█ █ █ ████  █ ███ █   █ █ █ █ █ █ █ █",
    "█   █ █     █   █ █   █ █   █ █ █  ██",
    "█   █ █████ █████ █████ █   █ █ █   █",
]

# OpenCode 风格渐变：从主色调到暖金再回来
ROW_COLORS = ["#fab283", "#e5a070", "#d09060", "#e5a070", "#fab283"]

TAGLINE = "⚡ Explosion-class Coding Agent"


def render_banner(model: str = "", workspace: str = "") -> str:
    console = Console(theme=MEGUMIN_THEME, force_terminal=True)

    logo = Text()
    for i, line in enumerate(LOGO_LINES):
        logo.append(line, style=f"bold {ROW_COLORS[i]}")
        if i < len(LOGO_LINES) - 1:
            logo.append("\n")

    body = Text()
    body.append(logo)
    body.append(f"\n\n{TAGLINE}", style=f"italic {TEXT_MUTED}")

    if model or workspace:
        parts = []
        if model:
            parts.append(f"model: {model}")
        if workspace:
            parts.append(f"workspace: {workspace}")
        body.append(f"\n{' │ '.join(parts)}", style=TEXT_MUTED)

    body.append(f"\nType your request, or 'exit' / Ctrl+D to quit. ESC to interrupt.", style=TEXT_MUTED)

    panel = Panel(
        body,
        border_style=BORDER,
        padding=(1, 2),
    )

    with console.capture() as capture:
        console.print(panel)
    return capture.get().rstrip("\n")
