"""Agent loop：自适应迭代、并行工具执行、卡死反思。"""

from __future__ import annotations

import concurrent.futures
import random
import sys
import threading
import time
from typing import Any

from agent.config import config
from agent.context import ContextManager
from agent.history import History, make_tool, make_user
from agent.llm import ContextLengthExceeded, LLMError, Provider
from agent.stream import StreamAccumulator
from agent.terminal import EscInterrupt
from agent.tools import ToolResult, dispatch, get_tools_schema
from agent.ui import UI


class LoopResult:
    __slots__ = ("reason", "iterations", "prompt_tokens", "completion_tokens")

    def __init__(self, reason: str, iterations: int,
                 prompt_tokens: int = 0, completion_tokens: int = 0):
        self.reason = reason
        self.iterations = iterations
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


SUBAGENT_TOOLS = {"read_file", "glob", "grep", "bash"}
SUBAGENT_WRITE_TOOLS = {"read_file", "write_file", "edit_file", "multi_edit", "glob", "grep", "bash"}

# 并行安全的工具（无副作用）
READ_ONLY_TOOLS = {"read_file", "glob", "grep", "list_dir", "view_diff", "memory_read", "proc_status", "web_fetch"}

# 自适应迭代上限
QUICK_LIMIT = 25
EXTENDED_LIMIT = 80

# 卡死检测
STUCK_WINDOW = 3

# 迭代延长标志（由 extend_iterations 工具设置）
_extend_requested = False


def request_extend() -> None:
    """供 extend_iterations 工具调用，请求延长迭代上限。"""
    global _extend_requested
    _extend_requested = True


def _estimate_complexity(user_message: str) -> int:
    """根据输入复杂度估算迭代上限。"""
    indicators = [
        len(user_message) > 500,
        user_message.count("\n") > 5,
        any(kw in user_message.lower() for kw in [
            "refactor", "重构", "所有", "每个", "全部", "migrate", "升级", "批量",
        ]),
    ]
    return EXTENDED_LIMIT if sum(indicators) >= 2 else QUICK_LIMIT


