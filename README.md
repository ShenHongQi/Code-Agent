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

- **语言**：Python，约 6800 行
- **模型接入**：自研 Provider 抽象层，对接 OpenAI 兼容网关（默认 DeepSeek V4 Pro，可切 Kimi / Qwen / GLM / OpenAI）
- **双传输层**：SDK 实现 + 纯标准库 `urllib` + 手写 SSE 解析（`AGENT_TRANSPORT=raw` 切换）
- **运行时依赖**：仅 `openai` 一个包
- **交互系统**：斜杠命令 + 两级自动补全 + 会话恢复 + 跨会话记忆
- **Skill 系统**：11 个内置 skill，支持自定义与远程安装，模型可通过 `use_skill` 工具自动激活

## 核心模块

| 模块 | 职责 |
|------|------|
| `agent/loop.py` | Agent loop 主循环，5 类终止条件 |
| `agent/context.py` | Token 估算校准 + 锚定式 compaction + 安全切点 + 孤儿自愈 |
| `agent/stream.py` | SSE delta 累积，tool_call 跨 chunk 重组 |
| `agent/history.py` | 消息构造，会话状态，seal_pending_tool_calls |
| `agent/tools/` | @tool 装饰器 registry，签名→schema，手写校验器 |
| `agent/workspace.py` | 路径收敛，敏感文件拦截，FileRegistry 新鲜度 |
| `agent/permission.py` | 三级危险分类（allow/confirm/block），交互式箭头键菜单，skill 自动审批 |
| `agent/shell.py` | ShellRunner（stdin=DEVNULL, 进程组 kill, 有界 drain） |
| `agent/transport.py` | 纯 stdlib Provider 实现，证明 SDK 可替换 |
| `agent/terminal.py` | 终端输入管理，斜杠命令两级自动补全，CJK 宽度适配 |
| `agent/commands.py` | 斜杠命令分发系统（help/think/resume/skill/goal/plan） |
| `agent/skills/` | Skill 引擎：注册/执行/自动审批，内置 + 用户自定义 + 远程安装 |
| `agent/session.py` | 会话持久化与恢复 |
| `agent/memory.py` | 跨会话记忆管理 |
| `agent/markdown.py` | Markdown 终端渲染 |
| `agent/banner.py` | 启动 banner 与状态显示 |
| `agent/ui.py` | ANSI 流式渲染，上下文用量常驻显示 |
| `agent/prompts.py` | System prompt 与 subagent prompt 构建 |
| `agent/goal.py` | 自动目标模式 + 方案设计模式 |

## 工具集（22 个）

| 工具 | 功能 |
|------|------|
| `read_file` | 带行号读取文件，写入 FileRegistry |
| `write_file` | 新建文件（已存在则拒绝） |
| `edit_file` | 精确唯一字符串替换，mtime 校验 |
| `multi_edit` | 多位置批量编辑 |
| `view_diff` | 查看文件 diff |
| `delete_file` | 删除文件 |
| `rename_file` | 重命名/移动文件 |
| `list_dir` | 列出目录内容 |
| `glob` | 按模式列路径，200 条封顶，按 mtime 排序 |
| `grep` | 正则搜索内容，100 匹配封顶 |
| `bash` | Shell 执行，超时/输出封顶/权限检查 |
| `spawn` | 后台启动长运行进程 |
| `proc_status` | 查看后台进程状态与输出 |
| `proc_kill` | 终止后台进程 |
| `todo_write` | 多步任务计划 |
| `task` | 派生只读子代理探索代码库 |
| `web_fetch` | 获取网页内容 |
| `memory_write` | 写入跨会话记忆 |
| `memory_read` | 读取跨会话记忆 |
| `memory_forget` | 删除跨会话记忆 |
| `extend_iterations` | 动态扩展迭代上限 |
| `use_skill` | 激活 skill 工作流，启用自动审批 |

## 斜杠命令

在交互模式下输入 `/` 触发自动补全下拉框：

