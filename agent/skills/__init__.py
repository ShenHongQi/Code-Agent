"""Skill 系统：预定义工作流，自动审批，快捷执行。

内置 skill 从 agent/skills/*.md 加载（YAML frontmatter + Markdown prompt）。
用户自定义 skill 从 ~/.megumin/skills/*.yaml|.md 加载。
支持从 GitHub / Gist / URL 远程安装 skill。
"""

from __future__ import annotations
import re
import threading
import urllib.request
import urllib.error
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
    trigger: str = ""  # 自动触发条件描述（注入 system prompt）
    source: str = ""  # 来源文件路径

    def build_prompt(self, args: str, workspace: str = "") -> str:
        return self.prompt_template.format(args=args, workspace=workspace).strip()


# ─── Registry ───────────────────────────────────────────────────────────────

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


# ─── System prompt 集成 ─────────────────────────────────────────────────────

def get_skill_catalog() -> str:
    """生成 skill 目录文本，用于注入 system prompt。"""
    skills = get_all_skills()
    if not skills:
        return ""
    lines = []
    for s in sorted(skills, key=lambda x: x.name):
        trigger = f" — 触发: {s.trigger}" if s.trigger else ""
        lines.append(f"- **{s.name}**: {s.description}{trigger}")
    return "\n".join(lines)


# ─── Auto-approve ───────────────────────────────────────────────────────────

_auto_approve = threading.local()


def set_auto_approve(enabled: bool) -> None:
    _auto_approve.enabled = enabled


def is_auto_approve() -> bool:
    return getattr(_auto_approve, "enabled", False)


# ─── 执行 ──────────────────────────────────────────────────────────────────

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


# ─── .md 文件解析 ──────────────────────────────────────────────────────────

def _parse_skill_md(path: Path) -> Skill | None:
    """解析 skill .md 文件：YAML frontmatter + Markdown body。

    格式：
        ---
        name: review
        description: 审查代码变更
        aliases: [cr]
        auto_approve: true
        ---

        prompt 模板内容...
    """
    text = path.read_text(encoding="utf-8")

    # 分离 frontmatter 和 body
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None

    frontmatter = parts[1]
    body = parts[2].strip()
    if not body:
        return None

    # 简单解析 YAML frontmatter
    meta = _parse_simple_yaml(frontmatter)
    name = meta.get("name")
    if not name:
        return None

    return Skill(
        name=name,
        description=meta.get("description", ""),
        prompt_template=body,
        aliases=meta.get("aliases", []),
        auto_approve=meta.get("auto_approve", True),
        trigger=meta.get("trigger", ""),
        source=str(path),
    )


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """最小 YAML 解析器（不依赖 pyyaml）。"""
    data: dict[str, Any] = {}
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        if value.startswith("[") and value.endswith("]"):
            items = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
            data[key] = items
        elif value.lower() in ("true", "false"):
            data[key] = value.lower() == "true"
        else:
            data[key] = value.strip("'\"")
    return data


# ─── 加载内置 skills ────────────────────────────────────────────────────────

BUILTIN_SKILLS_DIR = Path(__file__).parent


def _load_builtin_skills() -> int:
    """从 agent/skills/*.md 加载内置 skill。"""
    if not BUILTIN_SKILLS_DIR.exists():
        return 0
    loaded = 0
    for path in sorted(BUILTIN_SKILLS_DIR.glob("*.md")):
        try:
            skill = _parse_skill_md(path)
            if skill:
                register_skill(skill)
                loaded += 1
        except Exception:
            pass
    return loaded


# ─── 加载用户自定义 skills ──────────────────────────────────────────────────

USER_SKILLS_DIR = Path.home() / ".megumin" / "skills"
SKILLS_DIR = USER_SKILLS_DIR  # 别名，兼容 commands.py


def load_user_skills() -> int:
    """从 ~/.megumin/skills/ 加载用户自定义 skill。

    支持 .yaml/.yml 和 .md 格式。
    """
    if not USER_SKILLS_DIR.exists():
        return 0

    loaded = 0
    for path in sorted(USER_SKILLS_DIR.iterdir()):
        if path.suffix in (".yaml", ".yml"):
            parser = _parse_skill_yaml
        elif path.suffix == ".md":
            parser = _parse_skill_md
        else:
            continue
        try:
            skill = parser(path)
            if skill and skill.name not in _skills:
                register_skill(skill)
                loaded += 1
        except Exception:
            pass
    return loaded


