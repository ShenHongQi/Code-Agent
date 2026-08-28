"""路径收敛 + FileRegistry 文件新鲜度追踪。"""

from __future__ import annotations
import hashlib
import os
from pathlib import Path

from agent.config import config

SENSITIVE_PATTERNS = (
    ".env", ".env.", ".pem", "id_rsa", "id_ed25519",
    ".git/config", "credentials", ".netrc", ".npmrc",
)


def _is_sensitive(name: str) -> bool:
    lower = name.lower()
    for pat in SENSITIVE_PATTERNS:
        if pat in lower:
            return True
    return False


class WorkspaceError(Exception):
    pass


class Workspace:
    def __init__(self, root: str | None = None):
        self.root = Path(root or config.workspace).resolve()

    def resolve(self, path: str) -> Path:
        """将相对/绝对路径收敛到 workspace 内，返回 resolved 绝对路径。"""
        candidate = (self.root / path).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise WorkspaceError(
                f"Path escapes workspace: {path!r} resolves to {candidate}"
            )
        return candidate

    def check_sensitive(self, path: Path) -> None:
        if _is_sensitive(path.name) or _is_sensitive(str(path.relative_to(self.root))):
            raise WorkspaceError(f"Access denied: {path.name} is a sensitive file")

    def relative(self, path: Path) -> str:
        return str(path.relative_to(self.root))


class FileRecord:
    __slots__ = ("mtime", "size", "hash")

    def __init__(self, mtime: float, size: int, content_hash: str):
        self.mtime = mtime
        self.size = size
        self.hash = content_hash


class FileRegistry:
    """追踪已读文件的 mtime，用于 edit 前检测外部修改。"""

    def __init__(self):
        self._records: dict[str, FileRecord] = {}

    def register_read(self, path: Path, content: bytes) -> None:
        stat = path.stat()
        h = hashlib.md5(content, usedforsecurity=False).hexdigest()
        self._records[str(path)] = FileRecord(stat.st_mtime, stat.st_size, h)

    def check_freshness(self, path: Path) -> str | None:
        """返回 None 表示新鲜；返回错误描述表示文件已被外部修改。"""
        key = str(path)
        if key not in self._records:
            return f"File not yet read. Use read_file first."
        record = self._records[key]
        try:
            stat = path.stat()
        except FileNotFoundError:
            return "File no longer exists on disk."
        if stat.st_mtime != record.mtime or stat.st_size != record.size:
            return (
                "File was modified externally since last read. "
                "Use read_file to see current content before editing."
            )
        return None

    def update_after_write(self, path: Path, content: bytes) -> None:
        stat = path.stat()
        h = hashlib.md5(content, usedforsecurity=False).hexdigest()
        self._records[str(path)] = FileRecord(stat.st_mtime, stat.st_size, h)

    def has_record(self, path: str) -> bool:
        return path in self._records
