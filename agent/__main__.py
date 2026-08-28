"""CLI 入口、参数解析、REPL 主循环。"""

from __future__ import annotations
import argparse
import sys

from agent.config import config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agent",
        description="A coding agent that reads/writes files and executes commands.",
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

    # Check API key
    if not config.api_key:
        print("Error: AGENT_API_KEY environment variable is required.", file=sys.stderr)
        print("Set it in your environment or in a .env file.", file=sys.stderr)
        sys.exit(1)

    # Initialize subsystems
    from agent.workspace import Workspace, FileRegistry
    from agent.tools import fs, search, bash, todo, task  # noqa: F401 - register tools
    from agent.llm import create_provider
    from agent.history import History
    from agent.prompts import SYSTEM_PROMPT
    from agent.ui import UI
    from agent.loop import run_loop

    workspace = Workspace(config.workspace)
    registry = FileRegistry()

    fs.init(workspace, registry)
    search.init(workspace)
    bash.init(workspace)

    provider = create_provider()
    task.init(workspace, provider, depth=0)

    history = History(SYSTEM_PROMPT)
    ui = UI(stream=not config.no_stream)

    ui.info(f"Coding Agent | model: {config.model} | workspace: {workspace.root}")
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
