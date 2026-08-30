"""权限系统：三层分类 + 风险等级 + 权限模式 + 递归解包。"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from enum import Enum


class PermissionDenied(Exception):
    pass


# ─── 枚举 ──────────────────────────────────────────────────────────────────

class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PermissionMode(Enum):
    SUGGEST = "suggest"
    AUTO_EDIT = "auto-edit"
    FULL_AUTO = "full-auto"


# ─── 绝对禁止（CRITICAL） ──────────────────────────────────────────────────

BLOCKED_PATTERNS = [
    r"\brm\s+-[rf]*r[f]*\s+/",
    r"\brm\s+-[rf]*r[f]*\s+~/",
    r"\brm\s+-[rf]*r[f]*\s+/\*",
    r"\bdd\b.*\bof=/dev/",
    r":\(\)\s*\{.*:\|:.*&.*\}",
    r"\bgit\s+push\s+.*--force\b",
    r"\bgit\s+push\s+-f\b",
    r"\bcurl\b.*\|\s*(ba)?sh\b",
    r"\bwget\b.*\|\s*(ba)?sh\b",
    r"\bsudo\s+rm\b",
    r"\bmkfs\b",
    r"\bformat\s+[Cc]:",
    r"\beval\b.*\brm\b",
]

# ─── 自动允许（LOW） ───────────────────────────────────────────────────────

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

# ─── 高风险（HIGH） ────────────────────────────────────────────────────────

HIGH_RISK_PATTERNS: list[tuple[str, str]] = [
    (r"\bgit\s+push\b", "推送代码到远程仓库"),
    (r"\bgit\s+reset\s+--hard\b", "硬重置 git 历史"),
    (r"\brm\s+-[rf]*r[f]*\b", "递归删除文件"),
    (r"\bsudo\b", "使用 sudo 提权"),
    (r"\bsystemctl\s+(start|stop|restart|enable|disable)\b", "管理系统服务"),
    (r"\bdocker\s+(rm|stop|kill)\b", "操作 Docker 容器"),
    (r"\bkubectl\s+(apply|delete|exec)\b", "操作 Kubernetes 集群"),
    (r"\b(apt|apt-get|brew)\s+(remove|purge)\b", "删除系统包"),
]

# ─── 中等风险（MEDIUM） ────────────────────────────────────────────────────

MEDIUM_RISK_PATTERNS: list[tuple[str, str]] = [
    (r"\bgit\s+commit\b", "提交代码"),
    (r"\bgit\s+checkout\s+--\b", "丢弃文件更改"),
    (r"\b(pip|pip3)\s+install\b", "安装 Python 包"),
    (r"\bnpm\s+install\b", "安装 npm 包"),
    (r"\byarn\s+add\b", "安装 yarn 包"),
    (r"\b(curl|wget)\s+", "网络请求"),
    (r"\bchmod\b", "修改文件权限"),
    (r"\bchown\b", "修改文件所有者"),
    (r"\bdocker\s+run\b", "运行 Docker 容器"),
    (r"\bmv\s+/", "移动系统路径文件"),
    (r"\brm\s+-f\b", "强制删除文件"),
    (r"\b(apt|apt-get|brew)\s+install\b", "安装系统包"),
]

# ─── 上下文感知 ────────────────────────────────────────────────────────────

SAFE_DELETE_TARGETS = {
    "node_modules", "__pycache__", ".pytest_cache", "dist", "build",
    ".egg-info", ".mypy_cache", ".ruff_cache", ".tox", ".venv",
    "target", ".next", ".nuxt", ".output",
}

# ─── 递归命令解包（参考 Codex is_dangerous_command） ──────────────────────

_WRAPPER_RE = [
    re.compile(r"^\s*sudo\s+(?:-\S+\s+)*"),
    re.compile(r"^\s*env\s+(?:\S+=\S+\s+)*"),
    re.compile(r"""^\s*(?:ba)?sh\s+-c\s+['"]?"""),
    re.compile(r"^\s*nohup\s+"),
    re.compile(r"^\s*nice\s+(?:-n\s+\d+\s+)?"),
    re.compile(r"^\s*timeout\s+\d+\s+"),
    re.compile(r"^\s*strace\s+(?:-\S+\s+)*"),
]


