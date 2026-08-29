"""Skill 系统：预定义工作流，自动审批，快捷执行。

支持内置 skill 和用户自定义 skill（~/.megumin/skills/*.yaml）。
"""

from __future__ import annotations
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Skill:
    name: str
    description: str
    prompt_template: str
    aliases: list[str] = field(default_factory=list)
    auto_approve: bool = True

    def build_prompt(self, args: str, workspace: str = "") -> str:
        """根据参数构建最终 prompt。"""
        return self.prompt_template.format(args=args, workspace=workspace).strip()


# ─── Skill Registry ─────────────────────────────────────────────────────────

_skills: dict[str, Skill] = {}


def register_skill(skill: Skill) -> None:
    _skills[skill.name] = skill
    for alias in skill.aliases:
        _skills[alias] = skill


def get_skill(name: str) -> Skill | None:
    return _skills.get(name)


def get_all_skills() -> list[Skill]:
    seen = set()
    result = []
    for skill in _skills.values():
        if skill.name not in seen:
            seen.add(skill.name)
            result.append(skill)
    return result


# ─── Auto-approve 全局开关 ──────────────────────────────────────────────────

_auto_approve = threading.local()


def set_auto_approve(enabled: bool) -> None:
    _auto_approve.enabled = enabled


def is_auto_approve() -> bool:
    return getattr(_auto_approve, "enabled", False)


# ─── Skill 执行 ─────────────────────────────────────────────────────────────

def execute_skill(
    skill: Skill,
    args: str,
    history: Any,
    provider: Any,
    ui: Any,
    memory_mgr: Any = None,
    workspace_root: str = "",
    thinking_log: list[str] | None = None,
) -> None:
    """执行一个 skill：构建 prompt → 开启 auto_approve → 跑 agent loop。"""
    from agent.history import make_user
    from agent.loop import run_loop

    prompt = skill.build_prompt(args, workspace_root)

    ui.info(f"⚡ 执行 skill: {skill.name}")
    if args:
        ui.info(f"   参数: {args}")

    history.append(make_user(prompt))

    if skill.auto_approve:
        set_auto_approve(True)

    try:
        result = run_loop(
            history, provider, ui,
            memory_mgr=memory_mgr,
            workspace_root=workspace_root,
            thinking_log=thinking_log,
        )
        if result.reason == "max_iterations":
            ui.warning(f"Skill 达到迭代上限 ({result.iterations})。")
    finally:
        set_auto_approve(False)


# ─── 内置 Skills ────────────────────────────────────────────────────────────

register_skill(Skill(
    name="review",
    description="审查代码变更，给出改进建议",
    aliases=["cr"],
    prompt_template="""\
请审查当前工作区的代码变更（使用 view_diff 或 git diff），分析以下方面：
1. 正确性：是否有逻辑错误或 bug
2. 安全性：是否有安全隐患
3. 可维护性：代码风格、命名、结构
4. 性能：是否有性能问题

{args}

给出具体的问题列表和改进建议。对每个问题引用具体的代码行。""",
))

register_skill(Skill(
    name="test",
    description="为指定代码生成测试",
    aliases=["t"],
    prompt_template="""\
为以下目标生成完整的单元测试：
{args}

要求：
1. 先阅读目标代码理解其功能
2. 覆盖正常路径、边界条件和异常情况
3. 使用项目已有的测试框架和风格
4. 测试文件放在合适的位置
5. 运行测试确保通过""",
))

register_skill(Skill(
    name="explain",
    description="详细解释代码实现",
    aliases=["ex"],
    auto_approve=False,
    prompt_template="""\
请详细解释以下代码的实现：
{args}

从以下角度分析：
1. 整体架构和设计模式
2. 核心数据流
3. 关键函数的作用
4. 依赖关系
5. 可能的改进点""",
))

register_skill(Skill(
    name="commit",
    description="生成 commit message 并提交",
    aliases=["ci"],
    prompt_template="""\
请完成以下操作：
1. 使用 bash 运行 git diff --cached（如果没有暂存内容则运行 git diff）
2. 根据变更内容生成规范的 commit message（Conventional Commits 格式）
3. 如果有未暂存的变更，先 git add 相关文件
4. 执行 git commit

{args}

Commit message 格式：type(scope): description
type: feat/fix/refactor/docs/style/test/chore""",
))

