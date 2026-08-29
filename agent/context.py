"""Token 估算校准 + 锚定式 compaction + 安全切点 + 孤儿自愈。"""

from __future__ import annotations

import json
from typing import Any

from agent.config import config

SAFETY_FACTOR = 1.15
EMA_ALPHA = 0.3  # exponential moving average for calibration


class TokenEstimator:
    """手写 token 估算器，带服务端反馈校准。"""

    def __init__(self):
        self._calibration_factor: float = 1.0

    def estimate(self, text: str) -> int:
        """估算文本的 token 数。CJK 按 1.0/字，其余按 len/3.6。"""
        if not text:
            return 0
        cjk_count = 0
        other_count = 0
        for ch in text:
            cp = ord(ch)
            if (0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or
                    0x2E80 <= cp <= 0x2EFF or 0xF900 <= cp <= 0xFAFF or
                    0x3000 <= cp <= 0x303F or 0xFF00 <= cp <= 0xFFEF):
                cjk_count += 1
            else:
                other_count += 1
        raw = cjk_count * 1.0 + other_count / 3.6
        return int(raw * SAFETY_FACTOR * self._calibration_factor)

    def estimate_message(self, msg: dict[str, Any]) -> int:
        """估算单条消息的 token 数。"""
        tokens = 4  # message structure overhead
        content = msg.get("content", "")
        if isinstance(content, str):
            tokens += self.estimate(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("text"):
                    tokens += self.estimate(part["text"])

        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tokens += 4  # tool_call structure
                func = tc.get("function", {})
                tokens += self.estimate(func.get("name", ""))
                tokens += self.estimate(func.get("arguments", ""))

        return tokens

    def estimate_messages(self, messages: list[dict[str, Any]], tools_schema: list[dict[str, Any]] | None = None) -> int:
        total = sum(self.estimate_message(m) for m in messages)
        if tools_schema:
            total += self.estimate_tools_schema(tools_schema)
        return total

    def estimate_tools_schema(self, tools: list[dict[str, Any]]) -> int:
        return self.estimate(json.dumps(tools, ensure_ascii=False))

    def calibrate(self, estimated: int, actual: int) -> None:
        """用服务端返回的 usage.prompt_tokens 校准。"""
        if estimated <= 0 or actual <= 0:
            return
        ratio = max(0.5, min(2.0, actual / estimated))
        self._calibration_factor = (
            EMA_ALPHA * ratio + (1 - EMA_ALPHA) * self._calibration_factor
        )


def find_safe_cut_point(messages: list[dict[str, Any]], target_idx: int) -> int:
    """找到 target_idx 附近的安全切点（不破坏 tool_call/tool 配对）。

    安全切点必须在"完整 round 边界"上：一个 round = assistant + 其全部 tool results。
    返回的索引是被保留段的起始位置（之前的消息被压缩）。
    """
    # Move forward from target to find a round boundary
    idx = target_idx
    n = len(messages)

    while idx < n:
        msg = messages[idx]
        # Safe: at a user message (natural round boundary)
        if msg.get("role") == "user":
            return idx
        # Not safe: at a tool message (belongs to previous assistant)
        if msg.get("role") == "tool":
            idx += 1
            continue
        # At an assistant message: check if it has tool_calls
        if msg.get("role") == "assistant":
            if not msg.get("tool_calls"):
                return idx
            # Has tool_calls: skip past all contiguous tool results
            num_calls = len(msg["tool_calls"])
            idx += 1
            skipped = 0
            while idx < n and skipped < num_calls:
                if messages[idx].get("role") != "tool":
                    break
                idx += 1
                skipped += 1
            continue
        idx += 1

    return n  # fallback: keep nothing (shouldn't happen in practice)


def heal_orphans(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """自愈扫描：修补孤儿 tool_call 和孤儿 tool 消息。"""
    # Collect all tool_call ids from assistant messages
    called: dict[str, int] = {}  # id -> index of assistant msg
    answered: set[str] = set()

    for i, msg in enumerate(messages):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                called[tc["id"]] = i
        elif msg.get("role") == "tool":
            answered.add(msg.get("tool_call_id", ""))

    # Find orphan tool_calls (called but not answered)
    orphan_ids = [tc_id for tc_id in called if tc_id not in answered]

    if orphan_ids:
        # Group orphans by their assistant message index, insert after it
        by_assistant: dict[int, list[str]] = {}
        for tc_id in orphan_ids:
            idx = called[tc_id]
            by_assistant.setdefault(idx, []).append(tc_id)

        result = []
        for i, msg in enumerate(messages):
            result.append(msg)
            if i in by_assistant:
                for tc_id in by_assistant[i]:
                    result.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": "[Context compacted; original result unavailable]",
                    })
    else:
        result = list(messages)

    # Find orphan tool messages (answered but no matching call in visible history)
    visible_call_ids = set(called.keys())
    cleaned = []
    for msg in result:
        if msg.get("role") == "tool":
            tc_id = msg.get("tool_call_id", "")
            if tc_id not in visible_call_ids:
                continue  # drop orphan tool message
        cleaned.append(msg)

    return cleaned


