# 编程智能体（Coding Agent）设计方案

> 本文是施工蓝图，也是答辩底稿。考核明确指出面试重点是"你是否理解你的 agent 为什么这样运转，是否能为你的设计决策给出辩护"，因此文中每个设计点都写成 **决策 / 被拒绝的替代方案 / 理由** 三段式。只写结论的文档在答辩时没有价值。

技术选型：**Python 3.13**，约 6900 行；自研 provider 抽象层对接 OpenAI 兼容网关，默认 DeepSeek V4 Pro（1M 上下文）；运行时依赖只有一个 HTTP client。

---

## 1. 题目约束 → 模块映射

题目列出 5 项"重要逻辑需自行编写"。这张表是本项目合规性的第一份证据——每一项都能指到具体文件。

| 题目要求的自研项 | 落地位置 | 自研内容概要 |
|---|---|---|
| 对话历史与上下文管理 | `agent/history.py`、`agent/context.py` | 消息构造、token 估算与校准、锚定式 compaction、安全切点、孤儿 tool_call 自愈 |
| 工具的定义与本地执行 | `agent/tools/` | `@tool` 由 Python 类型签名生成 JSON Schema、手写参数校验器、dispatch、23 个工具的本地实现 |
| 模型输出的解析 | `agent/stream.py` | SSE delta 累积、tool_call 按 `index` 跨 chunk 重组、`finish_reason` 判定 |
| 循环终止条件 | `agent/loop.py` | 5 类终止条件的显式判定；`seal_pending_tool_calls` 不变量 |
| 错误处理 | `agent/llm.py`、`agent/tools/__init__.py` | 可重试/致命错误分类、full jitter 退避、工具异常转模型可见反馈 |

被明确禁止且本项目**完全未使用**的：任何 agent 框架/SDK（LangChain、LlamaIndex、OpenAI Agents SDK、Claude Agent SDK、AutoGen、CrewAI）；API 服务端托管的代码执行与文件工具（Code Interpreter、Files API、Assistants/Responses 的服务端会话状态）。详见 §10。

---

## 2. 模块结构

```
agent/
  __main__.py     CLI 入口、参数解析、REPL 主循环
  config.py       只读 os.environ 的配置对象
  llm.py          Provider 抽象；重试与错误分类
  transport.py    urllib + 手写 SSE 解析的第二个 Provider 实现（纯 stdlib）
  stream.py       流式 delta 重组
  history.py      消息构造与会话状态
  context.py      token 估算校准 + compaction
  loop.py         agent loop 与终止条件
  workspace.py    路径收敛 + FileRegistry 文件新鲜度
  permission.py   危险操作分级与确认门（+ skill 自动审批集成）
  shell.py        ShellRunner：超时、进程组 kill、有界输出
  ui.py           ANSI 流式渲染
  prompts.py      system prompt 与 subagent prompt
  terminal.py     终端输入管理、斜杠命令两级自动补全、CJK 宽度适配
  commands.py     斜杠命令分发系统（help/think/resume/skill/goal/plan）
  goal.py         目标模式 GoalManager + 方案模式 PlanManager
  session.py      会话持久化、JSON 序列化/反序列化、按工作区索引
  memory.py       跨会话记忆管理（工作区记忆目录）
  banner.py       启动 banner 与环境状态显示
  markdown.py     Markdown 终端渲染
  hooks.py        生命周期钩子
  plugins.py      插件加载
  skills/
    __init__.py   Skill 引擎：注册/解析/执行/自动审批/远程安装
    *.md          11 个内置 skill（YAML frontmatter + Markdown prompt）
  tools/
    __init__.py   @tool registry、schema 生成、参数校验、dispatch
    fs.py         read_file / write_file / edit_file / delete_file / rename_file / list_dir
    diff.py       multi_edit / view_diff
    search.py     glob / grep
    bash.py       bash
    todo.py       todo_write
    task.py       task（子代理）
    web.py        web_fetch
    memory.py     memory_write / memory_read / memory_forget
    proc.py       spawn / proc_status / proc_kill（后台进程管理）
    control.py    extend_iterations（动态扩展迭代上限）+ use_skill（skill 激活）
tests/
.env.example
requirements.txt
```

**决策**：扁平的单层 `agent/` 包，模块按职责切分，嵌套子包只有 `tools/` 和 `skills/`。

**被拒绝的替代方案**：`core/` + `infra/` + `domain/` 的分层结构；或按框架概念命名（`chains/`、`memory/`、`agents/executor.py`）。

**理由**：两条。其一，分层目录只会增加跳转成本而不增加清晰度——真正的边界是模块间的函数签名，不是文件夹。其二也更重要：**目录结构本身是答辩材料**。出现 `chains/`、`memory/` 会让人第一眼怀疑这是 LangChain 的克隆；而 `loop.py`、`context.py`、`stream.py` 这样的命名读起来就是一个手写程序，模块名直接对应 §1 表格里题目要求的自研项。`skills/` 作为子包是因为它同时承载代码（`__init__.py`）和数据（`*.md` skill 模板）。

---

## 3. agent loop 与终止条件

### 3.1 单轮控制流

```
用户输入
  └→ history.append(user_message)
     ↓
  ┌─ 迭代开始 ────────────────────────────────┐
  │ context.prepare(history)      压缩 + 自愈  │
  │ llm.stream_chat(messages, tools)          │
  │ stream.accumulate(deltas)     → assistant │
  │ history.append(assistant)                 │
  │                                           │
  │ 有 tool_calls?                            │
  │   否 → 终止，交还用户                      │
  │   是 ↓                                    │
  │ 对每个 tool_call:                          │
  │   permission.check() → 必要时确认           │
  │   tools.dispatch()   → ToolResult          │
  │   history.append(tool_message)             │
  │ 迭代 += 1                                  │
  └───────────────────────────────────────────┘
```

### 3.2 核心不变量：tool_call 必须配对

**一旦向 history 写入带 `tool_calls` 的 assistant 消息，在下一次 API 请求之前，必须为其中每一个 `tool_call_id` 补齐一条 `role="tool"` 消息。** 缺失配对的 tool_call 在 DeepSeek、OpenAI 等 provider 上直接返回 400。

危险的不是正常路径——正常路径自然会配对。危险的是异常路径：用户在工具执行到一半时 Ctrl-C；某个工具抛出未预料的异常；权限门被拒绝后提前 break。这些路径都会留下孤儿 tool_call，而下一轮请求才会暴露它，届时错误信息与真实原因已经隔了很远。

**决策**：`seal_pending_tool_calls()` 放在 `finally` 块里，为所有尚未配对的 id 补一条说明性 tool 消息（如 `"Interrupted by user before execution."`）。

**被拒绝的替代方案**：在每个可能提前退出的地方手动补齐；或在请求前才检测并修补。

**理由**：手动补齐依赖"每次新增 break 都记得处理"，这种约束迟早失效。`finally` 是语言级保证，覆盖 return、break、异常、`KeyboardInterrupt` 全部路径。请求前检测作为**第二层**保留（见 §5 自愈），但不能作为唯一防线——因为那时已经无法知道该填什么内容了。

### 3.3 全部终止条件

