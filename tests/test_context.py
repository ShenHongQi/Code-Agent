"""上下文管理测试：token 估算、安全切点、孤儿自愈。"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AGENT_API_KEY", "test")

from agent.context import TokenEstimator, find_safe_cut_point, heal_orphans


def test_estimator_basic():
    est = TokenEstimator()
    assert est.estimate("") == 0
    assert est.estimate("hello") > 0
    assert est.estimate("你好") > est.estimate("hi")


def test_estimator_calibration():
    est = TokenEstimator()
    long_text = "a" * 1000
    before = est.estimate(long_text)
    est.calibrate(100, 150)  # actual was 50% higher
    after = est.estimate(long_text)
    assert after > before


def test_safe_cut_point_user_boundary():
    msgs = [
        {"role": "user", "content": "task1"},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "task2"},
        {"role": "assistant", "content": "done"},
    ]
    assert find_safe_cut_point(msgs, 0) == 0
    assert find_safe_cut_point(msgs, 2) == 2


def test_safe_cut_point_skips_tool_pair():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "tc1"}]},
        {"role": "tool", "tool_call_id": "tc1", "content": "result"},
        {"role": "user", "content": "next"},
    ]
    # Cutting at index 1 (assistant with tool_calls) should skip to index 3 (next user)
    assert find_safe_cut_point(msgs, 1) == 3


def test_safe_cut_point_multiple_tools():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "t1"}, {"id": "t2"}]},
        {"role": "tool", "tool_call_id": "t1", "content": "r1"},
        {"role": "tool", "tool_call_id": "t2", "content": "r2"},
        {"role": "user", "content": "thanks"},
    ]
    assert find_safe_cut_point(msgs, 1) == 4


def test_heal_orphan_tool_calls():
    msgs = [
        {"role": "assistant", "content": None, "tool_calls": [{"id": "tc1"}]},
        # Missing tool result for tc1
    ]
    healed = heal_orphans(msgs)
    tool_msgs = [m for m in healed if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "tc1"


def test_heal_orphan_tool_messages():
    msgs = [
        {"role": "user", "content": "hi"},
        # Orphan tool message with no matching assistant
        {"role": "tool", "tool_call_id": "orphan_id", "content": "stale"},
        {"role": "assistant", "content": "hello"},
    ]
    healed = heal_orphans(msgs)
    tool_msgs = [m for m in healed if m.get("role") == "tool"]
    assert len(tool_msgs) == 0  # orphan should be removed


if __name__ == "__main__":
    test_estimator_basic()
    test_estimator_calibration()
    test_safe_cut_point_user_boundary()
    test_safe_cut_point_skips_tool_pair()
    test_safe_cut_point_multiple_tools()
    test_heal_orphan_tool_calls()
    test_heal_orphan_tool_messages()
    print("All context tests passed!")
