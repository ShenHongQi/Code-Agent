"""强制压缩集成测试：验证 --context-limit 32000 场景下 compaction 正确工作。"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AGENT_API_KEY", "test")

from agent.context import ContextManager, TokenEstimator, find_safe_cut_point, heal_orphans
from agent.history import History, make_user, make_assistant, make_tool


def _build_long_history() -> History:
    """构造一个超过 32000 token 估算的长会话。"""
    h = History("You are a test agent.")
    # First user message (anchor)
    h.append(make_user("Please help me refactor the auth module."))
    # Simulate 20 rounds of tool use
    for i in range(20):
        h.append(make_assistant(
            content=f"I'll look at file {i}.",
            tool_calls=[{"id": f"tc_{i}", "type": "function",
                        "function": {"name": "read_file", "arguments": f'{{"path": "file{i}.py"}}'}}]
        ))
        h.append(make_tool(f"tc_{i}", "x" * 2000))  # ~550 tokens each
        h.append(make_user("continue"))
    return h


def test_compaction_preserves_invariants():
    """验证压缩后不破坏 tool_call/tool 配对。"""
    h = _build_long_history()
    messages = h.get_messages_for_api()

    # Force a low context limit
    os.environ["AGENT_CONTEXT_LIMIT"] = "32000"
    from agent.config import Config
    cfg = Config()

    class MockCM(ContextManager):
        def __init__(self):
            self.estimator = TokenEstimator()
            self._provider = None
            self._soft_cap = 5000  # very low to force compaction

    cm = MockCM()
    assert cm.should_compact(messages)

    compacted = cm.compact(messages)

    # Verify no orphan tool_calls
    called_ids: set[str] = set()
    answered_ids: set[str] = set()
    for msg in compacted:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                called_ids.add(tc["id"])
        elif msg.get("role") == "tool":
            answered_ids.add(msg["tool_call_id"])

    orphans = called_ids - answered_ids
    assert not orphans, f"Orphan tool_calls after compaction: {orphans}"

    # Verify no orphan tool messages
    orphan_tools = answered_ids - called_ids
    assert not orphan_tools, f"Orphan tool messages: {orphan_tools}"


def test_compaction_preserves_first_user():
    """验证压缩保留第一条用户消息。"""
    h = _build_long_history()
    messages = h.get_messages_for_api()

    class MockCM(ContextManager):
        def __init__(self):
            self.estimator = TokenEstimator()
            self._provider = None
            self._soft_cap = 5000

    cm = MockCM()
    compacted = cm.compact(messages)

    # First message should be system
    assert compacted[0]["role"] == "system"
    # Second should be the original first user message
    assert compacted[1]["role"] == "user"
    assert "refactor" in compacted[1]["content"]


def test_compaction_reduces_size():
    """验证压缩确实减小了消息总量。"""
    h = _build_long_history()
    messages = h.get_messages_for_api()

    class MockCM(ContextManager):
        def __init__(self):
            self.estimator = TokenEstimator()
            self._provider = None
            self._soft_cap = 5000

    cm = MockCM()
    before = cm.estimator.estimate_messages(messages)
    compacted = cm.compact(messages)
    after = cm.estimator.estimate_messages(compacted)

    assert after < before, f"Compaction didn't reduce size: {before} -> {after}"


def test_heal_orphans_in_compacted():
    """验证即使切点有问题，heal_orphans 也能修复。"""
    # Simulate a bad cut that left orphan tool_call
    messages = [
        {"role": "system", "content": "test"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "x1"}]},
        # Missing tool result for x1
        {"role": "user", "content": "continue"},
    ]
    healed = heal_orphans(messages)
    tool_msgs = [m for m in healed if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "x1"


if __name__ == "__main__":
    test_compaction_preserves_invariants()
    test_compaction_preserves_first_user()
    test_compaction_reduces_size()
    test_heal_orphans_in_compacted()
    print("All compaction tests passed!")
