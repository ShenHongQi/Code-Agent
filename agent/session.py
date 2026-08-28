"""会话持久化：保存/恢复/清理。"""

from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SESSIONS_DIR = Path.home() / ".megumin" / "sessions"
MAX_SESSIONS = 20
MAX_SESSION_SIZE = 2 * 1024 * 1024  # 2MB


class SessionManager:
    """管理会话的序列化、反序列化和清理。"""

    def __init__(self):
        self._sessions_dir = SESSIONS_DIR
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

    def save(self, messages: list[dict[str, Any]], meta: dict[str, Any]) -> Path:
        """保存会话到 JSON 文件，返回文件路径。"""
        session_id = meta.get("session_id", "unknown")
        path = self._sessions_dir / f"{session_id}.json"

        meta["updated_at"] = datetime.now(timezone.utc).isoformat()

        data = {"meta": meta, "messages": messages}
        content = json.dumps(data, ensure_ascii=False, indent=None)

        # 文件过大时只保留最后 10 轮
        if len(content) > MAX_SESSION_SIZE:
            messages = self._trim_messages(messages, keep_turns=10)
            data["messages"] = messages
            content = json.dumps(data, ensure_ascii=False, indent=None)

        path.write_text(content, encoding="utf-8")
        return path

    def load(self, session_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """加载指定会话，返回 (messages, meta)。"""
        path = self._sessions_dir / f"{session_id}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return data["messages"], data["meta"]

    def latest_for_workspace(self, workspace: str) -> dict[str, Any] | None:
        """查找该 workspace 最近的会话 meta，无则返回 None。"""
        ws_hash = self._workspace_hash(workspace)
        candidates: list[tuple[str, dict]] = []

        for f in self._sessions_dir.glob(f"{ws_hash}_*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                meta = data.get("meta", {})
                candidates.append((meta.get("updated_at", ""), meta))
            except (json.JSONDecodeError, OSError):
                continue

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    def cleanup(self) -> None:
        """只保留最近 MAX_SESSIONS 个会话文件。"""
        files = sorted(
            self._sessions_dir.glob("*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        for f in files[MAX_SESSIONS:]:
            try:
                f.unlink()
            except OSError:
                pass

    @staticmethod
    def create_session_id(workspace: str) -> str:
        ws_hash = SessionManager._workspace_hash(workspace)
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        return f"{ws_hash}_{ts}"

    @staticmethod
    def _workspace_hash(workspace: str) -> str:
        return hashlib.sha1(workspace.encode()).hexdigest()[:8]

    @staticmethod
    def _trim_messages(messages: list[dict[str, Any]], keep_turns: int) -> list[dict[str, Any]]:
        """保留最后 N 轮用户消息及其后续消息。"""
        user_indices = [i for i, m in enumerate(messages) if m.get("role") == "user"]
        if len(user_indices) <= keep_turns:
            return messages
        start = user_indices[-keep_turns]
        return messages[start:]
