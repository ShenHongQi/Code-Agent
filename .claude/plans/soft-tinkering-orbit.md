# Megumin Agent 能力升级方案

## Context

当前 agent 仅有 8 个工具、固定 40 轮迭代、无自我纠错、无并行执行——距离"可用的编程 agent"差距明显。本方案从四个维度全面升级，并为后续补强留好架构接口。

---

## A. 新增工具（8 → 16+）

### A1. 文件管理 — 修改 `agent/tools/fs.py`

```python
@tool delete_file(path: str)       # 删除文件（需先 read，带确认）
@tool rename_file(old: str, new: str)  # 重命名/移动
@tool list_dir(path: str=".", depth: int=1)  # 目录树，最深 3 层
```

### A2. 批量编辑 — 新建 `agent/tools/diff.py`

```python
@tool multi_edit(path: str, edits: str)  # JSON 数组 [{"old":"..","new":".."}]，原子批量替换
@tool view_diff(path: str=".")           # 显示 git diff
```
`multi_edit` 底部优先排序 + 一次性写入，解决当前 5 处修改需要 5 次 API 往返的问题。

### A3. 后台进程 — 新建 `agent/tools/proc.py`

```python
@tool spawn(command: str, label: str="")  # 启动后台进程（dev server 等）
@tool proc_status(pid: str="")            # 查看输出尾部 + 存活状态
@tool proc_kill(pid: str)                 # 终止后台进程
```
用 32KB 环形缓冲区存输出，atexit 清理所有子进程。

### A4. 网页抓取 — 新建 `agent/tools/web.py`

```python
@tool web_fetch(url: str, prompt: str="")  # 获取网页文本（文档查阅、错误搜索）
```
纯 urllib 实现，16KB 截断，HTML 简单去标签。网络请求归为 confirm 权限级别。

### A5. 升级 Sub-agent — 修改 `agent/tools/task.py`

```python
@tool task(description: str, tools: str="read_only")  
# tools: "read_only" | "write" | "full"
```
- 迭代上限 15 → 25
- 支持三级工具权限：只读 / 可写文件 / 全部（不含 task 自身）
- 深度仍为 1（防递归爆炸）

---

## B. 框架优化

### B1. 自适应迭代上限 — `agent/loop.py`

- 默认上限提高到 60
- 简单任务启发式判定为 QUICK_LIMIT=25
- 新增 `@tool extend_iterations(reason)` 允许 agent 动态申请延长

### B2. 卡死检测 + 自我反思 — `agent/loop.py`

当最近 3 次工具调用全部失败时，注入反思提示：
```
[System] 最近3次操作均失败。请停下来重新审视方案：
1. 重新阅读相关文件 2. 尝试不同策略 3. 用 todo_write 重新规划
```

### B3. 并行工具执行 — `agent/loop.py`

读操作（read_file, glob, grep, list_dir, view_diff）并行执行（ThreadPoolExecutor, max_workers=4）。
写操作保持顺序执行。

### B4. bash 去重 — `agent/tools/bash.py`

当前 bash.py 内联了 ShellRunner 的全部逻辑（~80行重复代码）。重构为委托给 `ShellRunner.run()` 再包装结果，约 15 行。

### B5. 更好的错误恢复 — `agent/llm.py`

- 流中断（connection reset）归类为 retryable
- 增加对 incomplete JSON 的容错（tool_call arguments 被截断时保留已有部分）

---

## C. 权限系统升级

### C1. 上下文感知 — `agent/permission.py`

```python
SAFE_DELETE_TARGETS = {"node_modules", "__pycache__", "dist", "build", ".egg-info", ...}
```
`rm -rf node_modules` 等可再生目标自动降级为 allow。

### C2. 会话级权限记忆

用户批准一次 `pip install` 后，同类命令本次会话内自动放行：
```python
class PermissionState:
    _session_allows: set[str]  # 已批准的 pattern
    def remember_allow(command)
    def is_session_approved(command) -> bool
```

### C3. 确认 UX 升级

