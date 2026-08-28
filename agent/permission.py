"""危险操作三级分级与确认门。"""

from __future__ import annotations
import re
import sys

# 直接阻断的模式
BLOCKED_PATTERNS = [
    r"\brm\s+-rf\s+/",
    r"\brm\s+-rf\s+~",
    r"\bdd\s+.*of=/dev/",
    r":\(\)\s*\{\s*:\|:\s*&\s*\};\s*:",  # fork bomb
    r"\bgit\s+push\s+.*--force",
    r"\bgit\s+push\s+-f\b",
    r"\bcurl\s+.*\|\s*sh",
    r"\bcurl\s+.*\|\s*bash",
    r"\bwget\s+.*\|\s*sh",
    r"\bsudo\s+rm\b",
    r"\bmkfs\b",
    r"\bformat\s+[cCdD]:",
]

# 需确认的模式
CONFIRM_PATTERNS = [
    r"\bgit\s+commit\b",
    r"\bgit\s+push\b",
    r"\bgit\s+reset\b",
    r"\bgit\s+checkout\s+--\b",
    r"\bpip\s+install\b",
    r"\bnpm\s+install\b",
    r"\byarn\s+add\b",
    r"\bcurl\b",
    r"\bwget\b",
    r"\bapt\b",
    r"\bbrew\s+install\b",
    r"\brm\s+-[rf]*r[f]*\b",
    r"\brm\s+-[rf]*f[r]*\b",
    r"\bchmod\b",
    r"\bchown\b",
]

# 自动放行的模式（匹配这些就直接放行，不再检查 CONFIRM）
SAFE_PATTERNS = [
    r"^\s*ls\b",
    r"^\s*cat\b",
    r"^\s*head\b",
    r"^\s*tail\b",
    r"^\s*echo\b",
    r"^\s*grep\b",
    r"^\s*find\b",
    r"^\s*wc\b",
    r"^\s*sort\b",
    r"^\s*diff\b",
    r"^\s*git\s+(status|diff|log|show|branch)\b",
    r"^\s*python[23]?\s+.*-[cm]\b",
    r"^\s*pytest\b",
    r"^\s*python[23]?\s+.*test",
    r"^\s*make\s+(test|check|lint)\b",
    r"^\s*cd\b",
    r"^\s*pwd\b",
    r"^\s*env\b",
    r"^\s*which\b",
    r"^\s*type\b",
    r"^\s*file\b",
    r"^\s*stat\b",
    r"^\s*tree\b",
]


class PermissionDenied(Exception):
    pass


def classify_command(command: str) -> str:
    """分类命令：'allow' / 'confirm' / 'block'。"""
    # Check blocked first
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command):
            return "block"

    # Check safe patterns
    for pattern in SAFE_PATTERNS:
        if re.search(pattern, command):
            return "allow"

    # Check confirm patterns
    for pattern in CONFIRM_PATTERNS:
        if re.search(pattern, command):
            return "confirm"

    # Default: allow (most dev commands are safe)
    return "allow"


def check_permission(command: str, auto_approve: bool = False) -> None:
    """检查命令权限。blocked 直接拒绝；confirm 需用户确认。"""
    level = classify_command(command)

    if level == "block":
        raise PermissionDenied(
            f"Command blocked for safety: {command}\n"
            "This command pattern is considered dangerous and cannot be executed."
        )

    if level == "confirm" and not auto_approve:
        _ask_confirmation(command)


def _ask_confirmation(command: str) -> None:
    """交互式确认。"""
    sys.stdout.write(f"\n\033[33m⚠ Command requires confirmation:\033[0m\n")
    sys.stdout.write(f"  {command}\n")
    sys.stdout.write(f"\033[33mAllow? [y/N]: \033[0m")
    sys.stdout.flush()
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        raise PermissionDenied("User denied command execution.")
    if answer not in ("y", "yes"):
        raise PermissionDenied("User denied command execution.")
