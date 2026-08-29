"""只读配置对象，从 ~/.megumin/config 和环境变量读取。"""

import os
from pathlib import Path


def _load_config_file() -> dict[str, str]:
    """从 ~/.megumin/config 读取持久化配置。"""
    config_path = Path.home() / ".megumin" / "config"
    values: dict[str, str] = {}
    if config_path.exists():
        for line in config_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    return values


def _get(key: str, default: str, file_values: dict[str, str]) -> str:
    """优先级：环境变量 > ~/.megumin/config > 默认值。"""
    return os.environ.get(key) or file_values.get(key) or default


class Config:
    def __init__(self):
        fv = _load_config_file()

        self.api_key: str = _get("AGENT_API_KEY", "", fv)
        self.base_url: str = _get(
            "AGENT_BASE_URL", "https://open.bigmodel.cn/api/paas/v4", fv
        )
        self.model: str = _get("AGENT_MODEL", "glm-4-flash", fv)
        self.transport: str = _get("AGENT_TRANSPORT", "sdk", fv)

        self.max_iterations: int = int(_get("AGENT_MAX_ITERATIONS", "60", fv))
        self.max_output_tokens: int = int(_get("AGENT_MAX_OUTPUT_TOKENS", "8192", fv))
        self.context_limit: int = int(_get("AGENT_CONTEXT_LIMIT", "0", fv))

        self.workspace: str = os.environ.get("AGENT_WORKSPACE", os.getcwd())
        self.no_stream: bool = _get("AGENT_NO_STREAM", "", fv).lower() in (
            "1", "true", "yes",
        )
        self.parallel_tools: bool = _get("AGENT_PARALLEL_TOOLS", "true", fv).lower() in (
            "1", "true", "yes",
        )
        self.plugins_enabled: bool = _get("AGENT_PLUGINS", "true", fv).lower() in (
            "1", "true", "yes",
        )
        self.reflection_enabled: bool = _get("AGENT_REFLECTION", "true", fv).lower() in (
            "1", "true", "yes",
        )
        self.permission_mode: str = _get("AGENT_PERMISSION_MODE", "auto-edit", fv)

    @property
    def usable_context(self) -> int:
        if self.context_limit > 0:
            return self.context_limit
        return 128_000


config = Config()
