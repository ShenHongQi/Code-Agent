"""斜杠命令分发系统：注册 + 派发 /command。"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class CommandContext:
    """传递给命令 handler 的上下文。"""
    ui: Any
    history: Any
    session_mgr: Any
    session_meta: dict
    workspace: str
    thinking_history: list[str] = field(default_factory=list)
    input_mgr: Any = None
    provider: Any = None
    memory_mgr: Any = None
    _resume_result: Any = None  # /resume 命令写入 (new_history, new_meta)


@dataclass
class Command:
    name: str
    handler: Callable[[CommandContext, str], None]
    description: str
    aliases: list[str] = field(default_factory=list)


_commands: dict[str, Command] = {}


def register(name: str, handler: Callable[[CommandContext, str], None],
             description: str = "", aliases: list[str] | None = None) -> None:
    """注册一个斜杠命令。handler(ctx, args_str) -> None"""
    cmd = Command(name=name, handler=handler, description=description,
                  aliases=aliases or [])
    _commands[name] = cmd
    for alias in cmd.aliases:
        _commands[alias] = cmd


def dispatch(user_input: str, ctx: CommandContext) -> bool:
    """尝试分发斜杠命令。返回 True 表示已处理，调用者应 continue。"""
    if not user_input.startswith("/"):
        return False

    parts = user_input.split(None, 1)
    cmd_name = parts[0][1:].lower()  # 去掉 /
    args_str = parts[1] if len(parts) > 1 else ""

    if cmd_name in _commands:
        _commands[cmd_name].handler(ctx, args_str)
        return True

    # 未知命令提示
    ctx.ui.warning(f"未知命令: /{cmd_name}  (输入 /help 查看可用命令)")
    return True


def get_all_commands() -> list[Command]:
    """返回去重后的所有命令（不含别名重复）。"""
    seen = set()
    result = []
    for cmd in _commands.values():
        if cmd.name not in seen:
            seen.add(cmd.name)
            result.append(cmd)
    return result


# ─── 内置命令 ─────────────────────────────────────────────────────────────

def _cmd_help(ctx: CommandContext, args: str) -> None:
    """列出所有可用命令。"""
    commands = get_all_commands()
    ctx.ui.info("可用命令:")
    for cmd in sorted(commands, key=lambda c: c.name):
        alias_str = f" (别名: {', '.join('/' + a for a in cmd.aliases)})" if cmd.aliases else ""
        ctx.ui.info(f"  /{cmd.name:<12} {cmd.description}{alias_str}")


def _cmd_think(ctx: CommandContext, args: str) -> None:
    """展开上一轮的完整中间思考。"""
    ctx.ui.show_full_thinking(ctx.thinking_history)


def _cmd_resume(ctx: CommandContext, args: str) -> None:
    """交互式恢复历史会话。"""
    from agent.terminal import select_menu

    sessions = ctx.session_mgr.list_for_workspace(ctx.workspace)
    if not sessions:
        ctx.ui.warning("当前工作区没有历史会话。")
        return

    # 格式化选项（清除换行，避免菜单渲染错乱）
    items = []
    for s in sessions:
        updated = s.get("updated_at", "")[:16].replace("T", " ")
        turns = s.get("turns", 0)
        summary = s.get("summary", "").replace("\n", " ").strip()[:50]
        items.append(f"{updated}  {turns}轮  {summary}")

    idx = select_menu(items, title="选择要恢复的会话:")
    if idx is None:
        ctx.ui.info("已取消。")
        return

    # 加载选中的会话
    chosen = sessions[idx]
    session_id = chosen.get("session_id")
    try:
        messages, meta = ctx.session_mgr.load(session_id)
    except (OSError, KeyError, ValueError) as e:
        ctx.ui.error(f"加载失败: {e}")
        return

    # 重放历史
    ctx.ui.replay_history(messages)

    # 替换当前 history 和 session_meta
    from agent.history import History
    from agent.prompts import build_system_prompt

    system_prompt = build_system_prompt(ctx.workspace, ctx.memory_mgr)
    new_history = History.from_serializable(system_prompt, messages)

    # 通过 ctx 更新外部引用（由 __main__ 处理）
    ctx._resume_result = (new_history, meta)


register("help", _cmd_help, "显示所有可用命令", aliases=["h", "?"])
register("think", _cmd_think, "展开上一轮中间思考", aliases=["thinking"])
register("resume", _cmd_resume, "恢复历史会话", aliases=["r"])
