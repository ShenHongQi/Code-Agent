"""工作区安全测试：路径收敛、敏感文件拦截。"""

import sys
import os
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AGENT_API_KEY", "test")

from agent.workspace import Workspace, WorkspaceError, FileRegistry


def test_path_convergence():
    td = tempfile.mkdtemp()
    try:
        ws = Workspace(td)
        resolved = ws.resolve("src/main.py")
        assert str(resolved).endswith("src/main.py")
        assert str(ws.root) in str(resolved)
    finally:
        os.rmdir(td)


def test_path_escape_blocked():
    td = tempfile.mkdtemp()
    try:
        ws = Workspace(td)
        try:
            ws.resolve("../../etc/passwd")
            assert False, "Should have raised"
        except WorkspaceError as e:
            assert "escapes" in str(e)
    finally:
        os.rmdir(td)


def test_absolute_path_outside():
    td = tempfile.mkdtemp()
    try:
        ws = Workspace(td)
        try:
            ws.resolve("/etc/passwd")
            assert False, "Should have raised"
        except WorkspaceError as e:
            assert "escapes" in str(e)
    finally:
        os.rmdir(td)


def test_sensitive_files():
    td = tempfile.mkdtemp()
    try:
        ws = Workspace(td)
        from pathlib import Path
        try:
            ws.check_sensitive(Path(td) / ".env")
            assert False, "Should have raised"
        except WorkspaceError:
            pass

        try:
            ws.check_sensitive(Path(td) / "id_rsa")
            assert False, "Should have raised"
        except WorkspaceError:
            pass

        try:
            ws.check_sensitive(Path(td) / "secret.pem")
            assert False, "Should have raised"
        except WorkspaceError:
            pass
    finally:
        os.rmdir(td)


def test_file_registry():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("hello world")
        path = f.name

    try:
        from pathlib import Path
        p = Path(path)
        reg = FileRegistry()

        # Not yet read
        assert reg.check_freshness(p) is not None

        # Register read
        content = p.read_bytes()
        reg.register_read(p, content)
        assert reg.check_freshness(p) is None

        # Modify externally
        p.write_text("modified!")
        assert reg.check_freshness(p) is not None
    finally:
        os.unlink(path)


if __name__ == "__main__":
    test_path_convergence()
    test_path_escape_blocked()
    test_absolute_path_outside()
    test_sensitive_files()
    test_file_registry()
    print("All workspace tests passed!")