| 条件 | 判定 | 处理 |
|---|---|---|
| 自然停止 | `finish_reason == "stop"` 且无 tool_calls | 结束本轮，交还用户 |
| 迭代上限 | `iteration >= 40`（子代理 15） | 停止，告知用户已达上限并保留 history 供续跑 |
| 上下文耗尽 | 压缩后估算仍超 usable | 停止并提示（正常情况下不可达，见 §5） |
| 用户中断 | `KeyboardInterrupt` | `seal` 后交还用户，会话可继续 |
| 致命错误 | 401/403/404、非 context 的 400 | 停止并打印诊断 |

### 3.4 "停止"与"模型忘了调工具"如何区分

**决策：不区分，不猜。** `finish_reason == "stop"` 且无 tool_calls 就当作本轮结束，控制权交还用户。

**被拒绝的替代方案**：检测到"回复看起来像还没干完"（比如以"接下来我将……"结尾）就自动追加一条 `"continue"` 用户消息把模型推回循环。

**理由**：这个判断无法可靠做出——自然语言里"我将修改 X"既可能是宣告下一步，也可能是总结刚做完的事。判断错了的代价是不对称的：漏判只是让用户多按一次回车；误判则制造一个**静默烧 token 的死循环**，且模型每次都会顺着"continue"编出新工作来做。**用户就是循环的外层控制**，这不是缺陷而是设计——把"是否继续"的决定权交给唯一真正知道任务是否完成的人。这也是 40 次迭代上限敢设得这么宽的前提：真正的刹车在人手里。

---

## 4. 工具系统

### 4.1 单一声明源

**决策**：`@tool` 装饰器读取函数的**类型注解 + docstring** 生成 JSON Schema，schema 与本地 dispatch 共用同一份声明。

```python
@tool
def read_file(path: str, offset: int = 0, limit: int = 2000) -> str:
    """读取工作区内的文本文件。

    path: 相对于工作区根目录的路径
    offset: 起始行号，从 0 开始
    limit: 最多读取的行数
    """
```

registry 从签名推出 `type`（`str`→string、`int`→integer、`bool`→boolean、`list[str]`→array…）、从"有无默认值"推出 `required`、从 docstring 逐行推出参数描述。

**被拒绝的替代方案**：手写 JSON Schema 字典，与实现函数分开维护。

**理由**：手抄的两份声明一定会漂移。漂移的表现形式极其阴险：模型按旧 schema 传了个已被删掉的参数，或漏传了新增的必填参数——而错误直到运行时才出现，且看起来像"模型不听话"，而不是"我的 schema 过期了"。单一声明源在结构上消灭了这类 bug。

### 4.2 参数校验

**决策**：手写约 50 行校验器，覆盖 6 种 JSON 类型 + `required` + `enum`，在 dispatch 层执行。`jsonschema` 库只在 `tests/` 里做对照验证，不进 runtime。

**被拒绝的替代方案**：runtime 直接用 `jsonschema` 或 `pydantic`。

**理由**：`pydantic` 不算 agent 框架，但"工具的定义与本地执行"正是题目点名要求自研的一项，把它外包给库会削弱这一项的完成度；而手写这段的成本只有 50 行。`jsonschema` 留在测试里是为了证明手写实现的正确性——这比"我相信我写对了"有说服力。

### 4.3 工具失败也必须返回内容

**决策**：dispatch 层捕获**全部**异常，转成 `ToolResult(ok=False, content="Error: ...")`。工具永远不向上抛异常。

**理由**：两条独立的理由，任一条都足够。

其一是**结构性的**：每个 tool_call 必须有配对结果（§3.2），异常逃出去就意味着孤儿。

其二是**能力上的**：模型能从错误文本里自我纠正，进程崩了不能。这一点决定了错误信息的写法——要写给模型看，而不是写给日志看。`edit_file` 没找到匹配时，不能只说 `"no match"`，而要说 `"字符串在 src/main.py 中出现 0 次。请先 read_file 确认实际内容，注意缩进与空行。"`；模型传了畸形 JSON 参数时，要把校验错误**连同期望的 schema** 一起回灌。**这正是校验必须放在 dispatch 层的原因——只有那里的输出才会成为模型可见的 tool 消息。**

### 4.4 工具集与契约

| 工具 | 契约与边界 |
|---|---|
| `read_file` | 路径收敛；默认 2000 行 / 40K 字符封顶；带行号返回（便于模型引用）；写入 FileRegistry |
| `write_file` | 仅用于新建文件；已存在则要求改用 `edit_file`，防止整文件覆盖丢内容 |
| `edit_file` | 精确唯一字符串替换；强制 read-before-edit；mtime 校验（见 §5.4） |
| `multi_edit` | 多位置批量编辑，一次调用修改文件中多处 |
| `view_diff` | 查看文件 diff |
| `delete_file` | 删除文件（路径收敛 + 权限检查） |
| `rename_file` | 重命名/移动文件（路径收敛 + 权限检查） |
| `list_dir` | 列出目录内容（路径收敛） |
| `glob` | 按模式列路径，200 条封顶，按 mtime 排序（新改的文件更可能相关） |
| `grep` | 正则搜内容，100 匹配封顶、单行 400 字符截断 |
| `bash` | 见 §6.3 |
| `spawn` | 后台启动长运行进程（dev server、watcher 等），返回 proc_id |
| `proc_status` | 查看后台进程输出与状态 |
| `proc_kill` | 终止后台进程 |
| `todo_write` | 多步任务的显式计划，写进 history 作为模型的外部记忆锚点 |
| `task` | 派生只读子代理，见 §7 |
| `web_fetch` | 获取网页内容（URL 抓取 + HTML 转文本） |
| `memory_write` | 写入跨会话记忆到工作区记忆目录 |
| `memory_read` | 读取跨会话记忆 |
| `memory_forget` | 删除跨会话记忆条目 |
| `extend_iterations` | 动态扩展当前轮次的迭代上限 |
| `use_skill` | 显式激活 skill 工作流（见 §12.7） |

### 4.5 `edit_file`：为什么是精确字符串替换

**决策**：`edit_file(path, old_string, new_string)`，要求 `old_string` 在文件中**恰好出现一次**。0 次或多次都一个字不改，并回报实际出现次数。

**被拒绝的替代方案 A —— 行号定位**（`edit(path, start_line, end_line, content)`）：行号会漂移。同一轮里模型先在文件前部插入 3 行，之后所有基于早先 `read_file` 输出算出的行号全部偏移 3。模型不会重新读文件，它会用记忆里的行号。

**被拒绝的替代方案 B —— unified diff / patch**：模型算不对 hunk header `@@ -a,b +c,d @@` 的四个数字（尤其是行数）。而 patch 工具为了容错通常做模糊匹配，于是错误的 hunk 不会报错，而是被"尽力"应用到某个相似的位置。

**理由**：关键不在于哪种方式更省 token，而在于**失败模式的性质**。行号漂移和 diff 误算的失败都是**静默改错位置**——文件被破坏了，而模型以为成功了，然后继续在错误的基础上工作。精确唯一字符串的失败是**安全的**：要么唯一命中并正确应用，要么什么都不改并明确告诉模型"出现了 0 次 / 3 次"。前者模型无从察觉，后者模型立刻能补充上下文重试。**在一个模型会犯错的系统里，可检测的失败远胜于不可检测的成功。**