class ContextManager:
    """管理上下文窗口：估算、压缩触发、compaction 执行。"""

    def __init__(self, provider=None, memory_mgr=None):
        self.estimator = TokenEstimator()
        self._provider = provider
        self._memory_mgr = memory_mgr
        self._soft_cap = min(
            int(0.75 * config.usable_context),
            120_000,
        )

    def should_compact(self, messages: list[dict[str, Any]]) -> bool:
        estimated = self.estimator.estimate_messages(messages)
        return estimated > self._soft_cap

    def compact(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """执行锚定式 compaction，返回压缩后的消息列表。

        永不驱逐：
        1. system prompt (index 0)
        2. 第一条用户消息
        3. 最后 6 轮消息

        中段消息摘要为单条 summary 消息。
        """
        if len(messages) < 8:
            return messages  # too short to compact

        # messages[0] is system prompt
        # Find first user message
        first_user_idx = None
        for i, msg in enumerate(messages):
            if msg.get("role") == "user":
                first_user_idx = i
                break

        if first_user_idx is None:
            return messages

        # Keep last 6 rounds (roughly last 12-18 messages)
        tail_size = self._find_tail_start(messages)

        # The middle section to be summarized
        anchor_end = first_user_idx + 1  # keep system + first user
        middle = messages[anchor_end:tail_size]

        if not middle:
            return messages

        # Find safe cut point for the tail
        safe_tail = find_safe_cut_point(messages, tail_size)

        # Actually do the compaction: summarize middle section
        middle_section = messages[anchor_end:safe_tail]
        if not middle_section:
            return messages

        summary = self._summarize(middle_section)

        # Reconstruct: [system, first_user, summary, tail...]
        result = messages[:anchor_end]
        result.append({"role": "user", "content": f"<summary>\n{summary}\n</summary>"})
        result.extend(messages[safe_tail:])

        # Heal any orphans created by compaction
        result = heal_orphans(result)
        return result

    def _find_tail_start(self, messages: list[dict[str, Any]]) -> int:
        """找到最后 6 个 round 的起始位置。"""
        rounds = 0
        idx = len(messages) - 1
        while idx >= 0 and rounds < 6:
            if messages[idx].get("role") == "user":
                rounds += 1
            idx -= 1
        return max(idx + 1, 2)  # at least keep system + first user

    def _summarize(self, messages: list[dict[str, Any]]) -> str:
        """调用 LLM 摘要中段消息。如果 provider 不可用，用简单截断。"""
        if not self._provider:
            return self._fallback_summary(messages)

        memory_instruction = ""
        if self._memory_mgr:
            memory_instruction = (
                "\n\nIf the conversation contains long-term valuable project knowledge "
                "(architecture decisions, conventions, known issues), output them at the end "
                "as lines prefixed with [MEMORY], one fact per line. Example:\n"
                "[MEMORY] 项目使用 pytest 作为测试框架\n"
                "[MEMORY] 数据库迁移用 alembic\n"
            )

        summary_prompt = (
            "Summarize the following conversation segment concisely. Preserve:\n"
            "- Files that were modified and what changed\n"
            "- Confirmed facts (test commands, file locations, etc.)\n"
            "- Rejected approaches and why\n"
            "- Pending tasks\n"
            f"{memory_instruction}\n"
            "Conversation:\n"
        )
        for msg in messages:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                summary_prompt += f"[{role}]: {content[:500]}\n"

        try:
            from agent.history import make_system, make_user
            from agent.llm import stream_with_retry
            summary_messages = [
                make_system("You are a concise summarizer. Output only the summary."),
                make_user(summary_prompt[:8000]),
            ]
            acc = stream_with_retry(self._provider, summary_messages, max_retries=2)
            summary = acc.content or self._fallback_summary(messages)
            self._extract_memories(summary)
            return summary
        except Exception:
            return self._fallback_summary(messages)

    def _extract_memories(self, summary: str) -> None:
        """从摘要中提取 [MEMORY] 标记行并写入项目记忆。"""
        if not self._memory_mgr:
            return
        for line in summary.splitlines():
            stripped = line.strip()
            if stripped.startswith("[MEMORY]"):
                entry = stripped[len("[MEMORY]"):].strip()
                if entry:
                    self._memory_mgr.append(entry, scope="project")

    def _fallback_summary(self, messages: list[dict[str, Any]]) -> str:
        """无 LLM 时的简单摘要。"""
        parts = []
        for msg in messages[:10]:
            role = msg.get("role", "?")
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                parts.append(f"[{role}]: {content[:200]}")
        return "Previous conversation (truncated):\n" + "\n".join(parts)