def unwrap_command(command: str) -> str:
    """递归解包 sudo/env/sh -c 等前缀，暴露真实命令。"""
    prev = None
    cmd = command.strip()
    while cmd != prev:
        prev = cmd
        for pat in _WRAPPER_RE:
            m = pat.match(cmd)
            if m:
                cmd = cmd[m.end():]
                if cmd and cmd[0] in ("'", '"'):
                    cmd = cmd[1:]
                cmd = cmd.rstrip("'\"").strip()
    return cmd


# ─── 分类结果 ──────────────────────────────────────────────────────────────

@dataclass
class Classification:
    action: str         # "allow" / "confirm" / "block"
    risk: RiskLevel
    rationale: str


_CHAIN_RE = re.compile(r'[|;&]|&&|\|\||`|\$\(')


def classify_command(command: str) -> Classification:
    """分类 bash 命令 → (action, risk, rationale)。"""
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command):
            return Classification("block", RiskLevel.CRITICAL, "危险操作被禁止")

    inner = unwrap_command(command)
    if inner != command:
        for pattern in BLOCKED_PATTERNS:
            if re.search(pattern, inner):
                return Classification("block", RiskLevel.CRITICAL, "解包后检测到危险操作")

    if not _CHAIN_RE.search(command):
        for pattern in SAFE_PATTERNS:
            if re.search(pattern, command):
                return Classification("allow", RiskLevel.LOW, "")

    rm_match = re.search(r"\brm\s+.*?[-/]?(\S+)\s*$", command)
    if rm_match:
        target = rm_match.group(1).rstrip("/").split("/")[-1]
        if target in SAFE_DELETE_TARGETS:
            return Classification("allow", RiskLevel.LOW, "可再生目标")

    for pattern, rationale in HIGH_RISK_PATTERNS:
        if re.search(pattern, command) or (inner != command and re.search(pattern, inner)):
            return Classification("confirm", RiskLevel.HIGH, rationale)

    for pattern, rationale in MEDIUM_RISK_PATTERNS:
        if re.search(pattern, command) or (inner != command and re.search(pattern, inner)):
            return Classification("confirm", RiskLevel.MEDIUM, rationale)

    return Classification("allow", RiskLevel.LOW, "")


def classify_tool_call(tool_name: str, args: dict) -> Classification:
    """非 bash 工具的风险分类。"""
    if tool_name in ("read_file", "list_dir"):
        return Classification("allow", RiskLevel.LOW, "")

    if tool_name == "write_file":
        path = args.get("path", "")
        return Classification("confirm", RiskLevel.MEDIUM, f"创建文件: {path}")

    if tool_name == "edit_file":
        path = args.get("path", "")
        return Classification("confirm", RiskLevel.LOW, f"编辑文件: {path}")

    if tool_name == "delete_file":
        path = args.get("path", "")
        return Classification("confirm", RiskLevel.HIGH, f"删除文件: {path}")

    if tool_name == "rename_file":
        old = args.get("old_path", "")
        new = args.get("new_path", "")
        return Classification("confirm", RiskLevel.MEDIUM, f"重命名: {old} → {new}")

    if tool_name == "web_fetch":
        url = args.get("url", "")
        return Classification("confirm", RiskLevel.MEDIUM, f"网络请求: {url}")

    return Classification("allow", RiskLevel.LOW, "")


# ─── 会话级权限状态 ─────────────────────────────────────────────────────────

class PermissionState:
    """会话作用域的权限记忆。"""

    def __init__(self):
        self._session_allows: set[str] = set()

    def remember_allow(self, command: str) -> None:
        for pattern, _ in HIGH_RISK_PATTERNS + MEDIUM_RISK_PATTERNS:
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


