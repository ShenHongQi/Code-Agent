"""跨会话记忆管理：全局记忆 + 项目记忆。"""

from __future__ import annotations

from pathlib import Path

GLOBAL_MEMORY_DIR = Path.home() / ".megumin" / "memory"
GLOBAL_MEMORY_FILE = GLOBAL_MEMORY_DIR / "global.md"
PROJECT_MEMORY_DIR = ".megumin"
PROJECT_MEMORY_FILE = "memory.md"

MAX_GLOBAL_SIZE = 3000
MAX_PROJECT_SIZE = 6000


class MemoryManager:
    """管理全局和项目级记忆的读写。"""

    def __init__(self, workspace: str):
        self._workspace = Path(workspace)
        self._project_file = self._workspace / PROJECT_MEMORY_DIR / PROJECT_MEMORY_FILE
        self._global_mtime: float = 0.0
        self._project_mtime: float = 0.0

    def load_global(self) -> str:
        try:
            return GLOBAL_MEMORY_FILE.read_text(encoding="utf-8").strip()
        except (OSError, FileNotFoundError):
            return ""

    def load_project(self) -> str:
        try:
            return self._project_file.read_text(encoding="utf-8").strip()
        except (OSError, FileNotFoundError):
            return ""

    def append(self, entry: str, scope: str = "project") -> None:
        """追加一条记忆条目。"""
        entry = entry.strip()
        if not entry:
            return

        if scope == "global":
            self._append_to_file(GLOBAL_MEMORY_FILE, entry, MAX_GLOBAL_SIZE)
        else:
            self._append_to_file(self._project_file, entry, MAX_PROJECT_SIZE)

    def remove(self, keyword: str, scope: str = "project") -> bool:
        """删除包含关键词的记忆行。返回是否有删除。"""
        target = GLOBAL_MEMORY_FILE if scope == "global" else self._project_file
        if not target.exists():
            return False

        lines = target.read_text(encoding="utf-8").splitlines()
        filtered = [line for line in lines if keyword.lower() not in line.lower()]

        if len(filtered) == len(lines):
            return False

        target.write_text("\n".join(filtered) + "\n", encoding="utf-8")
        return True

    def read(self, scope: str = "project") -> str:
        if scope == "global":
            return self.load_global()
        return self.load_project()

    def get_mtime(self) -> tuple[float, float]:
        """返回 (global_mtime, project_mtime)，文件不存在返回 0。"""
        g = self._safe_mtime(GLOBAL_MEMORY_FILE)
        p = self._safe_mtime(self._project_file)
        return (g, p)

    def has_changed(self) -> bool:
        """检查 mtime 是否自上次检查以来有变化。"""
        g, p = self.get_mtime()
        changed = (g != self._global_mtime or p != self._project_mtime)
        self._global_mtime = g
        self._project_mtime = p
        return changed

    def _append_to_file(self, path: Path, entry: str, max_size: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

        existing = ""
        if path.exists():
            existing = path.read_text(encoding="utf-8")

        new_content = existing.rstrip() + "\n- " + entry + "\n"

        if len(new_content) > max_size:
            lines = new_content.splitlines()
            while len("\n".join(lines)) > max_size and len(lines) > 5:
                # 移除最早的非标题行
                for i, line in enumerate(lines):
                    if not line.startswith("#") and line.strip():
                        lines.pop(i)
                        break
                else:
                    break

            new_content = "\n".join(lines) + "\n"

        path.write_text(new_content, encoding="utf-8")

    @staticmethod
    def _safe_mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except (OSError, FileNotFoundError):
            return 0.0
