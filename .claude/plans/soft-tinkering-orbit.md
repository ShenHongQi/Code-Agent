# Plan: 区分中间思考与最终输出 + 截断展开

## Context

当前 agent 的中间思考（每轮迭代中模型输出的推理文本）和最终回答使用完全相同的样式渲染（`● Assistant` + 完整 Markdown），用户无法区分哪些是中间过程、哪些是最终结果。需要：
1. 中间思考淡化（DIM 样式 + 截断）
2. 最终输出保持突出（完整 Markdown 渲染）
3. 超长中间思考支持展开查看

## 方案

### 核心思路

将流式输出改为"缓冲 → 判断 → 渲染"模式：
- LLM 调用期间：spinner 动画显示思考状态（不实时输出 token）
- 调用结束后判断类型：
  - **中间迭代**（has_tool_calls）：DIM 样式，最多显示 3 行，超出部分显示 `... (省略 N 行, /think 展开)`
  - **最终回答**（is_natural_stop）：完整 Markdown 渲染，正常亮度，`● Assistant` 标题

### 修改文件

#### 1. `agent/ui.py` — 拆分为两种显示模式

- 新增 `show_thinking(content: str, max_lines: int = 3)`：
  - DIM 样式打印 `💭` 前缀 + 前 max_lines 行纯文本
  - 超出部分显示 `... (省略 {n} 行)`
- 新增 `show_response(content: str)`：
  - 打印 `● Assistant` 标题（BOLD CYAN）
  - 通过 `render_markdown()` 完整渲染
- 简化 `assistant_start()` 仅启动 spinner
- 简化 `assistant_end()` 仅停止 spinner
- `stream_token()` 保留但在新流程中不被调用

#### 2. `agent/loop.py` — 改变渲染时机

新流程：`_stream_step()` 静默缓冲 → 判断类型 → 调用对应 UI 方法

```python
acc = _stream_step_with_retry(...)  # spinner 动画，静默缓冲
ui.assistant_end("")                 # 停止 spinner

if acc.is_natural_stop:
    ui.show_response(acc.content or "")
    return ...

if acc.has_tool_calls:
    if acc.content:
        ui.show_thinking(acc.content)
        if thinking_log is not None:
            thinking_log.append(acc.content)
    _execute_tools(...)
```

修改 `_stream_step()`: 移除 `ui.stream_token()` 调用，仅静默累积。

新增 `run_loop()` 参数：`thinking_log: list[str] | None`

#### 3. `agent/__main__.py` — `/think` 命令 + thinking 收集

- REPL 中增加 `/think` 命令，打印上一轮完整中间思考
- 维护 `thinking_history: list[str]`，传入 `run_loop(thinking_log=thinking_history)`
- 每轮新输入时清空
- 轮次结束后，若有中间思考，显示提示 `(中间思考共 N 行, /think 查看)`

## 视觉效果

```
⠋ Assistant (2.3s)              ← spinner 思考中
💭 我需要先检查工作区状态...      ← DIM，3 行截断
  ⏺ bash(ls -la)
    ⎿ total 136
⠋ Assistant (1.0s)              ← spinner 继续思考
💭 工作区已确认，开始构建项目...
  ... (省略 4 行)
  ⏺ write_file(package.json)
    ⎿ Created

● Assistant                      ← BOLD CYAN，最终输出
项目已构建完成。✅               ← 完整 Markdown 渲染
## 功能
- **后端**：REST API
...

(中间思考共 12 行, /think 查看完整内容)
```

## 验证

1. `python3 -c "from agent.ui import UI; from agent.loop import run_loop"` 确认导入
2. 运行 `python3 -m agent "创建hello.py"` 观察中间/最终视觉区分
3. 输入 `/think` 验证展开功能