```
──────────────────────────────────────────────────────
⚠ 需要确认:
  git push origin main
──────────────────────────────────────────────────────
  [y] 允许一次  [a] 本次会话允许同类  [n] 拒绝  > 
```
三选项：一次允许 / 会话允许 / 拒绝。

---

## D. 架构升级（面向未来补强）

### D1. 插件系统 — 新建 `agent/plugins.py`

插件目录：`~/.megumin/plugins/` 和 `{workspace}/.megumin/plugins/`

插件 = 独立 .py 文件，用 `@tool` 装饰器注册新工具。启动时自动发现加载。
插件不能覆盖内置工具，只能新增。

### D2. 事件钩子 — 新建 `agent/hooks.py`

```python
class Event(Enum):
    BEFORE_LLM_CALL, AFTER_LLM_CALL,
    BEFORE_TOOL_EXEC, AFTER_TOOL_EXEC,
    ON_ERROR, ON_STUCK,
    ON_TURN_START, ON_TURN_END, ON_COMPACTION

def register(event, handler): ...
def emit(event, **kwargs): ...
```
插件和内部模块均可注册 hook，用于日志、监控、自定义行为。

### D3. Multi-Model 预留 — `agent/llm.py`

```python
class ModelRouter:
    def __init__(self, default_provider): ...
    def register_route(task_type, provider): ...
    def get_provider(task_type="default") -> Provider: ...
```
为后续"摘要用廉价模型、代码用强模型"做接口预留。暂不实装路由逻辑。

---

## 实现顺序

| 阶段 | 内容 | 预计改动 |
|------|------|----------|
| 1 | 基础: bash 重构 + config 扩展 + 权限升级 | ~150 行 |
| 2 | 新工具: fs 扩展 + diff + proc + web | ~350 行 |
| 3 | Loop 智能: 自适应迭代 + 卡死反思 + 并行执行 | ~200 行 |
| 4 | 可扩展性: plugins + hooks + sub-agent 升级 | ~200 行 |
| 5 | 整合: prompts 更新 + __main__ 接入 + 测试 | ~100 行 |

总计新增约 1000 行，项目从 ~2900 行增长到 ~3900 行。

---

## 文件改动清单

| 文件 | 操作 | 关键改动 |
|------|------|----------|
| `agent/config.py` | 修改 | 新增 max_iterations=60, parallel_tools, plugins_enabled 等 |
| `agent/permission.py` | 修改 | PermissionState、context-aware 规则、三选项 UX |
| `agent/tools/bash.py` | 重构 | 委托 ShellRunner，~15 行替代 ~80 行 |
| `agent/tools/fs.py` | 修改 | 新增 delete_file, rename_file, list_dir |
| `agent/tools/diff.py` | 新建 | multi_edit, view_diff |
| `agent/tools/proc.py` | 新建 | spawn, proc_status, proc_kill |
| `agent/tools/web.py` | 新建 | web_fetch |
| `agent/tools/task.py` | 修改 | 三级工具权限, 25 轮上限 |
| `agent/loop.py` | 修改 | 并行执行, 卡死检测, 自适应上限, extend_iterations |
| `agent/llm.py` | 修改 | 流中断容错, ModelRouter 预留 |
| `agent/plugins.py` | 新建 | 插件发现/加载 |
| `agent/hooks.py` | 新建 | 事件系统 |
| `agent/prompts.py` | 修改 | 更新工具列表描述 |
| `agent/__main__.py` | 修改 | 插件加载, 新工具注册, hook 接入 |

---

## 验证

1. 现有 31 个测试全部通过
2. `megumin` 启动后 `bash("ls")` / `read_file` / `edit_file` 正常
3. `multi_edit` 一次修改 3 处不冲突
4. `spawn("python -m http.server 8080")` 后 `proc_status` 可见输出
5. `web_fetch("https://docs.python.org/3/")` 返回文本
6. 连续 3 次 edit_file 失败 → 自动注入反思提示
7. 敏感命令 `git push` → 三选项确认 UI → 选 [a] → 后续同类自动放行
8. `~/.megumin/plugins/` 放一个简单 .py 工具 → 启动时自动加载
