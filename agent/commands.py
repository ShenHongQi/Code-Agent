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
    _skill_executed: bool = False  # skill 执行后标记（用于保存会话）
    _goal_set: str | None = None  # /goal 命令设置自动目标
    _plan_request: str | None = None  # /plan 命令设置规划请求


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

    ctx.ui.info("命令:")
    for cmd in sorted(commands, key=lambda c: c.name):
        alias_str = f" ({', '.join('/' + a for a in cmd.aliases)})" if cmd.aliases else ""
        ctx.ui.info(f"  /{cmd.name:<12} {cmd.description}{alias_str}")

    from agent.skills import get_all_skills
    skills = get_all_skills()
    if skills:
        ctx.ui.info("\nSkills (/skill <name> 执行):")
        for s in sorted(skills, key=lambda x: x.name):
            alias_str = f" ({', '.join(s.aliases)})" if s.aliases else ""
            ctx.ui.info(f"  {s.name:<12} {s.description}{alias_str}")


def _cmd_think(ctx: CommandContext, args: str) -> None:
    """展开上一轮的完整中间思考。"""
    ctx.ui.show_full_thinking(ctx.thinking_history)


def _cmd_resume(ctx: CommandContext, args: str) -> None:
    """交互式恢复历史会话。"""
    from agent.terminal import select_menu

    all_sessions = ctx.session_mgr.list_for_workspace(ctx.workspace)
    sessions = [s for s in all_sessions if s.get("turns", 0) > 0]
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
    ctx.ui.replay_history(messages, model=meta.get("model", ""))

    # 替换当前 history 和 session_meta
    from agent.history import History
    from agent.prompts import build_system_prompt

    system_prompt = build_system_prompt(ctx.workspace, ctx.memory_mgr)
    new_history = History.from_serializable(system_prompt, messages)

    # 通过 ctx 更新外部引用（由 __main__ 处理）
    ctx._resume_result = (new_history, meta)


def _cmd_skill(ctx: CommandContext, args: str) -> None:
    """列出或执行 skill。"""
    from agent.skills import SKILLS_DIR, execute_skill, get_all_skills, get_skill

    # /skill 或 /skill list → 列出所有 skill
    if not args or args.strip() == "list":
        skills = get_all_skills()
        ctx.ui.info("可用 Skills:")
        for s in sorted(skills, key=lambda x: x.name):
            alias_str = f" ({', '.join(s.aliases)})" if s.aliases else ""
            auto_str = " ⚡" if s.auto_approve else ""
            ctx.ui.info(f"  {s.name:<12}{s.description}{alias_str}{auto_str}")
        ctx.ui.info("\n  用法: /skill <name> [参数]")
        ctx.ui.info("  ⚡ = 自动审批（无需确认权限）")
        ctx.ui.info("  安装: /skill install <url>")
        ctx.ui.info(f"  自定义: {SKILLS_DIR}/*.md")
        return

    # /skill create → 创建自定义 skill 模板
    if args.strip() == "create":
        _create_skill_template(ctx)
        return

    # /skill install <url> → 远程安装 skill
    if args.strip().startswith("install"):
        _install_skill(ctx, args.strip()[len("install"):].strip())
        return

    # /skill <name> [args...]
    parts = args.split(None, 1)
    skill_name = parts[0].lower()
    skill_args = parts[1] if len(parts) > 1 else ""

    skill = get_skill(skill_name)
    if not skill:
        ctx.ui.warning(f"未知 skill: {skill_name}")
        ctx.ui.info("输入 /skill list 查看可用列表")
        return

    # 标记为 skill 执行
    ctx._skill_executed = True
    execute_skill(
        skill=skill,
        args=skill_args,
        history=ctx.history,
        provider=ctx.provider,
        ui=ctx.ui,
        memory_mgr=ctx.memory_mgr,
        workspace_root=ctx.workspace,
        thinking_log=ctx.thinking_history,
    )


def _create_skill_template(ctx: CommandContext) -> None:
    """在 ~/.megumin/skills/ 创建一个示例 skill 模板。"""
    from agent.skills import SKILLS_DIR

    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    template_path = SKILLS_DIR / "example.yaml"

    if template_path.exists():
        ctx.ui.info(f"模板已存在: {template_path}")
        return

    template_path.write_text("""\
name: example
description: 示例 skill（修改此文件或复制创建新 skill）
aliases: [eg]
auto_approve: true
prompt: |
  这是一个示例 skill 的 prompt 模板。
  用户参数: {args}
  工作区: {workspace}

  请在此编写你的 skill 指令。
  agent 会按照此 prompt 自动执行任务。
""", encoding="utf-8")

    ctx.ui.info(f"已创建示例模板: {template_path}")
    ctx.ui.info("编辑此文件或复制为新文件来创建自定义 skill。")
    ctx.ui.info("重启 megumin 后生效。")


