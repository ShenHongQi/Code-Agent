"""CLI 入口、参数解析、REPL 主循环。"""

from __future__ import annotations
import argparse
import sys

from agent.config import config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="megumin",
        description="Megumin - A coding agent that reads/writes files and executes commands.",
    )
    parser.add_argument(
        "--workspace", "-w",
        help="Workspace directory (default: cwd)",
    )
    parser.add_argument(
        "--model", "-m",
        help="Model name to use",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Disable streaming output",
    )
    parser.add_argument(
        "--context-limit",
        type=int,
        help="Force a context token limit (for testing compaction)",
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="Initial prompt (if not given, enters interactive mode)",
    )
    return parser.parse_args()


def _first_run_setup() -> None:
    """首次启动时交互式配置 API Key，保存到 ~/.megumin/config。"""
    from pathlib import Path

    config_dir = Path.home() / ".megumin"
    config_file = config_dir / "config"

    print("\n🔥 Megumin Coding Agent — 首次启动配置")
    print("=" * 42)
    print()
    print("默认使用智谱 GLM-4-Flash（免费模型）")
    print("申请 API Key: https://open.bigmodel.cn/")
    print()

    api_key = input("请输入 API Key: ").strip()
    if not api_key:
        return

    print()
    print("选择模型 provider:")
    print("  1. 智谱 GLM-4-Flash (免费，默认)")
    print("  2. DeepSeek")
    print("  3. OpenAI")
    print("  4. 自定义")
    choice = input("选择 [1]: ").strip() or "1"

    providers = {
        "1": ("https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
        "2": ("https://api.deepseek.com/v1", "deepseek-chat"),
        "3": ("https://api.openai.com/v1", "gpt-4o"),
    }

    if choice in providers:
        base_url, model = providers[choice]
    else:
        base_url = input("API Base URL: ").strip()
        model = input("模型名称: ").strip()

    config_dir.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        f"AGENT_API_KEY={api_key}\n"
        f"AGENT_BASE_URL={base_url}\n"
        f"AGENT_MODEL={model}\n"
    )
    config_file.chmod(0o600)

    print()
    print(f"✅ 配置已保存到 {config_file}")
    print(f"   模型: {model}")
    print()


def main() -> None:
    args = parse_args()

    # Apply CLI overrides to config
    if args.workspace:
        config.workspace = args.workspace
    if args.model:
        config.model = args.model
    if args.no_stream:
        config.no_stream = True
    if args.context_limit:
        config.context_limit = args.context_limit

    # 首次启动：交互式配置 API Key
    if not config.api_key:
        _first_run_setup()
        # Reload config after setup
        from agent.config import Config
        new_cfg = Config()
        config.api_key = new_cfg.api_key
        config.base_url = new_cfg.base_url
        config.model = new_cfg.model
        if not config.api_key:
            print("Error: API Key 未配置，无法启动。", file=sys.stderr)
            sys.exit(1)

    # Initialize subsystems
    from agent.workspace import Workspace, FileRegistry
    from agent.tools import fs, search, bash, todo, task  # noqa: F401 - register tools
    from agent.llm import create_provider
    from agent.history import History
    from agent.prompts import build_system_prompt
    from agent.ui import UI
    from agent.loop import run_loop

    workspace = Workspace(config.workspace)
    registry = FileRegistry()

    fs.init(workspace, registry)
    search.init(workspace)
    bash.init(workspace)

    provider = create_provider()
    task.init(workspace, provider, depth=0)

    system_prompt = build_system_prompt(str(workspace.root))
    history = History(system_prompt)
    ui = UI(stream=not config.no_stream)

    ui.info(f"🔥 Megumin | model: {config.model} | workspace: {workspace.root}")
    ui.info("Type your request, or 'exit' / Ctrl+D to quit.\n")

    # One-shot mode
    initial_prompt = " ".join(args.prompt) if args.prompt else None
    if initial_prompt:
        _run_turn(initial_prompt, history, provider, ui)
        return

    # Interactive REPL
    while True:
        try:
            ui.user_prompt()
            user_input = input().strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "/exit", "/quit"):
            print("Goodbye!")
            break

        _run_turn(user_input, history, provider, ui)


def _run_turn(user_input: str, history, provider, ui) -> None:
    from agent.history import make_user
    from agent.loop import run_loop

    history.append(make_user(user_input))

    try:
        result = run_loop(history, provider, ui)
    except KeyboardInterrupt:
        history.seal_pending_tool_calls()
        ui.warning("\nInterrupted.")
        return

    if result.reason == "max_iterations":
        ui.warning(f"\nReached iteration limit ({result.iterations}). You can continue the conversation.")
    elif result.reason == "context_exhausted":
        ui.error("Context window exhausted. Consider starting a new session.")
    elif result.reason == "fatal_error":
        ui.error("A fatal error occurred. Check your API key and configuration.")


if __name__ == "__main__":
    main()
