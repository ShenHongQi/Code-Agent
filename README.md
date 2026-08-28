# Code-Agent

一个从零实现的编程智能体（coding agent）：通过与大语言模型交互，自主读写文件、执行命令，完成交给它的编程任务。

**不使用任何 agent 框架 / SDK**，也不依赖 API 服务端托管的代码执行或文件工具。对话历史与上下文管理、工具定义与本地执行、模型输出解析、循环终止条件、错误处理全部自行编写。

## 快速开始

```bash
# 安装（需要 uv，没有的话先 curl -LsSf https://astral.sh/uv/install.sh | sh）
git clone https://github.com/ShenHongQi/Code-Agent.git
cd Code-Agent
uv tool install -e .

# 首次启动会交互式引导配置 API Key
megumin
```

安装后在任意目录使用：
```bash
cd /path/to/your/project
megumin                    # 交互模式
megumin "写一个排序算法"   # 单次任务
```

配置保存在 `~/.megumin/config`，后续启动无需再配置。

## 技术特性

- **语言**：Python 3.13，约 2500 行
- **模型接入**：自研 Provider 抽象层，对接 OpenAI 兼容网关（默认 DeepSeek，可切 Kimi / Qwen / GLM / OpenAI）
- **双传输层**：SDK 实现 + 纯标准库 `urllib` + 手写 SSE 解析（`AGENT_TRANSPORT=raw` 切换）
- **运行时依赖**：仅 `openai` 一个包

## 核心模块

| 模块 | 职责 |
|------|------|
| `agent/loop.py` | Agent loop 主循环，5 类终止条件 |
| `agent/context.py` | Token 估算校准 + 锚定式 compaction + 安全切点 + 孤儿自愈 |
| `agent/stream.py` | SSE delta 累积，tool_call 跨 chunk 重组 |
| `agent/history.py` | 消息构造，会话状态，seal_pending_tool_calls |
| `agent/tools/` | @tool 装饰器 registry，签名→schema，手写校验器 |
| `agent/workspace.py` | 路径收敛，敏感文件拦截，FileRegistry 新鲜度 |
| `agent/permission.py` | 三级危险分类（allow/confirm/block） |
| `agent/shell.py` | ShellRunner（stdin=DEVNULL, 进程组 kill, 有界 drain） |
| `agent/transport.py` | 纯 stdlib Provider 实现，证明 SDK 可替换 |

## 工具集

| 工具 | 功能 |
|------|------|
| `read_file` | 带行号读取文件，写入 FileRegistry |
| `write_file` | 新建文件（已存在则拒绝） |
| `edit_file` | 精确唯一字符串替换，mtime 校验 |
| `glob` | 按模式列路径，200 条封顶，按 mtime 排序 |
| `grep` | 正则搜索内容，100 匹配封顶 |
| `bash` | Shell 执行，超时/输出封顶/权限检查 |
| `todo_write` | 多步任务计划 |
| `task` | 派生只读子代理探索代码库 |

## 运行测试

```bash
python -m tests.test_stream
python -m tests.test_context
python -m tests.test_permission
python -m tests.test_workspace
python -m tests.test_tools
```

## 配置项

通过环境变量或 `.env` 文件配置：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AGENT_API_KEY` | (必填) | API Key |
| `AGENT_BASE_URL` | `https://api.deepseek.com/v1` | API 端点 |
| `AGENT_MODEL` | `deepseek-chat` | 模型名 |
| `AGENT_TRANSPORT` | `sdk` | 传输层（`sdk` 或 `raw`） |
| `AGENT_MAX_ITERATIONS` | `40` | 单轮最大迭代 |
| `AGENT_WORKSPACE` | `cwd` | 工作区路径 |
| `AGENT_CONTEXT_LIMIT` | `0`（用默认） | 强制上下文限制（测试用） |
| `AGENT_NO_STREAM` | `false` | 禁用流式输出 |

## 设计文档

完整设计文档见 **[docs/DESIGN.md](docs/DESIGN.md)** —— 包含每个决策被拒绝的替代方案与理由，为答辩准备。

> 注：本文件是仓库说明，不是考核提交物中的 `README.txt`（后者另行撰写，1000 汉字以内）。
