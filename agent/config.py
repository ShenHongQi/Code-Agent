"""只读配置对象，全部从环境变量读取。"""

import os


class Config:
    def __init__(self):
        self.api_key: str = os.environ.get("AGENT_API_KEY", "")
        self.base_url: str = os.environ.get(
            "AGENT_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"
        )
        self.model: str = os.environ.get("AGENT_MODEL", "glm-4-flash")
        self.transport: str = os.environ.get("AGENT_TRANSPORT", "sdk")

        self.max_iterations: int = int(os.environ.get("AGENT_MAX_ITERATIONS", "40"))
        self.max_output_tokens: int = int(
            os.environ.get("AGENT_MAX_OUTPUT_TOKENS", "8192")
        )
        self.context_limit: int = int(
            os.environ.get("AGENT_CONTEXT_LIMIT", "0")
        )  # 0 = use provider default

        self.workspace: str = os.environ.get("AGENT_WORKSPACE", os.getcwd())
        self.no_stream: bool = os.environ.get("AGENT_NO_STREAM", "").lower() in (
            "1",
            "true",
            "yes",
        )

    @property
    def usable_context(self) -> int:
        if self.context_limit > 0:
            return self.context_limit
        return 128_000  # conservative default for DeepSeek


config = Config()
