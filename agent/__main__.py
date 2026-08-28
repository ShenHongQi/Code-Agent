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
        "--new-session",
        action="store_true",
        help="Force a new session (skip recovery prompt)",
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


def _try_resume_session(session_mgr, workspace_root: str, system_prompt: str):
    """尝试恢复上次会话，返回 (History, session_meta) 或 (None, None)。"""
    from agent.history import History

    meta = session_mgr.latest_for_workspace(workspace_root)
    if not meta:
        return None, None

    updated = meta.get("updated_at", "")[:16].replace("T", " ")
    turns = meta.get("turns", 0)
    summary = meta.get("summary", "")[:80]

    print(f"  检测到上次会话 ({updated}, {turns} 轮)")
    if summary:
        print(f"  摘要: {summary}")
    print()

    try:
        choice = input("  [r] 恢复上次会话  [n] 新建  > ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        choice = "n"

    if choice == "r":
        try:
            messages, loaded_meta = session_mgr.load(meta["session_id"])
            history = History.from_serializable(system_prompt, messages)
            print(f"  ✅ 已恢复 {len(messages)} 条消息\n")
            return history, loaded_meta
        except (OSError, KeyError, ValueError) as e:
            print(f"  ⚠ 恢复失败: {e}，启动新会话\n")

    return None, None


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
    from agent.tools import memory as memory_tool  # noqa: F401 - register memory tools
    from agent.tools import diff, proc, web, control  # noqa: F401 - register new tools
    from agent.llm import create_provider
    from agent.history import History
    from agent.prompts import build_system_prompt
    from agent.memory import MemoryManager
    from agent.session import SessionManager
    from agent.ui import UI
    from agent.loop import run_loop
    from agent.terminal import InputManager, EscDetector, EscInterrupt

    workspace = Workspace(config.workspace)
    registry = FileRegistry()

    fs.init(workspace, registry)
    search.init(workspace)
    bash.init(workspace)
    diff.init(workspace, registry)
    proc.init(workspace)

    # Memory system
    memory_mgr = MemoryManager(str(workspace.root))
    memory_tool.init(memory_mgr)

    # Session system
    session_mgr = SessionManager()

    provider = create_provider()
    task.init(workspace, provider, depth=0)

    # Plugin system
    if config.plugins_enabled:
        from agent.plugins import discover_plugins, load_plugin
        plugin_files = discover_plugins(str(workspace.root))
        for pf in plugin_files:
            manifest = load_plugin(pf, workspace)
            if manifest:
                ui_msg = f"  Plugin: {manifest.name} (+{', '.join(manifest.tools_added)})"
                print(f"\033[2m{ui_msg}\033[0m")

    system_prompt = build_system_prompt(str(workspace.root), memory_mgr)

    # Initialize memory mtime tracking
    memory_mgr.has_changed()

    ui = UI(stream=not config.no_stream)
    input_mgr = InputManager()

    ui.info(f"🔥 Megumin | model: {config.model} | workspace: {workspace.root}")
    ui.info("Type your request, or 'exit' / Ctrl+D to quit. ESC to interrupt.\n")

    # Session recovery
    history = None
    session_meta = None

    if not args.new_session:
        history, session_meta = _try_resume_session(
            session_mgr, str(workspace.root), system_prompt
        )

    if history is None:
        history = History(system_prompt)
        session_id = SessionManager.create_session_id(str(workspace.root))
        session_meta = {
            "session_id": session_id,
            "workspace": str(workspace.root),
            "model": config.model,
            "created_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
            "turns": 0,
            "summary": "",
        }

    # One-shot mode
    initial_prompt = " ".join(args.prompt) if args.prompt else None
    if initial_prompt:
        _run_turn(initial_prompt, history, provider, ui, memory_mgr, str(workspace.root))
        _save_session(session_mgr, history, session_meta)
        input_mgr.save_history()
        return

    # Interactive REPL
    prefill = ""
    thinking_history: list[str] = []

    while True:
        try:
            user_input = input_mgr.styled_input(prefill=prefill, model=config.model)
            prefill = ""
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            _save_session(session_mgr, history, session_meta)
            input_mgr.save_history()
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "/exit", "/quit"):
            print("Goodbye!")
            _save_session(session_mgr, history, session_meta)
            input_mgr.save_history()
            break

        # /think 命令：展开上一轮的中间思考
        if user_input.lower() in ("/think", "/thinking"):
            ui.show_full_thinking(thinking_history)
            continue

        # 新一轮对话：清空思考记录
        thinking_history.clear()

        # Run with ESC detection
        esc_detector = EscDetector()
        esc_detector.start()
        try:
            _run_turn(user_input, history, provider, ui, memory_mgr, str(workspace.root),
                      esc_detector.event, thinking_history)
        except EscInterrupt:
            prefill = user_input
            ui.warning("\n⚠ Interrupted (ESC). Edit and re-send.")
        except KeyboardInterrupt:
            history.seal_pending_tool_calls()
            ui.warning("\nInterrupted.")
        finally:
            esc_detector.stop()

        # Auto-save after each turn
        session_meta["turns"] = session_meta.get("turns", 0) + 1
        _save_session(session_mgr, history, session_meta)

    # Cleanup old sessions
    session_mgr.cleanup()


def _run_turn(user_input: str, history, provider, ui, memory_mgr=None,
              workspace_root=None, interrupt_event=None,
              thinking_log: list[str] | None = None) -> None:
    from agent.history import make_user
    from agent.loop import run_loop
    from agent.terminal import EscInterrupt

    history.append(make_user(user_input))

    result = run_loop(
        history, provider, ui,
        interrupt_event=interrupt_event,
        memory_mgr=memory_mgr,
        workspace_root=workspace_root,
        thinking_log=thinking_log,
    )

    if result.reason == "max_iterations":
        ui.warning(f"\nReached iteration limit ({result.iterations}). You can continue the conversation.")
    elif result.reason == "context_exhausted":
        ui.error("Context window exhausted. Consider starting a new session.")
    elif result.reason == "fatal_error":
        ui.error("A fatal error occurred. Check your API key and configuration.")


def _save_session(session_mgr, history, meta: dict) -> None:
    """保存当前会话到磁盘。"""
    try:
        messages = history.to_serializable()
        # 生成简短摘要用于恢复提示
        if messages:
            last_assistant = ""
            for msg in reversed(messages):
                if msg.get("role") == "assistant" and msg.get("content"):
                    last_assistant = msg["content"][:200]
                    break
            meta["summary"] = last_assistant
        session_mgr.save(messages, meta)
    except OSError:
        pass


if __name__ == "__main__":
    main()