# ─── 权限模式管理 ──────────────────────────────────────────────────────────

_current_mode = PermissionMode.AUTO_EDIT


def get_permission_mode() -> PermissionMode:
    return _current_mode


def set_permission_mode(mode: PermissionMode) -> None:
    global _current_mode
    _current_mode = mode


def init_permission_mode() -> None:
    """从 config 初始化权限模式（启动时调用一次）。"""
    global _current_mode
    from agent.config import config
    mode_str = getattr(config, "permission_mode", "auto-edit")
    try:
        _current_mode = PermissionMode(mode_str)
    except ValueError:
        _current_mode = PermissionMode.AUTO_EDIT


# ─── 确认 UI ──────────────────────────────────────────────────────────────

RESET = "\033[0m"
BOLD = "\033[1m"
YELLOW = "\033[33m"
ORANGE = "\033[38;5;208m"
DIM = "\033[2m"

RISK_COLORS = {
    RiskLevel.LOW: "\033[32m",
    RiskLevel.MEDIUM: "\033[33m",
    RiskLevel.HIGH: "\033[38;5;208m",
    RiskLevel.CRITICAL: "\033[31m",
}

RISK_LABELS = {
    RiskLevel.LOW: "低风险",
    RiskLevel.MEDIUM: "中风险",
    RiskLevel.HIGH: "⚠ 高风险",
    RiskLevel.CRITICAL: "🚫 危险",
}


_spinner_pause_cb = None


def set_spinner_control(pause_cb) -> None:
    global _spinner_pause_cb
    _spinner_pause_cb = pause_cb


def interactive_confirm(description: str, detail: str,
                        risk: RiskLevel, options: list[tuple[str, str]]) -> str:
    """Arrow-key interactive permission prompt. Returns the chosen option key."""
    import shutil

    risk_color = RISK_COLORS.get(risk, YELLOW)
    risk_label = RISK_LABELS.get(risk, "")

    if _spinner_pause_cb:
        _spinner_pause_cb()

    width = shutil.get_terminal_size().columns
    detail_max = width - 6
    detail_short = detail[:detail_max] + ("…" if len(detail) > detail_max else "")

    if not sys.stdin.isatty() or os.name == "nt":
        sys.stdout.write(f"\n  {risk_color}{risk_label}{RESET}")
        if description:
            sys.stdout.write(f" — {description}")
        sys.stdout.write(f"\n    {BOLD}{detail_short}{RESET}\n")
        for i, (_, label) in enumerate(options):
            sys.stdout.write(f"    {i + 1}. {label}\n")
        sys.stdout.write("  > ")
        sys.stdout.flush()
        try:
            answer = input().strip()
            idx = int(answer) - 1
            if 0 <= idx < len(options):
                return options[idx][0]
        except (ValueError, EOFError, KeyboardInterrupt):
            pass
        return "deny"

    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    selected = 0
    total = len(options)
    render_lines = 2 + total

    def _draw():
        sys.stdout.write(f"\033[{render_lines}A\r\033[J")
        sys.stdout.write(f"  {risk_color}{risk_label}{RESET}")
        if description:
            sys.stdout.write(f" — {description}")
        sys.stdout.write("\n")
        sys.stdout.write(f"    {BOLD}{detail_short}{RESET}\n")
        for i, (_, label) in enumerate(options):
            if i == selected:
                sys.stdout.write(f"  {BOLD}{risk_color}❯ {label}{RESET}\n")
            else:
                sys.stdout.write(f"  {DIM}  {label}{RESET}\n")
        sys.stdout.flush()

    def _collapse(chosen_label: str):
        sys.stdout.write(f"\033[{render_lines}A\r\033[J")
        sys.stdout.write(f"  {risk_color}{risk_label}{RESET} {detail_short} {DIM}→ {chosen_label}{RESET}\n")
        sys.stdout.flush()

    try:
        tty.setcbreak(fd)

        sys.stdout.write(f"  {risk_color}{risk_label}{RESET}")
        if description:
            sys.stdout.write(f" — {description}")
        sys.stdout.write("\n")
        sys.stdout.write(f"    {BOLD}{detail_short}{RESET}\n")
        for i, (_, label) in enumerate(options):
            if i == selected:
                sys.stdout.write(f"  {BOLD}{risk_color}❯ {label}{RESET}\n")
            else:
                sys.stdout.write(f"  {DIM}  {label}{RESET}\n")
        sys.stdout.flush()

        while True:
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                seq = sys.stdin.read(2)
                if seq == "[A":
                    selected = (selected - 1) % total
                    _draw()
                elif seq == "[B":
                    selected = (selected + 1) % total
                    _draw()
            elif ch in ("\r", "\n"):
                chosen_key, chosen_label = options[selected]
                _collapse(chosen_label)
                return chosen_key
            elif ch == "\x03":
                _collapse("denied")
                return "deny"

    except (termios.error, OSError, KeyboardInterrupt):
        try:
            _collapse("denied")
        except Exception:
            pass
        return "deny"
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except (termios.error, OSError):
            pass


