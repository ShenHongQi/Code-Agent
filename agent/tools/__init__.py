"""@tool registry、schema 生成、参数校验、dispatch。"""

from __future__ import annotations

import inspect
import json
from typing import Any, Callable, get_type_hints

_REGISTRY: dict[str, "ToolDef"] = {}

# Python type -> JSON Schema type
_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


class ToolResult:
    __slots__ = ("ok", "content")

    def __init__(self, ok: bool, content: str):
        self.ok = ok
        self.content = content


class ToolDef:
    def __init__(self, func: Callable, name: str, description: str, schema: dict[str, Any]):
        self.func = func
        self.name = name
        self.description = description
        self.schema = schema


def _parse_docstring(doc: str | None) -> tuple[str, dict[str, str]]:
    """从 docstring 提取函数描述和参数描述。"""
    if not doc:
        return "", {}
    lines = doc.strip().split("\n")
    desc_lines = []
    param_descs: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if ":" in stripped and not stripped.startswith(":"):
            parts = stripped.split(":", 1)
            candidate_name = parts[0].strip()
            if candidate_name.isidentifier() and not candidate_name[0].isupper():
                param_descs[candidate_name] = parts[1].strip()
                continue
        desc_lines.append(stripped)
    description = " ".join(desc_lines).strip()
    return description, param_descs


def _build_schema(func: Callable) -> tuple[str, dict[str, Any]]:
    """从函数签名和 docstring 生成 JSON Schema。"""
    hints = get_type_hints(func)
    sig = inspect.signature(func)
    doc = func.__doc__ or ""
    description, param_descs = _parse_docstring(doc)

    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        hint = hints.get(name, str)

        # Handle list[X] type
        origin = getattr(hint, "__origin__", None)
        if origin is list:
            args = getattr(hint, "__args__", (str,))
            item_type = _TYPE_MAP.get(args[0], "string") if args else "string"
            prop: dict[str, Any] = {"type": "array", "items": {"type": item_type}}
        else:
            json_type = _TYPE_MAP.get(hint, "string")
            prop = {"type": json_type}

        if name in param_descs:
            prop["description"] = param_descs[name]

        properties[name] = prop

        if param.default is inspect.Parameter.empty:
            required.append(name)

    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    schema["additionalProperties"] = False

    return description, schema


def tool(func: Callable) -> Callable:
    """装饰器：注册一个工具函数。"""
    name = func.__name__
    description, schema = _build_schema(func)
    _REGISTRY[name] = ToolDef(func, name, description, schema)
    return func


def get_registry() -> dict[str, ToolDef]:
    return _REGISTRY


def get_tools_schema(allowed: set[str] | None = None) -> list[dict[str, Any]]:
    """生成供 API 使用的 tools 参数。allowed 为 None 时返回全部。"""
    result = []
    for td in _REGISTRY.values():
        if allowed is not None and td.name not in allowed:
            continue
        result.append({
            "type": "function",
            "function": {
                "name": td.name,
                "description": td.description,
                "parameters": td.schema,
            },
        })
    return result


def validate_params(name: str, params: dict[str, Any]) -> str | None:
    """手写参数校验器。返回 None 表示合法，否则返回错误描述。"""
    td = _REGISTRY.get(name)
    if not td:
        return f"Unknown tool: {name}"

    schema = td.schema
    properties = schema.get("properties", {})
    required = schema.get("required", [])

    # Check required
    for req in required:
        if req not in params:
            return f"Missing required parameter: {req}"

    # Check types and unknown params
    for key, value in params.items():
        if key not in properties:
            return f"Unknown parameter: {key}"
        expected_type = properties[key].get("type")
        if not _check_type(value, expected_type):
            return f"Parameter '{key}' should be {expected_type}, got {type(value).__name__}"

    return None


def _check_type(value: Any, json_type: str | None) -> bool:
    if json_type is None:
        return True
    if json_type == "string":
        return isinstance(value, str)
    if json_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if json_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if json_type == "boolean":
        return isinstance(value, bool)
    if json_type == "array":
        return isinstance(value, list)
    if json_type == "object":
        return isinstance(value, dict)
    return True


def dispatch(name: str, params: dict[str, Any]) -> ToolResult:
    """校验参数并执行工具，永远返回 ToolResult，不抛异常。"""
    td = _REGISTRY.get(name)
    if not td:
        return ToolResult(False, f"Error: Unknown tool '{name}'")

    # Handle raw JSON parse failure
    if "__raw__" in params:
        schema_str = json.dumps(td.schema, indent=2)
        return ToolResult(
            False,
            f"Error: Invalid JSON in arguments. Expected schema:\n{schema_str}\n"
            f"Raw input: {params['__raw__'][:500]}"
        )

    error = validate_params(name, params)
    if error:
        schema_str = json.dumps(td.schema, indent=2)
        return ToolResult(False, f"Error: {error}\nExpected schema:\n{schema_str}")

    try:
        result = td.func(**params)
        if isinstance(result, ToolResult):
            return result
        return ToolResult(True, str(result))
    except Exception as e:
        return ToolResult(False, f"Error: {type(e).__name__}: {e}")
