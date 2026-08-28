"""工具系统测试：schema 生成、参数校验、dispatch。"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AGENT_API_KEY", "test")

from agent.tools import get_tools_schema, validate_params, dispatch, _REGISTRY
from agent.tools import fs, search, bash, todo
from agent.workspace import Workspace, FileRegistry


def setup():
    ws = Workspace(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    reg = FileRegistry()
    fs.init(ws, reg)
    search.init(ws)
    bash.init(ws)


setup()


def test_schema_generation():
    schema = get_tools_schema()
    names = [t["function"]["name"] for t in schema]
    assert "read_file" in names
    assert "write_file" in names
    assert "edit_file" in names
    assert "glob" in names
    assert "grep" in names
    assert "bash" in names
    assert "todo_write" in names

    # Verify read_file schema
    rf = next(t for t in schema if t["function"]["name"] == "read_file")
    params = rf["function"]["parameters"]
    assert "path" in params["properties"]
    assert "offset" in params["properties"]
    assert "limit" in params["properties"]
    assert "path" in params["required"]
    assert "offset" not in params["required"]


def test_validate_params():
    assert validate_params("read_file", {"path": "test.py"}) is None
    assert validate_params("read_file", {"path": "test.py", "offset": 10}) is None
    assert validate_params("read_file", {}) is not None  # missing required
    assert validate_params("read_file", {"path": 123}) is not None  # wrong type
    assert validate_params("read_file", {"path": "x", "unknown": "y"}) is not None


def test_dispatch_read_file():
    result = dispatch("read_file", {"path": "requirements.txt"})
    assert result.ok
    assert "openai" in result.content


def test_dispatch_unknown_tool():
    result = dispatch("nonexistent", {"x": 1})
    assert not result.ok
    assert "Unknown tool" in result.content


def test_dispatch_bash():
    result = dispatch("bash", {"command": "echo hello"})
    assert result.ok
    assert "hello" in result.content


def test_dispatch_glob():
    result = dispatch("glob", {"pattern": "*.py"})
    assert result.ok


def test_dispatch_grep():
    result = dispatch("grep", {"pattern": "def test_", "path": "tests"})
    assert result.ok
    assert "test_tools.py" in result.content


if __name__ == "__main__":
    test_schema_generation()
    test_validate_params()
    test_dispatch_read_file()
    test_dispatch_unknown_tool()
    test_dispatch_bash()
    test_dispatch_glob()
    test_dispatch_grep()
    print("All tests passed!")