代价是 token 更贵（要重复原文片段），这个交换我认。

---

## 5. 上下文管理

### 5.1 为什么必须压缩（答辩要点）

**压缩的真正驱动力不是"1M 的窗口装不下"，而是 history 每一步都被完整重发，使单轮任务的 token 成本呈 O(n²)。** 第 k 步要重发前 k-1 步的全部内容，n 步累计约 n²/2。一个跑了 30 步、每步读了个文件的会话，光重发就能烧掉几十万 token。

次要但真实的两条：中段上下文的召回质量随长度衰减（模型对长 history 中间部分的注意力下降）；以及延迟随 prompt 长度线性上升，直接影响交互体验。

这条理由的实践含义是：**即使换成上下文窗口极大的模型，压缩也不能省。** 这是我拒绝"反正窗口够大就不做压缩"的原因。

### 5.2 token 估算与校准

**决策**：手写估算器 + 服务端反馈校准。估算规则：CJK 字符按 1.0 token/字，其余按 `len/3.6`，每条消息 +4 的结构开销，最后乘 `SAFETY_FACTOR = 1.15`。首次真实调用后，用响应里的 `usage.prompt_tokens` 与本地估算值之比做 EMA 校准。

**被拒绝的替代方案**：引入 `tiktoken`。

**理由**：`tiktoken` 的词表是 OpenAI 的，对 DeepSeek / Kimi / Qwen / GLM **都不是正确的分词器**——用它会得到一个精确的错误答案，比一个诚实的粗估更危险。它还要在首次使用时联网下载词表文件，这在离线或网络受限环境下会直接让 agent 起不来。

而"精确"本来就不是这里需要的性质。我需要的是**一个方向可控的估算 + 一个权威的兜底**：

- 估算器**刻意偏高估**（`SAFETY_FACTOR` 1.15）。因为误差的代价不对称：低估会撑爆窗口导致请求失败，高估只是压缩早触发、白丢一点上下文。
- 一次真实调用之后，EMA 校准就把它拉到了该 provider 的真实分词行为上。
- 而 400 `context_length_exceeded` 是**权威兜底而非失败**：捕获它 → 强制压缩 → 重试一次。服务端才是唯一知道真实 token 数的一方，把它的拒绝当作信号而不是错误。

一句话：**我不需要 tokenizer，我需要一个偏高估的估算器加上服务端自己给的 usage。**

### 5.3 锚定式 compaction

触发阈值 `soft_context_cap = min(0.75 × usable, 120_000)`。

**永不驱逐的锚点**：

1. system prompt——定义了 agent 的行为契约，丢了就换了个 agent。
2. **最初的那条用户任务消息**——这是最容易被忽略也最致命的一条。它通常是 history 里最短的消息（几十 token），却是整个会话的目标定义。丢了它，模型会开始"完成"摘要里提到的某个中间步骤，而不是用户真正要的东西。
3. 最后 6 轮或 25% usable 的近期消息——正在进行的工作现场。

中段消息另起**一次独立的 LLM 调用**摘要成单条 `<summary>` 消息插回原位。摘要 prompt 明确要求保留：已修改的文件及改动性质、已确认的事实（如"测试入口是 `pytest tests/`"）、已排除的方案及原因、未完成的待办。

**被拒绝的替代方案**：滑动窗口直接丢弃最老的 N 条。

**理由**：滑动窗口会丢掉"已经排除过方案 A"这类信息，导致模型兜回去重试已知失败的路径——这是长会话里最常见也最耗时的退化。用一次摘要调用的成本换取这些结论的留存是划算的。

### 5.4 安全切点与孤儿自愈

**这是全项目最高风险的不变量。** 压缩的切点绝不能落在"带 `tool_calls` 的 assistant 消息"与"它的 tool 结果"之间——那会造出孤儿 tool_call 或孤儿 tool 消息，两者都是 400。

三种具体的破法都要处理：

1. 切点正好落在配对中间；
2. 父 assistant 被驱逐，但它的 tool 结果留下了；
3. 切点紧跟在一条 tool 消息之后（保留段以 `role="tool"` 开头，同样非法）。

**决策**：`find_safe_cut_point()` 只在"完整的 round 边界"上切（一个 round = 一条 assistant + 其全部 tool 结果）；**并且**在每次请求前跑一次独立的自愈扫描，检测孤儿并修补（补占位 tool 结果，或整条丢弃 assistant 消息）。

**理由**：不用一层防线是因为这个不变量的违反后果严重、触发条件隐蔽（要长会话才会碰到），而两层防线互相独立——切点逻辑保证正确构造，自愈扫描兜住所有我没想到的构造路径（包括 §3.2 的中断路径）。

**必须强制测试**：默认 provider 的上下文窗口很大，意味着**这条代码路径在日常开发里自然跑不到**。因此必须有一条 `--context-limit 32000` 的强制早触发用例进 CI，否则第一次真实压缩就发生在录制演示视频的时候。

### 5.5 文件新鲜度

**决策**：`FileRegistry` 在 `read_file` 时记录 `(path, mtime, size, hash)`。`edit_file` / `write_file` 要求该文件有 read 记录，否则返回错误要求先读；若当前 mtime 与记录不符（外部修改），拒绝写入并要求重读。写入成功后更新记录。

**理由**：挡住一类经典 bug——模型读了文件、做了编辑、又基于**更早的那次读取内容**做第二次编辑，把第一次的改动覆盖掉。模型不会主动重读，因为它认为自己知道文件内容。mtime 校验则处理另一种情况：用户在 agent 运行期间用编辑器改了同一个文件。让这两种情况**在写入前失败并给出可执行指令**，比事后发现文件被改坏要好得多。

---

## 6. 安全与权限

### 6.1 路径收敛

**决策**：`resolved = (workspace_root / path).resolve()`，然后校验 `resolved == root or root in resolved.parents`。

**理由**：`resolve()` 一次性关掉两条越权路径——它既折叠 `..`（挡住 `../../etc/passwd`），又跟随 symlink（挡住"工作区内的软链指向工作区外"这条更隐蔽的路径）。**关键是必须在 `resolve()` 之后再比较**：先做字符串检查再 resolve 是无效的，因为字符串检查看不出 symlink 指向哪里。绝对路径同样走这套校验，不做特例。

### 6.2 敏感文件名单

`.env`、`.env.*`、`*.pem`、`id_rsa*`、`.git/config`、`*credentials*` 等在 `workspace.py` 层面直接拒绝读取。

**理由**：题目硬规则要求 key 不出现在仓库和视频里。演示视频里 agent 一句 `cat .env` 就能让屏幕上出现真实密钥——这是**不可挽回**的（视频已提交，key 只能作废重换）。让 agent 在结构上读不到这些文件，是唯一可靠的做法，比"提示词里叮嘱它不要读"强得多。

### 6.3 `bash` 加固

```python
subprocess.Popen(cmd, shell=True,
                 stdin=subprocess.DEVNULL,      # 关键
                 stdout=subprocess.PIPE,
                 stderr=subprocess.STDOUT,
                 start_new_session=True)        # 关键
```

