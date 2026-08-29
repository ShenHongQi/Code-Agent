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


def _new_session_meta(workspace: str) -> dict:
    """创建新会话的 meta。"""
    from datetime import datetime, timezone

    from agent.session import SessionManager

    return {
        "session_id": SessionManager.create_session_id(workspace),
        "workspace": workspace,
        "model": config.model,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "turns": 0,
        "summary": "",
    }


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
    from agent.commands import CommandContext
    from agent.commands import dispatch as cmd_dispatch
    from agent.goal import GoalManager, PlanManager
    from agent.history import History
    from agent.llm import create_provider
    from agent.memory import MemoryManager
    from agent.prompts import build_system_prompt
    from agent.session import SessionManager
    from agent.terminal import EscDetector, EscInterrupt, InputManager
    from agent.tools import bash, control, diff, fs, proc, search, task, todo, web  # noqa: F401  # noqa: F401
    from agent.tools import memory as memory_tool  # noqa: F401
    from agent.ui import UI
    from agent.workspace import FileRegistry, Workspace

    workspace = Workspace(config.workspace)
    registry = FileRegistry()

    fs.init(workspace, registry)
    search.init(workspace)
    bash.init(workspace)
    diff.init(workspace, registry)
    proc.init(workspace)

    from agent.permission import init_permission_mode
    init_permission_mode()

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

    # Goal & Plan managers
    goal_mgr = GoalManager()
    plan_mgr = PlanManager()

    # 注册命令列表供输入补全
    from agent.commands import get_all_commands
    input_mgr.set_commands([(c.name, c.description) for c in get_all_commands()])

    from agent.banner import render_banner
    from agent.terminal import install_resize_handler

    print(render_banner(model=config.model, workspace=str(workspace.root)))

    # SIGWINCH：窗口变化时立即清屏 + 重绘 banner + 重绘输入框
    def _redraw_banner():
        banner = render_banner(model=config.model, workspace=str(workspace.root))
        sys.stdout.write(banner + "\n")
        sys.stdout.flush()

    install_resize_handler(_redraw_banner)

    # 默认新建会话（不做恢复提示）
    history = History(system_prompt)
    session_meta = _new_session_meta(str(workspace.root))

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
        # ── 自动目标模式：无需等待用户输入 ──
        if goal_mgr.active:
            auto_input = None
            if goal_mgr.iterations == 0:
                auto_input = goal_mgr.build_initial_prompt()
            else:
                auto_input = goal_mgr.build_continue_prompt()

            thinking_history.clear()
            esc_detector = EscDetector()
            esc_detector.start()
            try:
                result = _run_turn_with_result(
                    auto_input, history, provider, ui, memory_mgr,
                    str(workspace.root), esc_detector.event, thinking_history
                )
                if not goal_mgr.should_auto_continue(result, history):
                    ui.info(f"\n🎯 目标完成或已达自动迭代上限 ({goal_mgr.iterations} 轮)。")
                    goal_mgr.clear()
            except EscInterrupt:
                ui.warning("\n⚠ 目标执行被中断 (ESC)。目标已暂停，输入 /goal clear 取消或继续对话。")
                goal_mgr.clear()
            except KeyboardInterrupt:
                history.seal_pending_tool_calls()
                ui.warning("\n目标执行被中断。")
                goal_mgr.clear()
            finally:
                esc_detector.stop()

            session_meta["turns"] = session_meta.get("turns", 0) + 1
            _save_session(session_mgr, history, session_meta)
            continue

        # ── 方案模式等待确认 ──
        if plan_mgr.phase == "awaiting_approval":
            try:
                user_input = input_mgr.styled_input(
                    prefill="", model=f"{config.model} [方案确认]"
                )
            except (EOFError, KeyboardInterrupt):
                plan_mgr.reject()
                print("\n方案已取消。")
                continue

            lower = user_input.strip().lower()
            if lower in ("y", "yes", "确认", "ok", "执行", "批准", "approve"):
                plan_mgr.approve()
                ui.info("✅ 方案已批准，开始执行…")
                thinking_history.clear()
                esc_detector = EscDetector()
                esc_detector.start()
                try:
                    _run_turn(
                        plan_mgr.build_execution_prompt(), history, provider, ui,
                        memory_mgr, str(workspace.root), esc_detector.event, thinking_history
                    )
                except EscInterrupt:
                    ui.warning("\n⚠ 执行中断 (ESC)。")
                except KeyboardInterrupt:
                    history.seal_pending_tool_calls()
                    ui.warning("\n执行中断。")
                finally:
                    esc_detector.stop()
                plan_mgr.finish()
                session_meta["turns"] = session_meta.get("turns", 0) + 1
                _save_session(session_mgr, history, session_meta)
                continue
            elif lower in ("n", "no", "取消", "cancel", "reject", "拒绝"):
                plan_mgr.reject()
                ui.info("❌ 方案已取消。")
                continue
            else:
                # 用户提供修改意见，追加到对话让 agent 修订方案
                thinking_history.clear()
                esc_detector = EscDetector()
                esc_detector.start()
                revision_prompt = (
                    f"用户对方案有修改意见:\n{user_input}\n\n"
                    f"请根据意见修订方案，输出修改后的完整方案。"
                )
                try:
                    _run_turn(
                        revision_prompt, history, provider, ui,
                        memory_mgr, str(workspace.root), esc_detector.event, thinking_history
                    )
                except (EscInterrupt, KeyboardInterrupt):
                    plan_mgr.reject()
                    ui.warning("\n方案修订中断。")
                finally:
                    esc_detector.stop()
                # 仍在等待确认
                ui.info("\n📋 方案已修订。输入 y 执行 / n 取消 / 或继续提修改意见:")
                session_meta["turns"] = session_meta.get("turns", 0) + 1
                _save_session(session_mgr, history, session_meta)
                continue

        # ── 正常交互模式 ──
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

        # 斜杠命令分发
        if user_input.startswith("/"):
            ctx = CommandContext(
                ui=ui,
                history=history,
                session_mgr=session_mgr,
                session_meta=session_meta,
                workspace=str(workspace.root),
                thinking_history=thinking_history,
                input_mgr=input_mgr,
                provider=provider,
                memory_mgr=memory_mgr,
            )
            cmd_dispatch(user_input, ctx)

            # /resume 可能替换了 history 和 session_meta
            if ctx._resume_result is not None:
                history, session_meta = ctx._resume_result

            # /goal 设置目标
            if ctx._goal_set is not None:
                if ctx._goal_set == "__clear__":
                    goal_mgr.clear()
                else:
                    goal_mgr.set_goal(ctx._goal_set)

            # /plan 设置规划请求
            if ctx._plan_request is not None:
                plan_mgr.start(ctx._plan_request)
                thinking_history.clear()
                esc_detector = EscDetector()
                esc_detector.start()
                # 规划阶段只允许读取工具
                plan_read_tools = {
                    "read_file", "glob", "grep", "list_dir",
                    "view_diff", "proc_status", "web_fetch",
                    "memory_read", "todo_read",
                }
                try:
                    _run_turn(
                        plan_mgr.build_planning_prompt(), history, provider, ui,
                        memory_mgr, str(workspace.root), esc_detector.event, thinking_history,
                        allowed_tools=plan_read_tools,
                    )
                except EscInterrupt:
                    plan_mgr.reject()
                    ui.warning("\n⚠ 规划中断。")
                except KeyboardInterrupt:
                    history.seal_pending_tool_calls()
                    plan_mgr.reject()
                    ui.warning("\n规划中断。")
                else:
                    plan_mgr.move_to_approval()
                    ui.info("\n📋 方案规划完成。输入 y 执行 / n 取消 / 或输入修改意见:")
                finally:
                    esc_detector.stop()
                session_meta["turns"] = session_meta.get("turns", 0) + 1
                _save_session(session_mgr, history, session_meta)

            # skill 执行计为一轮对话
            if ctx._skill_executed:
                session_meta["turns"] = session_meta.get("turns", 0) + 1
                _save_session(session_mgr, history, session_meta)
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