def _install_skill(ctx: CommandContext, url: str) -> None:
    """从远程 URL 安装 skill。"""
    from agent.skills import install_skill

    if not url:
        ctx.ui.info("用法: /skill install <url>")
        ctx.ui.info("")
        ctx.ui.info("支持的来源:")
        ctx.ui.info("  GitHub 文件  https://github.com/user/repo/blob/main/skill.md")
        ctx.ui.info("  GitHub Gist  https://gist.github.com/user/hash")
        ctx.ui.info("  Raw URL      https://example.com/my-skill.md")
        ctx.ui.info("  Cursorrules  https://github.com/user/repo/blob/main/.cursorrules")
        ctx.ui.info("")
        ctx.ui.info("格式: .md（YAML frontmatter）/ .yaml / .cursorrules（自动转换）")
        return

    if not url.startswith(("http://", "https://")):
        ctx.ui.warning("请提供完整的 URL（以 http:// 或 https:// 开头）")
        return

    ctx.ui.info("正在下载 skill …")

    skill, message = install_skill(url)
    if skill:
        ctx.ui.info(f"✓ {message}")
        alias_str = f"  别名: {', '.join(skill.aliases)}" if skill.aliases else ""
        ctx.ui.info(f"  描述: {skill.description}{alias_str}")
        ctx.ui.info(f"  使用: /skill {skill.name} [参数]")
    else:
        ctx.ui.error(f"✗ {message}")


def _cmd_goal(ctx: CommandContext, args: str) -> None:
    """设定自动目标，agent 自主迭代完成。"""
    if not args:
        # 显示当前目标状态
        ctx.ui.info("用法: /goal <目标描述>  — 设定目标并自动执行")
        ctx.ui.info("      /goal clear       — 清除当前目标")
        return

    if args.strip().lower() == "clear":
        ctx._goal_set = "__clear__"
        ctx.ui.info("🎯 目标已清除，回到交互模式。")
        return

    ctx._goal_set = args.strip()
    ctx.ui.info(f"🎯 目标已设定: {args.strip()}")
    ctx.ui.info("   进入自动模式，agent 将自主工作直到完成。")
    ctx.ui.info("   按 ESC 可中断，/goal clear 取消目标。")


def _cmd_plan(ctx: CommandContext, args: str) -> None:
    """进入设计方案模式：先规划再执行。"""
    if not args:
        ctx.ui.info("用法: /plan <需求描述>  — 进入方案设计模式")
        ctx.ui.info("      agent 将先分析代码、输出方案，待你确认后再执行。")
        return

    ctx._plan_request = args.strip()
    ctx.ui.info(f"📋 进入方案设计模式: {args.strip()}")
    ctx.ui.info("   agent 将分析代码并输出实现方案，等待你的确认。")


def _cmd_permissions(ctx: CommandContext, args: str) -> None:
    """查看或切换权限模式。"""
    from agent.permission import (
        PermissionMode,
        get_permission_mode,
        set_permission_mode,
    )

    current = get_permission_mode()

    if not args:
        from agent.terminal import select_menu

        modes = [
            ("suggest", "全部操作需确认（最保守）"),
            ("auto-edit", "文件编辑自动通过，危险命令仍确认"),
            ("full-auto", "全自动（仅高危/危险仍确认）"),
        ]

        items = []
        for val, desc in modes:
            marker = " ◀" if val == current.value else ""
            items.append(f"{val:<12} {desc}{marker}")

        idx = select_menu(items, title="选择权限模式:")
        if idx is None:
            ctx.ui.info("已取消。")
            return

        new_mode = PermissionMode(modes[idx][0])
        set_permission_mode(new_mode)
        ctx.ui.info(f"权限模式已切换: {new_mode.value} — {modes[idx][1]}")
        return

    mode_str = args.strip().lower()
    try:
        new_mode = PermissionMode(mode_str)
    except ValueError:
        ctx.ui.warning(f"未知模式: {mode_str}")
        ctx.ui.info("可选: suggest / auto-edit / full-auto")
        return

    set_permission_mode(new_mode)
    ctx.ui.info(f"权限模式已切换: {new_mode.value}")


register("help", _cmd_help, "显示所有可用命令", aliases=["h", "?"])
register("think", _cmd_think, "展开上一轮中间思考", aliases=["thinking"])
register("resume", _cmd_resume, "恢复历史会话", aliases=["r"])
register("skill", _cmd_skill, "执行预定义工作流", aliases=["s"])
register("goal", _cmd_goal, "自动目标模式", aliases=["g"])
register("plan", _cmd_plan, "设计方案模式", aliases=["p"])
register("permissions", _cmd_permissions, "查看/切换权限模式", aliases=["perm"])