**先说 `shell=True`。** 任何静态检查都会把它标成注入风险，这个标注是对的——但在 `bash` 工具这里，**shell 就是被需要的功能本身**：模型要写的是 `pytest tests/ -q | tail -20`、`grep -rn "foo" src/*.py`、`cmd > out.txt` 这类东西，管道、glob、重定向都由 shell 提供。这里不存在"改成 argv 列表"的选项，因为没有一个固定的可执行文件——命令全文就是模型的输出。

换个说法：`shell=True` 不是疏忽，它标出了本项目最大的信任边界所在——**我们本来就在有意地把模型生成的字符串交给 shell 执行**，这是 coding agent 的题设，不是实现瑕疵。既然这条边界无法用参数化消除，补偿性控制就必须落在别处：§6.4 的危险分类、§6.2 的敏感文件名单、以及 §6.5 的 git-clean scratch workspace。

余下四个要点，每个对应一种真实的挂死或失控：

- **`stdin=DEVNULL`**：最容易被忽略也最容易毁掉演示的一条。`npm init`、`git commit`（无 `-m`）、`apt install` 这类命令在没有 tty 时会等待输入，而 agent 永远不会给它输入——进程挂到超时为止。DEVNULL 让它们立刻拿到 EOF 而失败，失败信息可以回灌给模型让它改用非交互形式。
- **`start_new_session=True`**：使子进程成为新进程组的组长，超时后可以 `os.killpg` **杀掉整棵进程树**。只 kill 直接子进程的话，`make -j8` 派生的编译进程会全部留下来变成孤儿。
- **`stderr=STDOUT` + 有界 drain 线程**：合流是因为模型需要看到交错的完整输出（编译错误通常在 stderr，进度在 stdout）。用独立线程持续读取是因为——如果不读，管道缓冲区（约 64KB）一满，子进程就会**阻塞在 write 上永远不退出**，而这看起来完全像是"命令跑得慢"。
- **输出封顶 64KB**：超出时保留 head + tail 并插入省略标记。保留两头是因为诊断信息通常在开头（第一个错误）和结尾（汇总/退出码），中间的重复进度输出才是可丢的。默认超时 120s，上限 600s。

### 6.4 三级危险分类

| 级别 | 例子 | 处理 |
|---|---|---|
| 自动放行 | `ls`、`cat`、`grep`、`git status`、`git diff`、`pytest` | 直接执行 |
| 需确认 | 文件写入、`git commit`、`pip install`、任何联网命令 | 打印命令全文 + 影响范围，等用户确认 |
| 直接阻断 | `rm -rf /`、fork bomb、`dd of=/dev/*`、`curl ... \| sh`、`git push --force` | 拒绝并说明原因 |

### 6.5 诚实表述：这不是安全边界

**对 shell 字符串做静态分类不是安全边界，是防误操作的护栏。** 它可以被 `eval`、变量拼接、base64 解码、脚本文件等任意多种方式绕过；一个真心要绕过它的模型或攻击者不会有困难。

**真正的边界在 OS 层**（容器、`seccomp`、独立用户 + 文件系统权限）。本项目没有实现 OS 级沙箱，这是明确的取舍：5.5 天里它的实现与调试成本远超收益，且会让跨平台演示变复杂。作为交换：

- `ShellRunner` 留出 `Sandbox` 接缝（一个 `run(cmd) -> Result` 协议），后续可以在不改调用方的前提下接入容器执行。
- **实操上最有效的控制是：agent 始终跑在一个 git-clean 的 scratch workspace 上，任何破坏都只差一次 `git checkout`。**

我认为主动讲清这个边界比宣称"我的分类器是安全的"更站得住——因为后者一问就破。

---

## 7. 子代理（`task` 工具）

### 7.1 存在的理由

**子代理是上下文隔离与成本摊销装置，不是并行技巧，也不是"专家团队"隐喻。**

具体机制：一次"这个项目的错误处理是怎么组织的"式探索，可能要 grep 十几次、读七八个文件，产生 60K token 的工具输出。如果这些输出落进主 history，那么此后**会话余下的每一步**都要重新发送这 60K——按 §5.1 的 O(n²) 结构，这是持续付出的边际成本。

交给子代理后，父会话只见到最终那约 200 token 的结论。**省下的不是这一步的钱，是余下每一步的钱。**

**被拒绝的替代方案**：给 agent 配"架构师/程序员/测试员"多角色协作。

**理由**：角色扮演式多智能体在这里没有可辩护的机制——同一个模型换个 system prompt 并不真的获得新能力，只是增加了 round trip 和串话风险。而上下文隔离是一个**可以量化**的收益（60K → 200 token），这才是子代理值得存在的理由。

### 7.2 边界

- **工具子集只读**：`read_file`、`glob`、`grep`、只读 `bash`。子代理不能写文件。理由是父级无法审查子级的中间决策，让不可审查的执行体产生副作用是不可接受的；而探索任务本身不需要写权限。
- **结果回传**：子代理的最终文本消息作为父级的 tool 结果返回。子代理的 history 用完即弃。
- **递归封顶 `depth <= 1`**：子代理不能再派生子代理。理由是"派生一个子代理"对模型来说是个很容易上瘾的动作，不设硬上限就可能指数展开；而两层已经覆盖了所有实际有用的场景。
- 并发 3、单轮最多 5 个、单个 15 步、**共享父级 token 预算**（否则子代理会成为预算的逃逸口）。

---

## 8. 流式终端 UI

### 8.1 tool_call delta 的重组

这是"模型输出的解析"里最容易写错的部分。流式响应中 tool_call **跨 chunk 碎片化**，且有几个不直观的细节：

- `arguments` **必然**被切成多片，要按顺序字符串拼接；
- `function.name` **也可能**被切片（不能假设它在第一个 chunk 里就完整）；
- 靠 `index` 字段区分这是第几个 tool_call（并行调用时多个 index 交错到达）；
- `index` 可能缺失，需默认为 0；
- 最后一个 chunk 可能是只带 `usage` 的**空 `choices`** chunk，直接下标访问会 IndexError。

**决策**：`dict[int, PartialToolCall]` 累积，对每个字段做防御性拼接，全部字段缺失都有默认值。`arguments` 只在流结束后才整体 `json.loads`——中途的片段本来就不是合法 JSON。

### 8.2 渲染

正文 token 实时流出；每个工具调用渲染一行状态与一行结果摘要：

```
⏺ read_file(src/main.py)
  ⎿ 42 行
⏺ bash(pytest tests/ -q)
  ⎿ 14 passed in 1.2s
```

**决策**：裸 ANSI 转义序列，约 120 行，不用 `rich` / `prompt_toolkit`。

**被拒绝的替代方案**：`rich.live.Live`。

**理由**：渲染模型不匹配。我需要的是 **append-only 的行式流**（token 逐个追加、历史输出永久保留、可自由滚动）；`rich` 的 `Live` 是**区域重绘**模型，它要控制一块屏幕区域并反复刷新，与逐字追加的原始文本流互相干扰（表现为闪烁、错行、滚动历史被吃掉）。用它就要不断跟它的刷新时机搏斗。其次，`rich` 是纯装饰性依赖，而本项目的依赖清单本身是合规性论证的一部分（§10），为了几个圆角边框把它变复杂不值得。