| 命令 | 功能 | 别名 |
|------|------|------|
| `/help` | 显示所有可用命令与 skill | `/h`, `/?` |
| `/think` | 展开上一轮完整中间思考 | `/thinking` |
| `/resume` | 交互式恢复历史会话 | `/r` |
| `/skill` | 管理和执行 skill | `/s` |
| `/goal` | 自动目标模式，agent 自主迭代直到完成 | `/g` |
| `/plan` | 方案设计模式，先规划再执行 | `/p` |
| `/permissions` | 查看/切换权限模式 | `/perm` |

## Skill 系统

Skill 是预定义的工作流模板，执行时自动审批工具调用，无需逐次确认。

模型可通过 `use_skill` 工具自动识别并激活匹配的 skill——当用户请求匹配某个 skill 的触发条件时，模型主动调用 `use_skill`，UI 显示激活状态，后续工具调用自动审批。

### 内置 Skill

| Skill | 功能 | 别名 |
|-------|------|------|
| `review` | 审查代码变更，给出改进建议 | `cr` |
| `test` | 为指定代码生成测试 | `t` |
| `explain` | 详细解释代码实现 | `ex` |
| `commit` | 生成 commit message 并提交 | `ci` |
| `fix` | 分析并修复问题 | `f` |
| `refactor` | 重构代码，改善结构 | `rf` |
| `doc` | 生成或更新文档 | `d` |
| `push` | 提交并推送到远程 | `p` |
| `init` | 初始化项目结构 | — |
| `frontend` | 前端开发全流程（组件/样式/状态/测试/构建） | `fe`, `web` |
| `backend` | 后端开发全流程（API/数据库/认证/测试/部署） | `be`, `api` |

### 使用方式

```bash
/skill review             # 审查当前变更
/skill test utils.py      # 为 utils.py 生成测试
/skill frontend 做一个登录页  # 前端开发任务
/skill backend 用户注册API   # 后端开发任务
```

### 自定义与远程安装

```bash
/skill create                         # 创建自定义 skill 模板
/skill install <url>                  # 从远程安装 skill
```

支持从以下来源安装：
- **GitHub 文件链接**：自动转换为 raw URL 下载
- **GitHub Gist**：直接获取 gist 内容
- **任意 URL**：直链 `.md` / `.yaml` 文件
- **多格式兼容**：自动识别并转换 Claude Code 格式、AAS（Agent Skills）格式、`.cursorrules` 格式

自定义 skill 存放在 `~/.megumin/skills/`，支持 `.md`（YAML frontmatter）和 `.yaml` 两种格式。

## Windows 用户

本项目依赖 Linux/macOS 终端 API，**无法直接在 Windows 原生环境运行**。Windows 用户请通过 WSL2 运行——零代码改动、完整功能。

详见 **[docs/WINDOWS_SETUP.md](docs/WINDOWS_SETUP.md)**，包含：
- WSL2 安装与配置（一条命令）
- Windows Terminal 推荐设置
- 项目安装与运行
- 演示视频录制方案（OBS / Game Bar / asciinema）
- 常见问题排查

## 运行测试

```bash
python -m tests.test_stream
python -m tests.test_context
python -m tests.test_permission
python -m tests.test_workspace
python -m tests.test_tools
```

## 配置项

通过环境变量、`.env` 文件或 `~/.megumin/config` 配置：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AGENT_API_KEY` | (必填) | API Key |
| `AGENT_BASE_URL` | `https://api.deepseek.com` | API 端点 |
| `AGENT_MODEL` | `deepseek-v4-pro` | 模型名 |
| `AGENT_TRANSPORT` | `sdk` | 传输层（`sdk` 或 `raw`） |
| `AGENT_MAX_ITERATIONS` | `40` | 单轮最大迭代 |
| `AGENT_WORKSPACE` | `cwd` | 工作区路径 |
| `AGENT_CONTEXT_LIMIT` | `0`（用模型默认） | 强制上下文限制 |
| `AGENT_NO_STREAM` | `false` | 禁用流式输出 |

## 设计文档

完整设计文档见 **[docs/DESIGN.md](docs/DESIGN.md)** —— 包含每个决策被拒绝的替代方案与理由，为答辩准备。

> 注：本文件是仓库说明，不是考核提交物中的 `README.txt`（后者另行撰写，1000 汉字以内）。