def _run_turn_with_result(user_input: str, history, provider, ui, memory_mgr=None,
                          workspace_root=None, interrupt_event=None,
                          thinking_log: list[str] | None = None,
                          allowed_tools: set[str] | None = None):
    """执行一轮对话并返回 LoopResult。"""
    from agent.history import make_user
    from agent.loop import run_loop

    history.append(make_user(user_input))

    result = run_loop(
        history, provider, ui,
        interrupt_event=interrupt_event,
        memory_mgr=memory_mgr,
        workspace_root=workspace_root,
        thinking_log=thinking_log,
        allowed_tools=allowed_tools,
    )

    if result.reason == "max_iterations":
        ui.warning(f"\nReached iteration limit ({result.iterations}). You can continue the conversation.")
    elif result.reason == "context_exhausted":
        ui.error("Context window exhausted. Consider starting a new session.")
    elif result.reason == "fatal_error":
        ui.error("A fatal error occurred. Check your API key and configuration.")

    return result


def _run_turn(user_input: str, history, provider, ui, memory_mgr=None,
              workspace_root=None, interrupt_event=None,
              thinking_log: list[str] | None = None,
              allowed_tools: set[str] | None = None) -> None:
    _run_turn_with_result(user_input, history, provider, ui, memory_mgr,
                          workspace_root, interrupt_event, thinking_log,
                          allowed_tools)


def _save_session(session_mgr, history, meta: dict) -> None:
    """保存当前会话到磁盘。"""
    try:
        messages = history.to_serializable()
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