同时提供 `--no-stream` 回退，走**完全相同**的代码路径（同一个 accumulator，只是不渲染增量）——这样回退路径不会成为未测试的第二套逻辑。

### 8.3 交互式确认（interactive_confirm）

**决策**：将权限确认和方案确认统一为 `interactive_confirm()` 组件：方向键上下选择 + 回车确认，选定后整个下拉框折叠为一行结果，不留屏幕噪音。

方案模式（§18）完成规划后弹出三选一：「✅ 执行方案 / ✏️ 提修改意见 / ❌ 取消方案」。权限门同样复用此组件。

**技术细节**：进入 `tty.setcbreak()` 半原始模式，`os.read(fd, ...)` 逐字节读取方向键序列，渲染用相对 ANSI 移动（`\033[{n}A`）。与权限确认和终端输入共用同一套按键识别逻辑（`_read_key()`），避免重复实现。

**被拒绝的替代方案**：文本输入（`y/n`、`输入 1/2/3`）。

**理由**：文本输入需要用户理解提示、键入、回车——三步；方向键只需一步操作。更重要的是，交互风格必须统一：权限门用选择框、方案确认也用选择框，否则用户的操作心智模型会在不同场景间切换。

---

## 9. 错误处理与重试

### 9.1 分类

| 类别 | 状态码 / 异常 | 处理 |
|---|---|---|
| 可重试 | 429、408、500/502/503/504、连接超时、读超时 | 退避重试，最多 5 次 |
| 上下文超限 | 400 且含 `context_length_exceeded` | **强制压缩后重试一次**（§5.2） |
| 致命 | 401/403（认证）、404（模型名错）、其他 400（请求畸形） | 立即停止并打印可操作的诊断 |

退避：base 1s、cap 30s、**full jitter**（`random.uniform(0, min(cap, base * 2**n))`）。

**决策**：显式设置 SDK 的 `max_retries=0`。

**理由**：不是为了"看起来像自己写的"，而是**双层重试会乘算**——SDK 默认重试 2 次、我重试 5 次，最坏情况变成 10 次请求和不可预测的总等待时间，且 SDK 那层对我的日志和退避策略完全不可见。重试是需要统一治理的策略（它决定了成本上限和最长阻塞时间），必须只存在于一处。full jitter 而非固定退避，是因为限流通常是多个请求同时被拒，同步重试会再次撞在一起。

### 9.2 Provider 兼容性：assistant 消息的 content 字段

**问题**：DeepSeek V4 Pro 严格要求每条 assistant 消息都包含 `content` 字段，即使该消息只有 `tool_calls` 而无正文。OpenAI API 在此处宽松——`content` 缺失或为 `null` 均可——但 DeepSeek 直接返回 400：`"Invalid assistant message: content or tool_calls must be set"`。

**决策**：`stream.py` 的 `to_message()` 和 `history.py` 的 `make_assistant()` **始终设置 `content: self.content or ""`**，保证即使内容为空也发送空字符串而非省略该字段。

**被拒绝的替代方案**：在 `llm.py` 发送前遍历 history 补齐缺失字段。

**理由**：在构造点就保证格式正确，比在发送点做后期修补可靠——后者依赖"每个构造路径都经过同一个修补点"，一旦某处直接构造 dict 就会漏过。这是典型的"正确性应在源头保证"原则。此修复同时兼容 OpenAI（空字符串对它也合法）和 DeepSeek，不需要 provider 特判。

### 9.3 模型侧错误的恢复

模型给出畸形 tool 参数（JSON 语法错误、缺必填字段、类型不符）**不崩、不重试整轮**，而是回一条 tool 消息，内容包含具体校验错误 + 期望的 schema，让模型自我纠正。这与 §4.3 是同一个原则的两个面：**工具层的错误是模型的输入，不是程序的异常。**

---

## 10. 禁令边界与自证

题目的禁令很具体，容易被误判的地方值得逐条摆明。

| 项 | 判定 | 处理与自证 |
|---|---|---|
| `openai` python 包 | **允许**（题目明示"模型厂商的 API 客户端库、OpenAI 兼容网关"） | **只用 `client.chat.completions.create()`** 这一个纯传输入口。`requirements.txt` 只有一行，这行本身就是论证 |
| Assistants / Responses API、Code Interpreter、Files API | **禁止** | 全程不用。特别指出 `client.responses.create(store=True)` 会把会话状态托管到厂商服务端，属**双重违规**——既是服务端托管状态，又等于没有自研对话历史 |
| `jsonschema` | 非框架，但仍不进 runtime | 只在 `tests/` 做对照。手写校验器正是被考核的"self-implemented"证据（§4.2） |
| `rich` / `prompt_toolkit` | 允许（纯 UI） | 已按技术理由拒绝（§8.2），顺带让依赖叙事保持干净 |
| `tiktoken` | 允许但错 | 已拒绝（§5.2）：错词表 + 首次需联网 |
| "ReAct"、"tool calling" 等术语 | 是**模式**不是框架 | 可用。但模块不按框架概念命名（§2） |
| MCP client | 会显得"接了生态" | **不做**。可辩护为"自研协议实现"，但纯排期风险、零评分收益 |

### 决定性的自证手段

`llm.py` 面向一个窄内部接口：

```python
class Provider(Protocol):
    def stream_chat(self, messages, tools) -> Iterator[Delta]: ...
```

并提供**第二个实现** `transport.py`：`urllib.request` + 手写 SSE 行解析，约 90 行纯标准库，通过 `AGENT_TRANSPORT=raw` 切换。

**一个环境变量就证明了 SDK 只是一个可替换的 HTTP client，不是 agent 本身。** 这个论证的成本很低（90 行），但它把"你是不是靠 SDK 做的"这个质疑一次性关掉——因为可以当场把 SDK 摘掉再跑一遍。

**一句话总结**：agent 的大脑在 `loop.py`、`context.py`、`tools/__init__.py`、`stream.py`、`history.py` 这五个文件里，而它们除了标准库什么都没 import。

### 密钥纪律（题目硬规则）

- `.gitignore` **从引入它的第一个 commit 起**就包含 `.env`——事后补加意味着中间某个 commit 可能已经带上了凭据。
- `.env.example` 只有 key 名，无值。
- `config.py` 只读 `os.environ`，**从不把 key 写入磁盘或日志**。
- 脱敏过滤器覆盖 UI 与 session log **两条**输出路径。
- `workspace.py` 的敏感文件名单让 agent 结构上读不到 `.env`（§6.2）。

---

## 11. 终端交互系统

### 11.1 斜杠命令

**决策**：输入 `/` 触发命令自动补全下拉框，4 个核心命令：`/help`、`/think`、`/resume`、`/skill`。命令系统通过 `register()` 注册，`dispatch()` 分发。

**被拒绝的替代方案**：直接在 REPL 主循环里用 if-elif 匹配。