def run_loop(
    history: History,
    provider: Provider,
    ui: UI,
    max_iterations: int | None = None,
    context_mgr: ContextManager | None = None,
    allowed_tools: set[str] | None = None,
    interrupt_event: threading.Event | None = None,
    memory_mgr=None,
    workspace_root: str | None = None,
    thinking_log: list[str] | None = None,
) -> LoopResult:
    """执行 agent loop 直到终止条件满足。"""
    global _extend_requested
    _extend_requested = False

    from agent.skills import set_auto_approve
    set_auto_approve(False)

    # 自适应上限
    if max_iterations:
        max_iter = max_iterations
    else:
        first_user = ""
        for msg in history.messages:
            if msg.get("role") == "user":
                first_user = msg.get("content", "")
        max_iter = min(config.max_iterations, _estimate_complexity(first_user))

    tools_schema = get_tools_schema(allowed_tools)
    ctx = context_mgr or ContextManager(provider, memory_mgr=memory_mgr)
    iteration = 0
    last_ctx_tokens = 0
    turn_output_tokens = 0

    while iteration < max_iter:
        iteration += 1

        # Check ESC interrupt
        if interrupt_event and interrupt_event.is_set():
            raise EscInterrupt()

        # 迭代延长
        if _extend_requested and max_iter < EXTENDED_LIMIT:
            max_iter = EXTENDED_LIMIT
            _extend_requested = False
            ui.info(f"[iterations extended to {max_iter}]")

        # Memory hot-reload: rebuild system prompt if memory changed
        if memory_mgr and memory_mgr.has_changed() and workspace_root:
            from agent.prompts import build_system_prompt
            new_prompt = build_system_prompt(workspace_root, memory_mgr)
            history.update_system(new_prompt)

        messages = history.get_messages_for_api()

        # Compaction check
        if ctx.should_compact(messages):
            ui.info("[compacting context...]")
            compacted = ctx.compact(messages)
            history._messages = compacted[1:]
            messages = history.get_messages_for_api()

        # 卡死检测 + 反思注入
        if config.reflection_enabled and _detect_stuck(history):
            reflection = (
                "[System] 最近多次工具调用均失败。请停下来重新审视方案：\n"
                "1. 重新阅读相关文件确认内容\n"
                "2. 尝试完全不同的策略\n"
                "3. 用 todo_write 重新规划步骤\n"
                "4. 如果任务本身不可行，向用户说明原因。"
            )
            history.append(make_user(reflection))
            messages = history.get_messages_for_api()

        ui.assistant_start()
        try:
            acc = _stream_step_with_retry(provider, messages, tools_schema, ui)
        except ContextLengthExceeded:
            ui.warning("Context length exceeded. Forcing compaction...")
            compacted = ctx.compact(messages)
            history._messages = compacted[1:]
            messages = history.get_messages_for_api()
            try:
                acc = _stream_step_with_retry(provider, messages, tools_schema, ui)
            except (ContextLengthExceeded, LLMError) as e2:
                ui.error(f"Still exceeding after compaction: {e2}")
                return LoopResult("context_exhausted", iteration)
        except LLMError as e:
            ui.error(str(e))
            return LoopResult("fatal_error", iteration)
        except (KeyboardInterrupt, EscInterrupt):
            ui.assistant_end()
            raise
        except Exception as e:
            ui.assistant_end()
            ui.error(f"Unexpected error: {e}")
            return LoopResult("fatal_error", iteration)

        # Calibrate token estimator with actual usage
        if acc.usage.get("prompt_tokens"):
            estimated = ctx.estimator.estimate_messages(messages)
            ctx.estimator.calibrate(estimated, acc.usage["prompt_tokens"])

        if acc.usage:
            last_ctx_tokens = acc.usage.get("prompt_tokens", 0)
            turn_output_tokens += acc.usage.get("completion_tokens", 0)

        # Append assistant message to history
        assistant_msg = acc.to_message()
        history.append(assistant_msg)

        # 保存流式状态（assistant_end 会清除标志）
        was_streamed = ui._streaming_active

        # 停止 spinner
        ui.assistant_end()

        # Check natural stop → 最终回答
        if acc.is_natural_stop:
            # 纠偏：如果 assistant 只输出文本且包含代码块/命令，提醒它调用工具
            if acc.content and _looks_like_missed_tool_call(acc.content) and iteration < max_iter - 1:
                if not was_streamed:
                    ui.show_thinking(acc.content)
                if thinking_log is not None:
                    thinking_log.append(acc.content)
                nudge = (
                    "[System] 你刚才描述了要执行的操作但没有调用工具。"
                    "请不要只描述命令——直接调用 bash/write_file/edit_file 等工具来执行。"
                    "现在请调用相应的工具完成任务。"
                )
                history.append(make_user(nudge))
                continue

            # 最终回答：流式已输出则跳过重复渲染
            if not was_streamed:
                ui.show_response(acc.content or "")
            ui.show_thinking_summary()
            return LoopResult("natural_stop", iteration, last_ctx_tokens, turn_output_tokens)

        # Process tool calls → 中间思考
        if acc.has_tool_calls:
            if acc.content:
                if not was_streamed:
                    ui.show_thinking(acc.content)
                if thinking_log is not None:
                    thinking_log.append(acc.content)
            try:
                _execute_tools(acc, history, ui, allowed_tools, interrupt_event)
            except (KeyboardInterrupt, EscInterrupt):
                history.seal_pending_tool_calls()
                if isinstance(sys.exc_info()[1], EscInterrupt):
                    raise
                ui.warning("\nInterrupted by user.")
                return LoopResult("user_interrupt", iteration)
            finally:
                history.seal_pending_tool_calls()

    ui.show_thinking_summary()
    return LoopResult("max_iterations", iteration, last_ctx_tokens, turn_output_tokens)


def _looks_like_missed_tool_call(content: str) -> bool:
    """检测 assistant 是否在文本中描述了命令而没有调用工具。"""
    import re
    indicators = [
        bool(re.search(r"```(bash|shell|sh)\n", content)),
        bool(re.search(r"```\n(mkdir|cd|npm|pip|git|python|curl|wget)\s", content)),
        bool(re.search(r"我将执行|让我[们来]|接下来我会|我会运行", content)),
        bool(re.search(r"执行以下命令|运行以下", content)),
    ]
    return sum(indicators) >= 2


def _detect_stuck(history: History) -> bool:
    """检测是否陷入连续失败循环。"""
    recent_errors = 0
    checked = 0
    for msg in reversed(history.messages):
        if msg.get("role") == "tool":
            content = msg.get("content", "")
            if content.startswith("Error:"):
                recent_errors += 1
            else:
                break
            checked += 1
            if checked >= STUCK_WINDOW:
                break
    return recent_errors >= STUCK_WINDOW


MAX_LLM_RETRIES = 5


def _stream_step_with_retry(
    provider: Provider,
    messages: list[dict[str, Any]],
    tools_schema: list[dict[str, Any]],
    ui: UI,
) -> StreamAccumulator:
    """带重试的 LLM 调用。retryable 错误自动重试，非 retryable 立即抛出。"""
    for attempt in range(MAX_LLM_RETRIES):
        try:
            return _stream_step(provider, messages, tools_schema, ui)
        except LLMError as e:
            if not e.retryable or attempt == MAX_LLM_RETRIES - 1:
                raise
            delay = random.uniform(0, min(30, 1.0 * 2 ** attempt))
            ui.warning(f"  Retrying ({attempt + 1}/{MAX_LLM_RETRIES}) in {delay:.1f}s: {e}")
            time.sleep(delay)
    raise LLMError("Max retries exceeded", retryable=False)


