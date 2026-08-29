"""流式解析测试：delta 重组、tool_call 碎片化。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AGENT_API_KEY", "test")

from agent.stream import StreamAccumulator


def test_simple_content():
    acc = StreamAccumulator()
    acc.feed({"choices": [{"delta": {"content": "Hello"}, "finish_reason": None}]})
    acc.feed({"choices": [{"delta": {"content": " world"}, "finish_reason": "stop"}]})
    assert acc.content == "Hello world"
    assert acc.is_natural_stop
    assert not acc.has_tool_calls


def test_tool_call_assembly():
    acc = StreamAccumulator()
    # First chunk: tool_call id and partial name
    acc.feed({"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "call_123", "function": {"name": "read", "arguments": ""}}
    ]}, "finish_reason": None}]})
    # Second chunk: partial name continuation + arguments start
    acc.feed({"choices": [{"delta": {"tool_calls": [
        {"index": 0, "function": {"name": "_file", "arguments": '{"pa'}}
    ]}, "finish_reason": None}]})
    # Third chunk: arguments rest
    acc.feed({"choices": [{"delta": {"tool_calls": [
        {"index": 0, "function": {"arguments": 'th": "x.py"}'}}
    ]}, "finish_reason": "tool_calls"}]})

    assert acc.has_tool_calls
    assert not acc.is_natural_stop
    calls = acc.get_tool_calls()
    assert len(calls) == 1
    assert calls[0]["name"] == "read_file"
    assert calls[0]["arguments"] == {"path": "x.py"}


def test_multiple_tool_calls():
    acc = StreamAccumulator()
    acc.feed({"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "c1", "function": {"name": "bash", "arguments": '{"command": "ls"}'}}
    ]}, "finish_reason": None}]})
    acc.feed({"choices": [{"delta": {"tool_calls": [
        {"index": 1, "id": "c2", "function": {"name": "glob", "arguments": '{"pattern": "*.py"}'}}
    ]}, "finish_reason": "tool_calls"}]})

    calls = acc.get_tool_calls()
    assert len(calls) == 2
    assert calls[0]["name"] == "bash"
    assert calls[1]["name"] == "glob"


def test_empty_choices_chunk():
    acc = StreamAccumulator()
    acc.feed({"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]})
    # Usage-only chunk with no choices
    acc.feed({"usage": {"prompt_tokens": 100, "completion_tokens": 5}})
    acc.feed({"choices": [{"delta": {}, "finish_reason": "stop"}]})
    assert acc.content == "hi"
    assert acc.usage == {"prompt_tokens": 100, "completion_tokens": 5}


def test_to_message():
    acc = StreamAccumulator()
    acc.feed({"choices": [{"delta": {"content": "thinking..."}, "finish_reason": None}]})
    acc.feed({"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "tc1", "function": {"name": "bash", "arguments": '{"command":"pwd"}'}}
    ]}, "finish_reason": "tool_calls"}]})

    msg = acc.to_message()
    assert msg["role"] == "assistant"
    assert msg["content"] == "thinking..."
    assert len(msg["tool_calls"]) == 1
    assert msg["tool_calls"][0]["id"] == "tc1"
    assert msg["tool_calls"][0]["function"]["name"] == "bash"


if __name__ == "__main__":
    test_simple_content()
    test_tool_call_assembly()
    test_multiple_tool_calls()
    test_empty_choices_chunk()
    test_to_message()
    print("All stream tests passed!")
