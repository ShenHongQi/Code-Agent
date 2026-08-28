"""Agent loop 与终止条件。"""

from __future__ import annotations
from typing import Any

from agent.config import config
from agent.context import ContextManager
from agent.history import History, make_user, make_tool
from agent.llm import Provider, stream_with_retry, LLMError, ContextLengthExceeded
from agent.stream import StreamAccumulator
from agent.tools import get_tools_schema, dispatch, ToolResult
from agent.ui import UI


class LoopResult:
    __slots__ = ("reason", "iterations")

    def __init__(self, reason: str, iterations: int):
        self.reason = reason
        self.iterations = iterations


SUBAGENT_TOOLS = {"read_file", "glob", "grep", "bash"}


def run_loop(
    history: History,
    provider: Provider,
    ui: UI,
    max_iterations: int | None = None,
    context_mgr: ContextManager | None = None,
    allowed_tools: set[str] | None = None,
) -> LoopResult:
    """执行 agent loop 直到终止条件满足。"""
    max_iter = max_iterations or config.max_iterations
    tools_schema = get_tools_schema(allowed_tools)
    ctx = context_mgr or ContextManager(provider)
    iteration = 0

    while iteration < max_iter:
        iteration += 1

        messages = history.get_messages_for_api()

        # Compaction check
        if ctx.should_compact(messages):
            ui.info("[compacting context...]")
            compacted = ctx.compact(messages)
            history._messages = compacted[1:]  # skip system (it's stored separately)
            messages = history.get_messages_for_api()

        try:
            acc = _stream_step(provider, messages, tools_schema, ui)
        except ContextLengthExceeded:
            ui.warning("Context length exceeded. Forcing compaction...")
            compacted = ctx.compact(messages)
            history._messages = compacted[1:]
            messages = history.get_messages_for_api()
            try:
                acc = _stream_step(provider, messages, tools_schema, ui)
            except (ContextLengthExceeded, LLMError) as e2:
                ui.error(f"Still exceeding after compaction: {e2}")
                return LoopResult("context_exhausted", iteration)
        except LLMError as e:
            ui.error(str(e))
            return LoopResult("fatal_error", iteration)

        # Calibrate token estimator with actual usage
        if acc.usage.get("prompt_tokens"):
            estimated = ctx.estimator.estimate_messages(messages)
            ctx.estimator.calibrate(estimated, acc.usage["prompt_tokens"])

        # Append assistant message to history
        assistant_msg = acc.to_message()
        history.append(assistant_msg)

        # Show content
        if not config.no_stream and acc.content:
            pass  # already streamed
        ui.assistant_end(acc.content or "")

        # Check natural stop
        if acc.is_natural_stop:
            return LoopResult("natural_stop", iteration)

        # Process tool calls
        if acc.has_tool_calls:
            try:
                _execute_tools(acc, history, ui, allowed_tools)
            except KeyboardInterrupt:
                ui.warning("\nInterrupted by user.")
                return LoopResult("user_interrupt", iteration)
            finally:
                history.seal_pending_tool_calls()

    return LoopResult("max_iterations", iteration)


def _stream_step(
    provider: Provider,
    messages: list[dict[str, Any]],
    tools_schema: list[dict[str, Any]],
    ui: UI,
) -> StreamAccumulator:
    """执行一次 LLM 调用（流式），渲染增量 token。"""
    ui.assistant_start()
    acc = StreamAccumulator()

    for chunk in provider.stream_chat(messages, tools_schema):
        new_text = acc.feed(chunk)
        if new_text:
            ui.stream_token(new_text)

    return acc


def _execute_tools(
    acc: StreamAccumulator, history: History, ui: UI, allowed_tools: set[str] | None = None
) -> None:
    """执行 assistant 消息中的所有 tool_calls。"""
    tool_calls = acc.get_tool_calls()

    for tc in tool_calls:
        name = tc["name"]
        args = tc["arguments"]
        tc_id = tc["id"]

        # Enforce tool restrictions (sub-agent read-only)
        if allowed_tools is not None and name not in allowed_tools:
            result = ToolResult(False, f"Error: Tool '{name}' is not available in this context (read-only).")
        else:
            # UI: show tool invocation
            args_summary = _summarize_args(name, args)
            ui.tool_start(name, args_summary)
            result = dispatch(name, args)

        ui.tool_result(result.ok, result.content)
        history.append(make_tool(tc_id, result.content))


def _summarize_args(name: str, args: dict[str, Any]) -> str:
    """生成工具参数的简短摘要用于显示。"""
    if name in ("read_file", "write_file", "edit_file"):
        return args.get("path", "")
    if name == "bash":
        cmd = args.get("command", "")
        return cmd[:60] + ("..." if len(cmd) > 60 else "")
    if name == "glob":
        return args.get("pattern", "")
    if name == "grep":
        return args.get("pattern", "")
    if name == "task":
        desc = args.get("description", "")
        return desc[:40] + ("..." if len(desc) > 40 else "")
    return ", ".join(f"{k}={v!r}" for k, v in list(args.items())[:2])