def _stream_step(
    provider: Provider,
    messages: list[dict[str, Any]],
    tools_schema: list[dict[str, Any]],
    ui: UI,
) -> StreamAccumulator:
    """执行一次 LLM 调用（流式），实时输出内容 token。"""
    acc = StreamAccumulator()

    for chunk in provider.stream_chat(messages, tools_schema):
        new_text = acc.feed(chunk)
        if new_text:
            ui.stream_token(new_text)

    return acc


def _execute_tools(
    acc: StreamAccumulator, history: History, ui: UI,
    allowed_tools: set[str] | None = None,
    interrupt_event: threading.Event | None = None,
) -> None:
    """执行工具调用。读操作并行，写操作顺序。"""
    tool_calls = acc.get_tool_calls()

    if not config.parallel_tools or len(tool_calls) <= 1:
        _execute_tools_sequential(tool_calls, history, ui, allowed_tools, interrupt_event)
        return

    # 分离读写操作
    read_calls = []
    write_calls = []
    for tc in tool_calls:
        if tc["name"] in READ_ONLY_TOOLS:
            read_calls.append(tc)
        else:
            write_calls.append(tc)

    results: dict[str, ToolResult] = {}

    # 并行执行读操作
    if len(read_calls) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(_dispatch_one, tc, allowed_tools): tc
                for tc in read_calls
            }
            for future in concurrent.futures.as_completed(futures):
                tc = futures[future]
                results[tc["id"]] = future.result()
    else:
        for tc in read_calls:
            results[tc["id"]] = _dispatch_one(tc, allowed_tools)

    # 顺序执行写操作
    for tc in write_calls:
        if interrupt_event and interrupt_event.is_set():
            raise EscInterrupt()
        results[tc["id"]] = _dispatch_one(tc, allowed_tools)

    # 按原始顺序记录结果
    for tc in tool_calls:
        result = results[tc["id"]]
        args_summary = _summarize_args(tc["name"], tc["arguments"])
        ui.tool_start(tc["name"], args_summary)
        ui.tool_result(result.ok, result.content)
        history.append(make_tool(tc["id"], result.content))


def _execute_tools_sequential(
    tool_calls: list[dict[str, Any]], history: History, ui: UI,
    allowed_tools: set[str] | None, interrupt_event: threading.Event | None,
) -> None:
    """顺序执行所有工具调用。"""
    for tc in tool_calls:
        if interrupt_event and interrupt_event.is_set():
            raise EscInterrupt()

        name = tc["name"]
        args = tc["arguments"]
        tc_id = tc["id"]

        if allowed_tools is not None and name not in allowed_tools:
            result = ToolResult(False, f"Error: Tool '{name}' is not available in this context.")
        else:
            args_summary = _summarize_args(name, args)
            ui.tool_start(name, args_summary)
            result = dispatch(name, args)

        ui.tool_result(result.ok, result.content)
        history.append(make_tool(tc_id, result.content))


def _dispatch_one(tc: dict[str, Any], allowed_tools: set[str] | None) -> ToolResult:
    """执行单个工具调用。"""
    name = tc["name"]
    args = tc["arguments"]

    if allowed_tools is not None and name not in allowed_tools:
        return ToolResult(False, f"Error: Tool '{name}' is not available in this context.")
    return dispatch(name, args)


def _summarize_args(name: str, args: dict[str, Any]) -> str:
    """生成工具参数的简短摘要用于显示。"""
    if name in ("read_file", "write_file", "edit_file", "delete_file", "view_diff"):
        return args.get("path", "")
    if name == "rename_file":
        return f"{args.get('old_path', '')} -> {args.get('new_path', '')}"
    if name == "bash":
        cmd = args.get("command", "")
        return cmd[:60] + ("..." if len(cmd) > 60 else "")
    if name == "spawn":
        cmd = args.get("command", "")
        return cmd[:50] + ("..." if len(cmd) > 50 else "")
    if name in ("glob", "grep"):
        return args.get("pattern", "")
    if name == "multi_edit":
        return args.get("path", "")
    if name == "web_fetch":
        return args.get("url", "")[:50]
    if name == "task":
        desc = args.get("description", "")
        return desc[:40] + ("..." if len(desc) > 40 else "")
    return ", ".join(f"{k}={v!r}" for k, v in list(args.items())[:2])
