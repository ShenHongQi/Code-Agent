"""三层权限分类 + 上下文感知 + 会话级记忆。"""

from __future__ import annotations
import re
import sys


class PermissionDenied(Exception):
    pass


# ─── 绝对禁止 ───────────────────────────────────────────────────────────────

BLOCKED_PATTERNS = [
    r"\brm\s+-[rf]*r[f]*\s+/\s*$",
    r"\brm\s+-[rf]*r[f]*\s+~/?\s*$",
    r"\bdd\b.*\bof=/dev/",
    r":\(\)\s*\{\s*:\|:\s*&\s*\}",  # fork bomb
    r"\bgit\s+push\s+.*--force\b",
    r"\bgit\s+push\s+-f\b",
    r"\bcurl\b.*\|\s*(ba)?sh\b",
    r"\bwget\b.*\|\s*(ba)?sh\b",
    r"\bsudo\s+rm\b",
    r"\bmkfs\b",
    r"\bformat\s+[Cc]:",
    r"\b:(){ :|:& };:",
]

# ─── 自动允许 ───────────────────────────────────────────────────────────────

SAFE_PATTERNS = [
    r"^\s*(ls|cat|head|tail|echo|printf)\b",
    r"^\s*(grep|egrep|fgrep|rg|ag)\b",
    r"^\s*(find|fd)\b",
    r"^\s*(wc|sort|uniq|diff|comm|cut|tr|awk|sed\s+-n)\b",
    r"^\s*(git\s+(status|diff|log|show|branch|tag|remote|rev-parse))\b",
    r"^\s*(python[23]?\s+(-c|-m|test)|pytest|python.*test)\b",
    r"^\s*(make\s+(test|check|lint)|cargo\s+(test|check|clippy))\b",
    r"^\s*(cd|pwd|env|which|type|file|stat|tree|du|df)\b",
    r"^\s*(node\s+-e|npx\s+jest|npm\s+test|yarn\s+test)\b",
    r"^\s*(uv\s+run|ruff|black|isort|mypy|flake8|pylint)\b",
    r"^\s*(go\s+(test|vet|build)|rustc\s+--edition)\b",
]

# ─── 需确认 ─────────────────────────────────────────────────────────────────

CONFIRM_PATTERNS = [
    r"\bgit\s+(commit|push|reset|checkout\s+--)\b",
    r"\b(pip|pip3)\s+install\b",
    r"\bnpm\s+install\b",
    r"\byarn\s+add\b",
    r"\b(curl|wget)\s+",
    r"\b(apt|apt-get|brew)\s+(install|remove|purge)\b",
    r"\brm\s+-[rf]*r[f]*\b",
    r"\brm\s+-f\b",
    r"\bchmod\b",
    r"\bchown\b",
    r"\bdocker\s+(run|rm|stop|kill)\b",
    r"\bkubectl\s+(apply|delete|exec)\b",
    r"\bsudo\b",
    r"\bmv\s+/",
    r"\bsystemctl\s+(start|stop|restart|enable|disable)\b",
]

# ─── 上下文感知：可再生目标自动降级 ────────────────────────────────────────

SAFE_DELETE_TARGETS = {
    "node_modules", "__pycache__", ".pytest_cache", "dist", "build",
    ".egg-info", ".mypy_cache", ".ruff_cache", ".tox", ".venv",
    "target", ".next", ".nuxt", ".output",
}


# ─── 会话级权限状态 ─────────────────────────────────────────────────────────

class PermissionState:
    """会话作用域的权限记忆。"""

    def __init__(self):
        self._session_allows: set[str] = set()

    def remember_allow(self, command: str) -> None:
        for pattern in CONFIRM_PATTERNS:
            if re.search(pattern, command):
                self._session_allows.add(pattern)
                return

    def is_session_approved(self, command: str) -> bool:
        for pattern in self._session_allows:
            if re.search(pattern, command):
                return True
        return False

    def reset(self) -> None:
        self._session_allows.clear()


_state = PermissionState()


def get_permission_state() -> PermissionState:
    return _state


# ─── 分类逻辑 ───────────────────────────────────────────────────────────────

def classify_command(command: str) -> str:
    """分类命令为 allow / confirm / block。"""
    # 1. 绝对禁止
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command):
            return "block"

    # 2. 安全命令
    for pattern in SAFE_PATTERNS:
        if re.search(pattern, command):
            return "allow"

    # 3. 上下文感知：rm 可再生目标
    rm_match = re.search(r"\brm\s+.*?[-/]?(\S+)\s*$", command)
    if rm_match:
        target = rm_match.group(1).rstrip("/").split("/")[-1]
        if target in SAFE_DELETE_TARGETS:
            return "allow"

    # 4. 需确认
    for pattern in CONFIRM_PATTERNS:
        if re.search(pattern, command):
            return "confirm"

    # 5. 默认允许
    return "allow"


# ─── 权限检查 ───────────────────────────────────────────────────────────────

RESET = "\033[0m"
BOLD = "\033[1m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
DIM = "\033[2m"


def check_permission(command: str, auto_approve: bool = False) -> None:
    """检查命令权限。block 抛异常，confirm 交互确认。"""
    level = classify_command(command)

    if level == "block":
        raise PermissionDenied(f"Command is blocked: {command}")

    if level == "confirm":
        if auto_approve:
            return
        if _state.is_session_approved(command):
            return
        _ask_confirmation(command)


def _ask_confirmation(command: str) -> None:
    """交互式三选项确认。"""
    import shutil
    width = shutil.get_terminal_size().columns
    sep = f"{YELLOW}{'─' * width}{RESET}"

    sys.stdout.write(f"\n{sep}\n")
    sys.stdout.write(f"{YELLOW}⚠ 需要确认:{RESET}\n")
    sys.stdout.write(f"  {BOLD}{command}{RESET}\n")
    sys.stdout.write(f"{sep}\n")
    sys.stdout.write(f"  {GREEN}[y]{RESET} 允许一次  {GREEN}[a]{RESET} 本次会话允许同类  {GREEN}[n]{RESET} 拒绝  > ")
    sys.stdout.flush()

    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        raise PermissionDenied("User denied.")

    if answer in ("y", "yes"):
        return
    elif answer in ("a", "all"):
        _state.remember_allow(command)
        return
    else:
        raise PermissionDenied("User denied.")