register_skill(Skill(
    name="fix",
    description="分析并修复问题",
    aliases=["f"],
    prompt_template="""\
请分析并修复以下问题：
{args}

步骤：
1. 理解问题描述
2. 定位相关代码
3. 分析根因
4. 实施修复
5. 验证修复（运行相关测试或手动验证）""",
))

register_skill(Skill(
    name="refactor",
    description="重构代码，改善结构",
    aliases=["rf"],
    prompt_template="""\
请对以下目标进行重构：
{args}

原则：
1. 先阅读理解现有代码
2. 保持功能不变（行为等价）
3. 改善代码结构、可读性、可维护性
4. 如有测试，确保重构后测试仍通过
5. 逐步重构，每步可验证""",
))

register_skill(Skill(
    name="doc",
    description="生成或更新文档",
    aliases=["d"],
    prompt_template="""\
请为以下目标生成/更新文档：
{args}

要求：
1. 阅读代码理解功能
2. 生成清晰准确的文档
3. 包含：概述、用法示例、API 说明、注意事项
4. 使用 Markdown 格式
5. 放在合适的位置（README、docs/ 目录或行内注释）""",
))

register_skill(Skill(
    name="push",
    description="提交并推送到远程",
    aliases=["p"],
    prompt_template="""\
请完成代码提交和推送：
1. git status 查看当前状态
2. git add 暂存所有相关变更
3. 根据变更内容生成规范的 commit message
4. git commit
5. git push

{args}

注意：不要 force push。如果有冲突先 pull 解决。""",
))

register_skill(Skill(
    name="init",
    description="初始化项目结构",
    aliases=[],
    prompt_template="""\
请在当前工作区初始化项目：
{args}

如果没有指定具体类型，请根据现有文件推断项目类型并：
1. 确认/创建合适的项目结构
2. 初始化包管理（package.json/pyproject.toml 等）
3. 设置 .gitignore
4. 创建基本的 README.md
5. 如有需要，安装依赖""",
))


# ─── 用户自定义 Skills ──────────────────────────────────────────────────────

SKILLS_DIR = Path.home() / ".megumin" / "skills"


def load_user_skills() -> int:
    """从 ~/.megumin/skills/ 加载用户自定义 skill。

    支持 .yaml/.yml 格式：
        name: my-skill
        description: 做某件事
        aliases: [ms]
        auto_approve: true
        prompt: |
          请执行以下任务：
          {args}

    返回加载的 skill 数量。
    """
    if not SKILLS_DIR.exists():
        return 0

    loaded = 0
    for path in sorted(SKILLS_DIR.iterdir()):
        if path.suffix not in (".yaml", ".yml"):
            continue
        try:
            skill = _parse_skill_file(path)
            if skill and skill.name not in _skills:
                register_skill(skill)
                loaded += 1
        except Exception:
            pass
    return loaded


def _parse_skill_file(path: Path) -> Skill | None:
    """简单 YAML 解析（不依赖 pyyaml）。"""
    text = path.read_text(encoding="utf-8")
    data: dict[str, Any] = {}
    current_key = ""
    multiline_buf: list[str] = []
    in_multiline = False

    for line in text.split("\n"):
        if in_multiline:
            if line and not line[0].isspace() and ":" in line:
                data[current_key] = "\n".join(multiline_buf)
                in_multiline = False
            else:
                multiline_buf.append(line.lstrip())
                continue

        if not in_multiline:
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()

            if value == "|" or value == ">":
                current_key = key
                multiline_buf = []
                in_multiline = True
            elif value.startswith("[") and value.endswith("]"):
                items = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
                data[key] = items
            elif value.lower() in ("true", "false"):
                data[key] = value.lower() == "true"
            else:
                data[key] = value.strip("'\"")

    if in_multiline:
        data[current_key] = "\n".join(multiline_buf)

    name = data.get("name")
    prompt = data.get("prompt", "")
    if not name or not prompt:
        return None

    return Skill(
        name=name,
        description=data.get("description", ""),
        prompt_template=prompt,
        aliases=data.get("aliases", []),
        auto_approve=data.get("auto_approve", True),
    )


# 模块加载时自动加载用户 skills
load_user_skills()