def _parse_skill_yaml(path: Path) -> Skill | None:
    """解析用户 .yaml skill 文件。"""
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

            if value in ("|", ">"):
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
        source=str(path),
    )


# ─── 远程安装 ──────────────────────────────────────────────────────────────

def _resolve_raw_url(url: str) -> str:
    """将 GitHub / Gist URL 转为 raw 下载地址。"""
    # GitHub blob → raw.githubusercontent.com
    m = re.match(
        r"https?://github\.com/([^/]+)/([^/]+)/blob/(.+)", url
    )
    if m:
        return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}"

    # Gist → raw（取第一个文件）
    m = re.match(r"https?://gist\.github\.com/([^/]+)/([a-f0-9]+)", url)
    if m:
        return f"https://gist.githubusercontent.com/{m.group(1)}/{m.group(2)}/raw"

    # 已经是 raw URL 或其他 URL，直接返回
    return url


def _convert_cursorrules(text: str, source_url: str) -> str:
    """将 .cursorrules 纯文本转换为 megumin skill .md 格式。"""
    name = Path(source_url.rstrip("/").split("/")[-1]).stem
    name = re.sub(r"[^a-z0-9_-]", "", name.lower().replace(".", "-")) or "imported"
    return (
        f"---\n"
        f"name: {name}\n"
        f"description: 从 cursorrules 导入\n"
        f"aliases: []\n"
        f"auto_approve: true\n"
        f"---\n\n"
        f"{text.strip()}\n\n"
        f"用户需求: {{args}}\n"
    )


def install_skill(url: str) -> tuple[Skill | None, str]:
    """从 URL 下载并安装 skill 到用户目录。

    返回 (skill, message)。skill 为 None 表示失败。
    支持:
      - GitHub 文件链接 (自动转 raw)
      - GitHub Gist 链接
      - 任意 .md / .yaml / .cursorrules 直链
    """
    raw_url = _resolve_raw_url(url)

    try:
        req = urllib.request.Request(raw_url, headers={"User-Agent": "megumin-agent/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return None, f"下载失败: HTTP {e.code}"
    except urllib.error.URLError as e:
        return None, f"连接失败: {e.reason}"
    except Exception as e:
        return None, f"下载失败: {e}"

    if not content.strip():
        return None, "下载的文件内容为空"

    # 检测格式并解析
    is_md = content.lstrip().startswith("---")
    is_cursorrules = ".cursorrules" in url or "cursorrules" in url.lower()

    if is_cursorrules and not is_md:
        content = _convert_cursorrules(content, url)
        is_md = True

    USER_SKILLS_DIR.mkdir(parents=True, exist_ok=True)

    if is_md:
        # 先写临时文件再解析
        tmp = USER_SKILLS_DIR / "_installing.md"
        tmp.write_text(content, encoding="utf-8")
        skill = _parse_skill_md(tmp)
        if not skill:
            tmp.unlink(missing_ok=True)
            return None, "文件格式无效：缺少 name 或 prompt 内容"
        dest = USER_SKILLS_DIR / f"{skill.name}.md"
        tmp.rename(dest)
        skill.source = str(dest)
    else:
        # 尝试当作 YAML 解析
        tmp = USER_SKILLS_DIR / "_installing.yaml"
        tmp.write_text(content, encoding="utf-8")
        skill = _parse_skill_yaml(tmp)
        if not skill:
            tmp.unlink(missing_ok=True)
            return None, "文件格式无效：缺少 name 或 prompt 内容"
        dest = USER_SKILLS_DIR / f"{skill.name}.yaml"
        tmp.rename(dest)
        skill.source = str(dest)

    register_skill(skill)
    return skill, f"已安装 skill '{skill.name}' → {dest}"


# ─── 模块初始化 ────────────────────────────────────────────────────────────

_load_builtin_skills()
load_user_skills()
