"""插件系统：自动发现和加载外部工具扩展。"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path

from agent.tools import _REGISTRY, tool
from agent.workspace import Workspace

GLOBAL_PLUGINS_DIR = Path.home() / ".megumin" / "plugins"


@dataclass
class PluginManifest:
    name: str
    description: str
    tools_added: list[str]


def discover_plugins(workspace_root: str) -> list[Path]:
    """查找所有插件 .py 文件。"""
    plugin_files: list[Path] = []

    dirs = [
        GLOBAL_PLUGINS_DIR,
        Path(workspace_root) / ".megumin" / "plugins",
    ]

    for d in dirs:
        if d.is_dir():
            for f in sorted(d.glob("*.py")):
                if not f.name.startswith("_"):
                    plugin_files.append(f)

    return plugin_files


def load_plugin(path: Path, workspace: Workspace) -> PluginManifest | None:
    """加载单个插件文件。插件中使用 @tool 装饰器注册工具。"""
    before_tools = set(_REGISTRY.keys())

    spec = importlib.util.spec_from_file_location(f"plugin_{path.stem}", path)
    if not spec or not spec.loader:
        return None

    module = importlib.util.module_from_spec(spec)
    module.__dict__["workspace"] = workspace
    module.__dict__["tool"] = tool

    try:
        spec.loader.exec_module(module)
    except Exception as e:
        import sys
        print(f"  ⚠ Plugin {path.name} failed: {e}", file=sys.stderr)
        return None

    after_tools = set(_REGISTRY.keys())
    new_tools = sorted(after_tools - before_tools)

    if not new_tools:
        return None

    return PluginManifest(
        name=getattr(module, "PLUGIN_NAME", path.stem),
        description=getattr(module, "PLUGIN_DESCRIPTION", ""),
        tools_added=new_tools,
    )
