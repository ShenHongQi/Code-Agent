"""统一主题：Megumin (KonoSuba 惠惠) 配色方案。

色板：
  Primary:    #e05252 (深红橙)  — 惠惠斗篷色，assistant 消息左边框、链接、列表标记
  Secondary:  #5c9cf5 (蓝)      — user 消息左边框、标题
  Accent:     #9d7cd8 (紫)      — 粗体强调
  Muted:      #6a6a6a           — 工具调用、注释
  Border:     #4b4c5c           — 普通边框
"""

from rich.style import Style
from rich.theme import Theme

# ─── Megumin Dark Palette (KonoSuba 惠惠配色) ───
PRIMARY = "#e05252"        # 深红橙 — 惠惠斗篷/爆裂魔法色
SECONDARY = "#5c9cf5"      # 蓝 — 副色调
ACCENT = "#9d7cd8"         # 紫 — 第三色
TEXT = "#e0e0e0"           # 前景文字
TEXT_MUTED = "#6a6a6a"     # 灰色辅助
TEXT_EMPHASIZED = "#e5c07b" # 黄 — 强调
BG = "#212121"             # 背景
BG_SECONDARY = "#252525"   # 次背景
BG_DARKER = "#121212"      # 深背景
BORDER = "#4b4c5c"         # 普通边框
BORDER_FOCUSED = PRIMARY   # 聚焦边框 = 惠惠红
BORDER_DIM = "#303030"     # 暗淡边框

# 状态色
SUCCESS = "#7fd88f"
ERROR = "#e06c75"
WARNING = "#f5a742"
INFO = "#56b6c2"

# Markdown 专用
MD_HEADING = SECONDARY
MD_LINK = PRIMARY
MD_CODE = SUCCESS
MD_BLOCKQUOTE = TEXT_EMPHASIZED
MD_LIST = PRIMARY
MD_STRONG = ACCENT

# ─── Rich Theme ───
MEGUMIN_THEME = Theme({
    "primary": Style(color=PRIMARY, bold=True),
    "secondary": Style(color=SECONDARY, bold=True),
    "accent": Style(color=ACCENT, bold=True),
    "muted": Style(color=TEXT_MUTED),
    "text": Style(color=TEXT),
    "emphasized": Style(color=TEXT_EMPHASIZED),
    "success": Style(color=SUCCESS),
    "error": Style(color=ERROR, bold=True),
    "warning": Style(color=WARNING),
    "info": Style(color=INFO),
    "header": Style(color=SECONDARY, bold=True),
    "tool.name": Style(color=TEXT_MUTED, bold=True),
    "tool.args": Style(color=TEXT_MUTED),
    "tool.ok": Style(color=SUCCESS),
    "tool.fail": Style(color=ERROR),
    "thinking": Style(color=TEXT_MUTED, italic=True),
    "banner.logo": Style(color=PRIMARY, bold=True),
    "banner.tag": Style(color=TEXT_MUTED, italic=True),
    "banner.info": Style(color=TEXT_MUTED),
    "spinner": Style(color=PRIMARY),
    "border": Style(color=BORDER),
    "border.focused": Style(color=PRIMARY),
})

# ─── ANSI 常量（流式渲染用） ───
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
ITALIC = "\033[3m"

# 256-color 近似（终端流式输出用）
ANSI_PRIMARY = "\033[38;5;167m"    # #d75f5f ≈ #e05252
ANSI_SECONDARY = "\033[38;5;75m"   # #5fafff ≈ #5c9cf5
ANSI_ACCENT = "\033[38;5;140m"     # #af87d7 ≈ #9d7cd8
ANSI_MUTED = "\033[38;5;242m"      # #6c6c6c ≈ #6a6a6a
ANSI_SUCCESS = "\033[38;5;114m"    # #87d787 ≈ #7fd88f
ANSI_ERROR = "\033[38;5;168m"      # #d75f87 ≈ #e06c75
ANSI_WARNING = "\033[38;5;214m"    # #ffaf00 ≈ #f5a742
ANSI_INFO = "\033[38;5;73m"        # #5fafaf ≈ #56b6c2

# 向后兼容别名
ACCENT_ANSI = ANSI_PRIMARY
MUTED_ANSI = ANSI_MUTED