**理由**：register + dispatch 模式让新增命令只需一行注册调用，不碰分发逻辑。更重要的是，注册信息（名称、描述、别名）复用为自动补全的数据源——下拉框的选项列表与命令实现是同一份声明，不会漂移。

### 11.2 两级自动补全

输入 `/` 弹出命令下拉框；选择 `/skill` 后自动填入 `/skill ` 并切换为 skill 名称下拉框。

**技术难点——终端原始输入**：

常规 `input()` 拿不到单个按键事件。实现使用 `termios` + `tty.setcbreak()` 进入半原始模式，用 `os.read(fd, ...)` 逐字节读取。

**关键修复——方向键识别**：方向键是多字节转义序列（如 `\033[A`），最初使用 `sys.stdin.read(1)` + `select()` 检测后续字节。但 Python 的 `sys.stdin.read()` 有内部缓冲区，它一次性从 OS 读走了完整的 `\033[A`（3 字节），第一个字节返回给调用者，剩下 2 字节留在 Python 缓冲区里。此时 `select()` 检查的是 OS 层 fd——已经空了——于是判定为裸 ESC。

**解决方案**：`_slash_input` 内全部 I/O 改用 `os.read(fd, ...)` 绕过 Python 缓冲层，用 `fcntl` + `O_NONBLOCK` 做非阻塞 peek 检测后续字节。`_read_key()` 函数封装了完整的按键识别：普通字符、方向键（`\033[A/B/C/D`）、裸 ESC。

### 11.3 CJK 宽度适配

中日韩字符在终端占 2 列宽度。下拉框的边框对齐依赖准确的可视宽度计算。

**决策**：`_visual_width(s)` 用 `unicodedata.east_asian_width()` 判定每个字符宽度（W/F = 2，其余 = 1）。所有下拉框渲染用 `_visual_width()` 计算填充量，`_truncate_to_width()` 做精确截断。

### 11.4 输入缓冲区净化

**问题**：斜杠命令选中执行后，下一次输入的第一个字符被吞掉，且 `/` 无法再次触发命令下拉框。

**根因**：`interactive_confirm()` 等组件使用 `tty.setcbreak()` + `os.read()` 读取按键，退出时恢复终端模式。但回车键的 release 和终端恢复之间存在竞态——残留字节（如回车的尾部、终端模式切换产生的噪声）留在 OS 缓冲区里。下一次 `_input_with_slash_detect()` 进入 cbreak 模式后的第一个 `os.read()` 读到的是这些残留，而非用户真正敲的字符。

**修复（两层）**：

1. **缓冲区排水**：进入 cbreak 后，用 `fcntl.F_SETFL | O_NONBLOCK` 将 fd 临时设为非阻塞，循环 `os.read(fd, 64)` 直到 `BlockingIOError`（缓冲区已空），再恢复阻塞模式。
2. **控制字符过滤**：首字节读取循环中，ASCII `< 0x20` 的字节（CR/LF/NUL 等控制字符）直接跳过并重读，只有可打印字符才被接受为有效输入。

**理由**：两层修复各自独立——排水覆盖"残留垃圾"，控制字符过滤覆盖"合法但无意义的字节"。任一层单独失效不影响另一层。

### 11.5 下拉框渲染

**决策**：每次 `_render()` 用 `\033[J`（清除光标以下）清空旧内容，重新绘制边框和选项，再用 `\033[{n}A` 回到输入行。

**被拒绝的替代方案**：`\033[s`/`\033[u`（光标保存/恢复）。

**理由**：当终端发生滚动时，保存的绝对光标位置失效——恢复后光标跑到错误的行。相对移动 `\033[{n}A` 只依赖"刚才画了几行"，不受滚动影响。

---

## 12. Skill 系统

### 12.1 设计目标

Skill 是预定义的工作流模板：一段精心编写的 prompt + 元数据（名称、描述、别名、是否自动审批）。执行 skill 时，prompt 注入用户参数后直接送入 agent loop，自动审批模式下工具调用无需用户逐次确认。

**这不是插件系统。** Skill 不引入新的工具、不改变 agent 的能力边界——它只是提供了一个高质量的起始 prompt，让 agent 用已有工具按特定工作流执行。这个定位是有意的：增加能力的方式应该是增加工具（§4），而不是增加 prompt 的魔法。

### 12.2 三层 Skill 来源

| 层级 | 路径 | 加载时机 |
|---|---|---|
| 内置 | `agent/skills/*.md` | 模块初始化时自动加载 |
| 用户自定义 | `~/.megumin/skills/*.md` 或 `*.yaml` | 模块初始化时自动加载 |
| 远程安装 | `/skill install <url>` | 用户手动触发，保存到用户目录 |

用户自定义 skill 同名时不会覆盖内置 skill（先注册先得）。

### 12.3 Skill 文件格式

```markdown
---
name: review
description: 审查代码变更，给出改进建议
aliases: [cr]
auto_approve: true
---

你是一个资深代码审查者。请审查以下代码变更：

{args}

## 审查维度
...
```

YAML frontmatter + Markdown body。`{args}` 和 `{workspace}` 是运行时替换的占位符。

**决策**：自研简单 YAML 解析器（约 30 行），不依赖 `pyyaml`。

**理由**：skill frontmatter 只用到 4 种值类型（字符串、布尔、列表、无值），且格式完全受控（内置 skill 由开发者编写，用户 skill 有模板引导）。为这个子集引入 `pyyaml` 会在依赖清单上增加一行——而依赖清单本身是合规论证的一部分（§10）。

### 12.4 自动审批

**决策**：使用 `threading.local()` 存储当前线程的 auto_approve 标志。skill 执行前设置，`finally` 块中清除。`permission.py` 的 `check_permission()` 检测到该标志时跳过用户确认（危险命令如 `rm -rf /` 仍然被阻断）。

**理由**：thread-local 保证 skill 的自动审批不会泄漏到其他线程或后续的非 skill 对话轮次。`finally` 保证异常和中断路径也能清除——这与 §3.2 的 `seal_pending_tool_calls` 是同一个模式：用语言级保证覆盖所有退出路径。

### 12.5 远程安装

`/skill install <url>` 支持从 GitHub 文件链接、GitHub Gist、任意直链 URL 下载 skill 文件。

- GitHub blob URL（`github.com/.../blob/...`）自动转换为 `raw.githubusercontent.com` 直链
- Gist URL 自动转换为 raw 下载地址
- `.cursorrules` 格式自动转换为 megumin skill `.md` 格式（追加 frontmatter + `{args}` 占位符）

下载后解析验证，保存到 `~/.megumin/skills/` 并立即注册可用，无需重启。

**决策**：使用标准库 `urllib.request` 下载，不引入 `requests`。

**理由**：与 `transport.py`（§10 的 raw 回退）一致——标准库够用的场景不加依赖。

### 12.6 四格式自动检测与转换

远程安装时，`_detect_skill_format()` 从文件内容和 URL 推断格式：

