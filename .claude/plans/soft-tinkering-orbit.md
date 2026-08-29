# Plan: Skill 交互改进 + 自动触发 + Markdown 表格修复

## Context

用户反馈三个问题：
1. 选中 skill 后立即执行，用户没机会输入参数
2. Skill 只能手动触发，缺少自动触发机制
3. Markdown 表格无法正常渲染

---

## A. Skill 选中后继续输入（`agent/terminal.py`）

**现状**：`_slash_input()` 中，在 skill 模式下按 Enter 直接 `return "/skill " + chosen_name`，用户无法输入参数。

**改法**：Enter 在 skill 模式下的行为改为「填充 buffer 并继续输入」，与一级选中 `/skill` 进入二级模式的逻辑一致。

修改 Enter 处理（约 line 330）：
- 原：`result = "/skill " + chosen_name` → return
- 新：`buffer = "/skill " + chosen_name + " "` → selected=0 → _render() → continue

当 buffer 是 `/skill review something` 时，`_get_matches()` 的 query 不匹配任何 skill name，下拉框自然消失，变成普通文本输入。用户按 Enter 走 `else: result = buffer` 正常返回。

---

## B. Skill 自动触发（`agent/prompts.py` + `agent/skills/__init__.py` + `*.md`）

**设计**：在 system prompt 注入 skill 目录 + 触发条件。模型识别匹配 skill 后主动采用其工作流。不新增工具，纯 prompt 级别。

### B1. Skill dataclass 加 `trigger` 字段
`agent/skills/__init__.py`：Skill 新增 `trigger: str = ""`，`_parse_skill_md()` 构造时加 `trigger=meta.get("trigger", "")`。

### B2. 内置 skill `.md` 加 trigger
每个 `agent/skills/*.md` 的 YAML frontmatter 加 `trigger` 行。

### B3. System prompt 注入
`agent/prompts.py` 的 `build_system_prompt()` 在 BASE_PROMPT 之后插入 skill 目录 section。

---

## C. Markdown 表格渲染（`agent/markdown.py`）

新增表格状态机：`_in_table` + `_table_rows` 缓冲。
- 检测到 `|` 开头的行进入表格模式，缓冲行
- 非表格行或 flush 时渲染为带 `┌┬┐├┼┤└┴┘` 边框的对齐表格
- 识别分隔行（`|---|`），区分表头/数据行
- 支持 `:` 对齐标记

---

## 修改文件清单

| 文件 | 改动 |
|------|------|
| `agent/terminal.py` | Enter: skill 模式改为填充 buffer + continue |
| `agent/skills/__init__.py` | Skill 加 trigger 字段；parse 时读取 |
| `agent/prompts.py` | build_system_prompt 注入 skill 目录 |
| `agent/markdown.py` | 表格状态机 + _render_table() |
| `agent/skills/*.md` (11 files) | frontmatter 加 trigger 行 |

## 验证

1. 启动 megumin，`/skill` → 选 skill → 确认可继续输入参数
2. 发送匹配 skill 的请求，确认 agent 采用对应工作流
3. 让 agent 输出表格，确认渲染正确
4. `/help`、`/think`、`/resume` 不受影响
