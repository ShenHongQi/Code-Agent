Git 仓库
https://github.com/ShenHongQi/Code-Agent

如何运行
依赖 Python 3.11+ 和 uv。克隆仓库后执行 uv tool install -e . 安装，然后在任意项目目录运行 megumin 进入交互模式，或 megumin "任务描述" 单次执行。首次启动交互式引导配置 API Key，凭据保存在 ~/.megumin/config，不入库。默认对接 DeepSeek，可通过环境变量切换任意 OpenAI 兼容模型。

特色功能

一、Agent Loop 主循环（agent/loop.py）
核心是 run_loop 驱动的迭代循环：调用 LLM → 解析响应 → 执行工具 → 结果回填 → 再次调用。五类终止条件：自然完成（finish_reason=stop 且无 tool_calls）、迭代上限（自适应估算，简单任务 8 轮、复杂任务 25 轮）、上下文耗尽（compaction 后仍超限）、致命 LLM 错误（不可重试的 HTTP 状态码）、用户中断（KeyboardInterrupt/ESC）。额外机制：卡住检测（连续 3 轮 Error 时注入反思提示）、遗漏调用检测（正则匹配文本中描述命令却未调用工具，自动纠正）、agent 可通过 extend_iterations 工具自主延长迭代上限至 60 轮。

二、工具系统（agent/tools/）
自研 @tool 装饰器注册机制：从函数签名的类型标注和 docstring 自动生成符合 OpenAI function calling 规范的 JSON Schema，手写参数校验器（类型检查、必填校验、枚举约束）。dispatch 统一入口执行，兜底 try/except 确保任何异常都返回 ToolResult 而非崩溃循环。22 个工具涵盖：文件读写（带行号、mtime 新鲜度校验防覆盖外部修改）、精确编辑（唯一字符串匹配替换）、Shell 执行（stdin=DEVNULL 防挂死、进程组 kill、有界 drain）、正则搜索、后台进程管理、只读子代理、跨会话记忆、网页获取等。

三、上下文管理与 Token 估算（agent/context.py）
手写 TokenEstimator，CJK 字符按 1.0 token/字、英文按 1/3.6 token/字符估算，通过 EMA（指数移动平均，α=0.3）用服务端实际 usage 持续校准。锚定式 Compaction：保留 system prompt + 首轮用户输入 + 最近 6 轮对话，中间部分由模型摘要压缩。安全切点算法确保不在 tool_call 与 tool response 之间截断；heal_orphans 修复压缩后的孤儿 tool_call（补占位响应）或孤儿 tool response（移除）。

四、流式解析与双传输层（agent/stream.py + agent/transport.py）
StreamAccumulator 将 SSE 流式 delta 累积重组为完整消息，处理 tool_calls 跨 chunk 的 index 分片拼接。双传输层：默认 openai SDK Provider，另有纯标准库 urllib + 手写 SSE 行解析的 RawProvider（AGENT_TRANSPORT=raw 切换），证明不依赖任何第三方 SDK 也能完整运行。

五、权限系统（agent/permission.py）
三级风险分类：allow（只读自动放行）、confirm（交互确认）、block（rm -rf 等直接拒绝）。Shell 命令递归解包：管道、逻辑链、子 shell、xargs 嵌套，逐条独立分类取最高风险。交互式箭头键选择菜单，选定后折叠为一行紧凑记录。

六、Skill 系统（agent/skills/）
Skill 是预定义的工作流模板，由 YAML frontmatter + Markdown prompt 定义，支持参数注入（{args}）和自动触发条件。内置 11 个 Skill：review（代码审查）、test（生成测试）、fix（修复问题）、commit（生成 message 并提交）、refactor（重构）、doc（生成文档）、push（提交推送）、explain（解释代码）、init（初始化项目）、frontend（前端全流程）、backend（后端全流程）。Skill 执行时自动审批所有工具调用，无需逐次确认。用户可在 ~/.megumin/skills/ 下创建自定义 Skill。支持远程安装：从 GitHub 文件链接、Gist、任意 URL 下载，并自动识别和转换 Claude Code 格式、AAS 格式、.cursorrules 格式为原生格式。Skill 目录注入 system prompt，模型可根据用户意图自动触发匹配的 Skill。

七、交互与会话（agent/terminal.py + agent/commands.py + agent/session.py）
斜杠命令系统带两级实时自动补全下拉框。/goal 自动目标模式让 agent 自主多轮迭代直到判断目标达成；/plan 方案设计模式先规划再执行；/resume 恢复历史会话；/think 查看完整推理过程。会话自动持久化，History 的 seal_pending_tool_calls 在中断恢复时为未闭合的 tool_call 补占位响应，保证对话格式合法。LLM 调用层按状态码分类错误，全抖动指数退避重试（最多 5 次），context_length_exceeded 自动触发 compaction 降级。

其它说明
项目约 6800 行 Python，运行时仅依赖 openai 一个包（rich 仅用于终端渲染），不使用任何 agent 框架/SDK。完整设计文档含每个决策的替代方案分析见 docs/DESIGN.md。
