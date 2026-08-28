# 记忆系统 + 会话持久化 + 动态 System Prompt 实现方案

## Context

当前 megumin 所有会话状态纯内存——退出即丢失。用户要求：
1. 简化输入框为上下两条分隔线
2. 实现跨会话记忆、会话恢复、会话日志
3. 记忆系统与 system prompt 动态联动

---

## 1. 输入框简化

**文件**: `agent/terminal.py` → `InputManager.styled_input()`

改为：
```
────────────────────────────────────────
> 用户输入
────────────────────────────────────────
```

去掉 `╭─ You` / `╰` / `│` box-drawing 字符，改用 `─` 横线做上下分隔。prompt 符号用 `> `。

---

## 2. 会话日志与恢复

**新建文件**: `agent/session.py`

### 存储结构
```
~/.megumin/sessions/
  {workspace_hash}_{iso_timestamp}.json
```

`workspace_hash` = workspace 绝对路径 SHA1 前 8 位，确保同项目的会话聚合。

### SessionManager 接口
```python
class SessionManager:
    def __init__(self, sessions_dir: Path)
    def save(self, history: History, meta: dict) -> Path
    def load(self, session_id: str) -> tuple[list[dict], dict]
    def latest_for_workspace(self, workspace: str) -> dict | None
    def cleanup(self, keep: int = 20) -> None  # 保留最近 20 个
```

### 序列化
- `History` 新增 `to_serializable() -> list[dict]` 和类方法 `from_serializable(system_prompt, messages)`
- 格式为 JSON：`{"meta": {...}, "messages": [...]}`
- meta 包含：session_id, workspace, model, created_at, updated_at, turns, summary

### 自动保存
- 每轮 `_run_turn()` 结束后调用 `session_mgr.save()`
- 退出时（exit/Ctrl+D/EscInterrupt）最终保存

### 恢复流程
启动时 `SessionManager.latest_for_workspace()` 检查是否有最近会话：
- 有 → 单行提示 `[r] 恢复 / [n] 新建`
- 选 r → `History.from_serializable()` 加载消息继续对话
- 选 n → 正常启动

### 修改文件
- `agent/history.py`: 添加 `to_serializable()` / `from_serializable()`
- `agent/__main__.py`: 接入 SessionManager（保存、恢复提示）

---

## 3. 跨会话记忆系统

**新建文件**: `agent/memory.py`

### 两级记忆

| 级别 | 路径 | 范围 |
|------|------|------|
| 全局 | `~/.megumin/memory/global.md` | 用户偏好、通用知识 |
| 项目 | `{workspace}/.megumin/memory.md` | 项目架构、约定、已知问题 |

### 格式（Markdown 分段）
```markdown
## Preferences
- 用户偏好简洁回答

## Architecture  
- Flask + React，数据库 PostgreSQL

## Conventions
- commit message 用中文
```

### MemoryManager 接口
```python
class MemoryManager:
    def __init__(self, workspace: str)
    def load_global(self) -> str
    def load_project(self) -> str
    def append(self, entry: str, scope: str = "project") -> None
    def remove(self, keyword: str, scope: str = "project") -> bool
    def get_mtime(self) -> tuple[float, float]  # (global_mtime, project_mtime)
```

### 显式写入（新工具）

**新建文件**: `agent/tools/memory.py`

```python
@tool
def memory_write(content: str, scope: str = "project") -> ToolResult:
    """保存信息到记忆中。scope: "project" 或 "global"。"""

@tool  
def memory_read(scope: str = "project") -> ToolResult:
    """读取当前记忆内容。"""

@tool
def memory_forget(keyword: str, scope: str = "project") -> ToolResult:
    """删除包含关键词的记忆条目。"""
```

### 隐式提取（compaction 时）

修改 `agent/context.py` 的 `_summarize()` 方法：
- 摘要 prompt 中增加指示："如果对话中有长期有价值的项目信息，在输出末尾标记 `[MEMORY] xxx`"
- compaction 完成后，解析 `[MEMORY]` 行，调用 `MemoryManager.append()` 写入项目记忆

---

## 4. 动态 System Prompt

**修改文件**: `agent/prompts.py`

### 新签名
```python
def build_system_prompt(workspace_root: str, memory_mgr: MemoryManager | None = None) -> str:
```

### 组装顺序
1. **基础身份规则**（固定文本，当前 `SYSTEM_PROMPT_TEMPLATE` 拆为 base 部分）
2. **项目记忆**（如有）→ `## Project Context\n{project_mem}`
3. **工作区结构**（当前已有的目录扫描）
4. **全局记忆/用户偏好**（如有）→ `## User Preferences\n{global_mem}`
5. **工具列表 + 规则**（固定）

### 热更新

在 `agent/loop.py` 的 `run_loop()` 每次迭代开头：
- 检查 `MemoryManager.get_mtime()` 是否变化
- 如变化 → 重新调用 `build_system_prompt()` → 更新 `history._system`

这样 `memory_write` 工具执行后，下一次 LLM 调用就会包含新记忆。

---

## 5. 完整改动清单

| 文件 | 类型 | 改动 |
|------|------|------|
| `agent/terminal.py` | 修改 | `styled_input()` 简化为两线 |
| `agent/session.py` | 新建 | SessionManager 类 |
| `agent/memory.py` | 新建 | MemoryManager 类 |
| `agent/tools/memory.py` | 新建 | memory_write/read/forget 工具 |
| `agent/history.py` | 修改 | `to_serializable()` / `from_serializable()` |
| `agent/prompts.py` | 修改 | 接受 MemoryManager，动态组装 |
| `agent/context.py` | 修改 | compaction 隐式提取 [MEMORY] |
| `agent/loop.py` | 修改 | memory mtime 热更新 |
| `agent/__main__.py` | 修改 | 接入 session/memory，恢复提示 |
| `agent/tools/__init__.py` | 修改 | 注册 memory 工具 |

---

## 6. 验证

1. **输入框**: 启动后确认只有上下两条 `─` 线
2. **会话保存**: 对话 3 轮 → 退出 → 检查 `~/.megumin/sessions/` 有 JSON 文件
3. **会话恢复**: 同目录重启 → 提示恢复 → 选 r → 确认历史在
4. **显式记忆**: 说"记住这个项目用 pytest" → 检查 `.megumin/memory.md` 包含该内容
5. **记忆注入**: 重启 → 首次 LLM 请求的 system prompt 包含记忆内容
6. **全局记忆**: 说"记住我喜欢简洁回答" → 切到另一目录启动 → system prompt 含偏好
7. **隐式提取**: 长对话触发 compaction → 检查 memory.md 追加了有价值条目
8. **热更新**: 同一会话中 memory_write 后，下一轮 system prompt 已更新
9. **现有测试**: `uv run pytest` 全部通过