| 格式 | 特征 | 转换动作 |
|---|---|---|
| **native** | YAML frontmatter 包含 `name` + `description`，有 `{args}` 占位符 | 直接使用 |
| **claude-code** | frontmatter 含 `description` 但无 `name`，或含 `globs` / `alwaysAllow` 等 Claude Code 字段 | 提取 slug 做 name，追加 `{args}` |
| **aas** | frontmatter 含 `risk` / `source_repo` / `source_type` 等 awesome-ai-agents 字段 | 映射字段、追加 `{args}` |
| **cursorrules** | URL 含 `.cursorrules` / `.mdc`，或纯文本无 frontmatter | 自动生成 frontmatter + 追加 `{args}` |

**决策**：检测基于元数据字段启发式匹配，转换后统一为 native 格式。外部 skill 缺少 `{args}` 占位符时自动追加 `"\n用户需求: {args}\n"`。

**理由**：skill 生态碎片化——不同社区用不同格式发布 prompt。让安装命令一键兼容四种格式，比要求用户手动转换更实际。启发式检测偶尔误判的代价很低（最坏情况是 frontmatter 字段不全，用户手动改一下），而正确检测的收益很大（零摩擦安装）。

### 12.7 `use_skill` 工具：skill 激活的显式化

**问题**：skill 的自动触发对用户不可见——模型在 system prompt 中看到 skill 目录和触发条件后，直接按 skill 模板执行工作流，但 UI 上没有任何痕迹表明"此刻正在使用 frontend skill"。用户无法确认模型是否真的激活了 skill，也无法在演示视频中展示 skill 系统的运作。

**决策**：新增 `use_skill(name)` 工具（`agent/tools/control.py`）。system prompt 指示模型：**当请求匹配 skill 触发条件时，第一步先调用 `use_skill` 工具激活 skill**，然后按返回的工作流执行。

```python
@tool
def use_skill(name: str) -> ToolResult:
    skill = get_skill(name)
    if skill.auto_approve:
        set_auto_approve(True)
    workflow = skill.prompt_template.replace("{args}", "(见用户原始请求)")
    return ToolResult(True, f"⚡ Skill [{skill.name}] activated — ...")
```

UI 层为 `use_skill` 配了专属 spinner 标签 `"⚡ activating skill"`，执行时用户能看到明确的激活动画。

**被拒绝的替代方案**：在 loop 层拦截 system prompt 注入结果，自动打印激活信息。

**理由**：loop 层不知道模型**是否真的在用 skill**——它只知道 skill 目录被注入了 system prompt，但模型可能忽略了触发条件。让模型**通过 tool call 显式声明**"我正在激活 skill X"，把决策权留在模型侧（它判断是否匹配），同时把可见性交给 tool dispatch 的标准渲染管线。这复用了已有的工具展示机制，不需要新增 UI 路径。

每轮 loop 开始时 `set_auto_approve(False)` 重置（`loop.py`），防止上一轮 skill 的自动审批泄漏到非 skill 对话。

### 12.8 内置 Skill 清单

11 个内置 skill 覆盖常见开发工作流：

| Skill | 定位 |
|---|---|
| `review` | 代码审查 |
| `test` | 测试生成 |
| `explain` | 代码解释 |
| `commit` | 生成 commit message 并提交 |
| `fix` | 问题分析与修复 |
| `refactor` | 代码重构 |
| `doc` | 文档生成/更新 |
| `push` | 提交并推送 |
| `init` | 项目初始化 |
| `frontend` | 前端全流程（React/Vue/Next.js/样式/状态/测试/构建） |
| `backend` | 后端全流程（API/数据库/认证/安全/测试/部署） |

其中 `frontend` 和 `backend` 是生产级的全流程 skill：自动识别项目技术栈，覆盖从需求分析到质量验收的完整工作流。

---

## 13. 会话与记忆

### 13.1 会话持久化

**决策**：每轮对话结束后将 history 序列化为 JSON，按工作区路径索引存储在 `~/.megumin/sessions/`。`/resume` 命令列出当前工作区的历史会话，用户选择后反序列化恢复。

恢复时重建 system prompt（因为工作区文件可能已变化）并替换当前 history，对话可以无缝继续。

### 13.2 跨会话记忆

通过 `memory_write` / `memory_read` / `memory_forget` 三个工具，agent 可以在工作区的 `.megumin/memory/` 目录下读写持久化记忆。

**用途**：记住项目偏好（"这个项目用 4 空格缩进"）、技术决策（"选了 Redis 做缓存"）、待办事项等。下次在同一工作区启动时，system prompt 会注入已有记忆作为上下文。

**决策**：记忆是纯文本文件而非数据库。

**理由**：用户可以直接用编辑器查看、修改、删除记忆——透明性比查询效率重要。记忆条目的规模不会超过几十条（超过了说明该用文档而不是记忆），文件系统足够。

---

## 14. 目标模式与方案模式（`goal.py`）

### 14.1 目标模式（`/goal`）

**决策**：`GoalManager` 实现自主迭代——用户设定目标后，agent 连续执行直到完成，无需每步等待用户输入。

核心控制流：
1. 用户输入 `/goal <描述>` → `GoalManager.set_goal()`
2. 首轮注入 `build_initial_prompt()`（含目标 + 自主执行指令）
3. 每轮结束后 `should_auto_continue()` 判定：
   - `fatal_error` / `context_exhausted` → 停止
   - `max_iterations` → agent 仍在忙，继续
   - `natural_stop` → 检测 agent 回复是否表示完成（正则匹配中英文完成指示词）
4. 若需继续，注入 `build_continue_prompt()` 自动发起下一轮
5. 安全上限 `max_auto_turns = 20`

**完成检测**：`_looks_like_done()` 用 6 条正则（中英文各 3 条）检测 agent 是否声称完成，如"全部完成"、"任务完成"、"all done"。**阈值为 1**——任意一条命中即认为完成。

**理由**：误判"未完成为已完成"的代价只是用户多输入一句"继续"；而误判"已完成为未完成"会白白多跑一轮、产生多余输出。宁可早停。

### 14.2 方案模式（`/plan`）

**决策**：`PlanManager` 实现先规划后执行——agent 在规划阶段**只读**，产出实现方案后等用户审批再执行。

状态机：`idle → planning → awaiting_approval → executing → idle`

- **规划阶段**：prompt 明确禁止写操作（`write_file`/`edit_file`/`bash` 写命令），只允许 `read_file`/`glob`/`grep`/`list_dir` 等只读工具。
- **审批阶段**：弹出 `interactive_confirm()` 三选一（§8.3）：
  - **执行方案** → `PlanManager.approve()` → 注入执行 prompt
  - **提修改意见** → 用户输入反馈 → 重新进入规划
  - **取消方案** → `PlanManager.reject()` → 回到普通对话

**被拒绝的替代方案**：用 system prompt 角色切换（"现在你是审查者 / 现在你是执行者"）。

**理由**：角色切换是不可靠的软约束——模型可能在"审查者"阶段就开始写文件。方案模式的约束在两层执行：prompt 层告诉模型不要写，而状态机在 loop 层控制流程走向。方案确认的 UI 统一使用 `interactive_confirm()`（§8.3），与权限门保持操作体验一致。

---

## 15. 关键默认值

可直接落进 `config.py`：