def _ask_confirmation(command: str, risk: RiskLevel, rationale: str) -> None:
    options = [
        ("once", "允许一次"),
        ("all", "本次会话允许同类"),
        ("deny", "拒绝"),
    ]
    choice = interactive_confirm(rationale, command, risk, options)
    if choice == "once":
        return
    elif choice == "all":
        _state.remember_allow(command)
        return
    raise PermissionDenied("User denied.")


def _ask_tool_confirmation(tool_name: str, args: dict,
                           risk: RiskLevel, rationale: str) -> None:
    detail = tool_name
    if "path" in args:
        detail += f"  {args['path']}"
    elif "url" in args:
        detail += f"  {args['url']}"
    options = [
        ("once", "允许"),
        ("deny", "拒绝"),
    ]
    choice = interactive_confirm(rationale, detail, risk, options)
    if choice == "once":
        return
    raise PermissionDenied("User denied.")


# ─── 权限检查入口 ──────────────────────────────────────────────────────────

def check_permission(command: str, auto_approve: bool = False) -> None:
    """检查 bash 命令权限。block → 抛异常，confirm → 按模式处理。"""
    result = classify_command(command)

    if result.action == "block":
        raise PermissionDenied(f"Command is blocked: {command}")

    if result.action == "confirm":
        if auto_approve:
            return
        from agent.skills import is_auto_approve
        if is_auto_approve():
            return
        if _state.is_session_approved(command):
            return

        mode = _current_mode
        if mode == PermissionMode.FULL_AUTO and result.risk in (RiskLevel.LOW, RiskLevel.MEDIUM):
            return

        _ask_confirmation(command, result.risk, result.rationale)


def check_tool_permission(tool_name: str, args: dict) -> None:
    """检查非 bash 工具权限（文件写入/删除/网络等）。"""
    result = classify_tool_call(tool_name, args)

    if result.action == "block":
        raise PermissionDenied(f"Tool blocked: {tool_name}")

    if result.action != "confirm":
        return

    from agent.skills import is_auto_approve
    if is_auto_approve():
        return

    mode = _current_mode

    if mode == PermissionMode.AUTO_EDIT:
        if tool_name in ("write_file", "edit_file", "delete_file", "rename_file"):
            return
        _ask_tool_confirmation(tool_name, args, result.risk, result.rationale)
        return

    if mode == PermissionMode.FULL_AUTO:
        if result.risk in (RiskLevel.LOW, RiskLevel.MEDIUM):
            return
        _ask_tool_confirmation(tool_name, args, result.risk, result.rationale)
        return

    # SUGGEST: 全部需要确认
    _ask_tool_confirmation(tool_name, args, result.risk, result.rationale)
