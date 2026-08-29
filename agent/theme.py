"""统一主题：颜色、样式常量。基于 Rich Style 系统。"""

from rich.style import Style
from rich.theme import Theme

# ─── 品牌色 ───
ACCENT = "#ff5f00"       # 橙色主色调
ACCENT_DIM = "#af5f00"   # 暗橙
ACCENT_BRIGHT = "#ff8700" # 亮橙
MUTED = "#6c6c6c"        # 灰色辅助文字
SUCCESS = "#5faf5f"       # 绿色成功
ERROR = "#d75f5f"         # 红色错误
WARNING = "#d7af00"       # 黄色警告
INFO = "#5f87af"          # 蓝色信息
CODE_BG = "#1c1c1c"       # 代码块背景

# ─── Rich Theme ───
MEGUMIN_THEME = Theme({
    "accent": Style(color=ACCENT, bold=True),
    "accent.dim": Style(color=ACCENT_DIM),
    "accent.bright": Style(color=ACCENT_BRIGHT),
    "muted": Style(color=MUTED),
    "success": Style(color=SUCCESS),
    "error": Style(color=ERROR, bold=True),
    "warning": Style(color=WARNING),
    "info": Style(color=INFO),
    "header": Style(color=ACCENT, bold=True),
    "tool.name": Style(color=ACCENT_DIM, bold=True),
    "tool.args": Style(color=MUTED),
    "tool.ok": Style(color=SUCCESS),
    "tool.fail": Style(color=ERROR),
    "thinking": Style(color=MUTED, italic=True),
    "banner.logo": Style(color=ACCENT, bold=True),
    "banner.tag": Style(color=MUTED, italic=True),
    "banner.info": Style(color=MUTED),
    "spinner": Style(color=ACCENT),
})

# ─── 旧 ANSI 常量（向后兼容过渡期使用） ───
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
ORANGE = "\033[38;5;208m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