```
max_iterations          40          (subagent 15)
max_output_tokens       8192
soft_context_cap        min(0.75 * usable, 120_000)
compaction tail         最后 6 个 round 或 25% usable
read_file 上限          2000 行 / 40K 字符
grep 上限               100 匹配 / 单行 400 字符
glob 上限               200 路径
bash                    默认 120s，上限 600s，输出 64KB (head+tail)
retry                   5 次，base 1s，cap 30s，full jitter，SDK max_retries=0
subagent                并发 3，单轮 5，depth 1，15 步，共享 token 预算
estimator               CJK 1.0/字，其余 len/3.6，每消息 +4，SAFETY_FACTOR 1.15
```

---

## 16. 施工顺序（5.5 天）

原则：**每一步都产出可提交、可演示的增量**。评委会读提交历史了解开发过程，因此历史应当反映真实的推进顺序，而不是最后一次性倒进去。

| 时间 | 内容 | 里程碑 |
|---|---|---|
| **D1** | `config` + `llm` + 最小 loop + `read_file`/`write_file`/`bash` + 纯 print 输出 | **agent 端到端完成一个真实任务**；当天录一版备份 demo |
| **D2** | 工具系统正规化（registry、签名生成 schema、校验器）+ `edit`/`glob`/`grep` + 路径收敛 + FileRegistry | 工具集完整 |
| **D3** | `context.py`（估算校准、锚定压缩、安全切点、自愈）+ retry/backoff + 错误分类 | 长会话可用 |
| **D4** | 权限门 + ShellRunner 加固 + 子代理 | 功能完整 |
| **D5 上午** | 流式 UI 打磨、`transport.py` raw 回退、`--no-stream`；跑 `--context-limit 32000` 强制压缩用例 | 全部路径被测过 |
| **D5 下午** | **硬性功能冻结**，写 README.txt、录制视频 | 交付物就绪 |
| **D6（9/2）** | 缓冲；24:00 前完成最后推送 | 提交 |

**D1 就要跑通 vertical slice**，这是整个排期里最重要的一条。理由：它把"能不能做出来"的风险在第一天就消掉，之后每一天都是在一个**已经能用**的东西上加深度。反过来做（先搭完整架构再接通）意味着到 D4 才知道能不能跑，那时已经没有回退空间。

D1 当天录备份 demo 同理——一个功能少但确实能跑的演示视频，胜过一个功能全但截止日出了岔子的空手。

**裁剪顺序**（进度落后时依次砍）：MCP（已砍）→ `transport.py` raw 实现 → 子代理 → 流式 UI 降级为整段输出 → 权限门降级为全部需确认。压缩与工具系统不可砍——它们是题目点名的自研项。

---

## 17. 高风险项与对策

**1. compaction 破坏 tool_call/tool_result 配对**
最可能真正炸掉演示的一项，三种破法见 §5.4。
对策：切点只在 round 边界 + 请求前自愈扫描 + `context_length_exceeded` 兜底。**并且：录制视频之前先跑一个长会话把这条路径压出来**，不要让第一次真实压缩发生在录制时。

**2. token 估算朝危险方向偏**
低估撑爆窗口，高估白丢上下文。
对策：刻意偏高估 + `usage` EMA 校准 + 把 400 当权威兜底。**注意默认 provider 窗口很大，这使压缩路径在日常开发中自然跑不到**，所以必须有 `--context-limit 32000` 的强制用例，否则这条代码永远没被执行过。

**3. `bash` 挂死或摧毁 workspace**
挂死是更可能的演示杀手（无 tty 的交互提示、管道缓冲写满），见 §6.3。
对策：`stdin=DEVNULL` + 进程组 kill + 有界 drain 线程 + 120s 默认超时。摧毁方面，最有效的实操控制是 **agent 始终跑在 git-clean 的 scratch workspace 上**——这比任何静态分类都可信。

**4. provider 流式怪癖 / 截止日 API 抖动**
`function.name` 被切片、`index` 缺失、usage chunk 的 `choices` 为空；或者 9 月 2 日当天厂商服务抖动。
对策：§8.1 的防御式 accumulator；`--no-stream` 回退；**同时配好两家 provider 的 key**，单厂商故障只是切一个 flag——这是 provider 抽象层**超出"可切换"这个题面要求**的真正价值；**视频提前录好并上传**，不留到截止日晚上。

**4.5（半个）scope creep 吃掉交付物**
5.5 天硬时钟，而完整版有 8 个工具 + 压缩 + 子代理。
对策：D1 vertical slice + §16 的裁剪顺序 + D5 中午硬冻结。**三项提交物里有两项不是代码**，必须预留半天。

---

## 18. 答辩时最该主动讲的十句话

1. **compaction 的真正驱动力不是 1M 窗口装不下，而是 history 每步被完整重发使单轮成本呈 O(n²)**；顺带还有延迟与中段召回衰减。所以换成大窗口模型也不能省。
2. **我不需要 tokenizer，我需要一个偏高估的估算器加上服务端自己给的 `usage`。** 一次调用之后它就被校准到该 provider 的真实分词行为，而 400 `context_length_exceeded` 是兜底而不是失败。
3. **子代理是上下文隔离与成本摊销装置**，不是并行技巧，也不是专家团队隐喻——60K 的探索换 200 token 的结论，省下的是会话余下每一步的边际 token。
4. **`edit_file` 用精确唯一字符串替换，因为它的失败是安全的**：要么唯一命中，要么什么都不改并告知实际出现次数。行号会漂移、diff 的 hunk header 模型算不对，这两者的失败都是**静默改错位置**。
5. **对 shell 字符串做静态分类不是安全边界，是防误操作的护栏**；真正的边界在 OS 层，所以 `ShellRunner` 留了 `Sandbox` 接缝，并且 agent 始终跑在 git-clean 的 scratch workspace 上。
6. **Skill 不是插件——它不引入新能力，只提供高质量的起始 prompt**。自动审批用 thread-local + finally 保证既不泄漏也不丢失，与 `seal_pending_tool_calls` 是同一个安全模式。远程安装只是把 URL 转成本地 `.md` 文件——skill 引擎不区分来源，它只认格式。
7. **终端方向键问题的根因是 Python 的 I/O 缓冲层与 OS fd 的断层**——`sys.stdin.read(1)` 一次读走了完整的 `\033[A` 三字节，`select()` 检查 OS fd 时已经空了。修复是全程用 `os.read(fd)` 绕过 Python 缓冲，这不是"换个 API"，而是理解了两层缓冲的存在。
8. **`use_skill` 让 skill 激活对用户可见**——模型通过 tool call 显式声明"我正在用某个 skill"，复用已有的工具渲染管线，不需要新增 UI 路径。自动审批用 thread-local + finally + 每轮重置三层保证不泄漏。
9. **目标模式的完成检测宁可早停也不多跑**——误判"已完成为未完成"会白白多跑一轮产生多余输出；误判"未完成为已完成"用户只需多输入一句"继续"。不对称的代价决定了阈值为 1。
10. **方案模式的约束在两层执行**——prompt 层告诉模型不要写文件，状态机在 loop 层控制流程走向。单靠 prompt 是软约束，模型可能在"规划"阶段就开始写文件；状态机保证即使 prompt 失效，用户审批前写操作不会被自动放行。
