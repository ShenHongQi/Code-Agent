# Codex 权限方案调研报告

## 一、整体架构概览

Codex 的权限系统由三层组成：

```
┌─────────────────────────────────────────────┐
│  用户配置层 (config.toml)                    │
│  approval_policy + sandbox_mode + profiles   │
├─────────────────────────────────────────────┤
│  规则引擎层 (exec_policy)                    │
│  静态命令匹配 + 危险命令检测 + 沙箱约束      │
├─────────────────────────────────────────────┤
│  Guardian 子代理层 (AI auto-review)          │
│  模型审批 + 风险评级 + 授权评估              │
└─────────────────────────────────────────────┘
```

---

## 二、用户配置层：三个审批模式

### 2.1 approval_policy（审批策略）

在 `~/.codex/config.toml` 中配置：

| 值 | 行为 |
|---|---|
| `"suggest"` | **建议模式**（默认）— 所有写操作和命令都需用户批准，只读操作自动通过 |
| `"auto-edit"` | **自动编辑** — 文件编辑自动通过，命令仍需审批 |
| `"full-auto"` | **全自动** — 所有操作自动通过（仍有沙箱限制） |

> 注：旧版有 `"untrusted"` 策略（更严格，连读操作都需确认），已在 v0.149 中移除。

### 2.2 sandbox_mode（沙箱模式）

| 值 | 文件系统权限 | 网络权限 |
|---|---|---|
| `"read-only"` | 只读 | 无网络 |
| `"workspace-write"` | 项目目录内可写，其他只读 | 无网络 |
| `"danger-full-access"` | 完全访问 | 完全访问 |

### 2.3 Permission Profiles（权限配置文件）

Codex 支持命名的权限配置文件（类似预设），内置三个：
- `read-only` → 对应 ReadOnly sandbox
- `workspace-write` → 对应 WorkspaceWrite sandbox
- `danger-full-access` → 完全访问（Disabled 状态）

用户可以在 `config.toml` 中自定义 profile，指定：
- 文件系统条目：路径 + 访问模式（read/write/deny）
- 网络权限：是否启用
- 路径支持 glob 模式和特殊路径（project_roots, tmpdir, /tmp）

---

## 三、规则引擎层：静态命令检测

### 3.1 危险命令检测 (`is_dangerous_command`)

纯静态分析，不依赖 AI：

```rust
// 检测规则：
match cmd {
    "rm" if has_force_flag => ForcedRm,    // rm -rf 类
    "sudo" => 递归检查子命令,
    "env" => 跳过环境变量，检查实际命令,
    "trap" => 检查 trap 动作中的命令,
}
```

特点：
- **不需要 AI 判断**，纯正则/token 匹配
- 递归展开：`sudo env rm -rf /` 会递归到最内层命令
- 有最大递归深度限制（8 层），防止无限嵌套

### 3.2 Exec Policy（执行策略）

基于规则的策略引擎：
- **前缀匹配规则**：命令前缀 → Allow/Deny 决策
- **网络规则**：协议 + 主机 + 端口 → Allow/Deny
- **禁止建议列表** (`BANNED_PREFIX_SUGGESTIONS`)：不允许 agent 自行添加的宽泛前缀，如 `/bin/bash`, `node`, `python` 等

### 3.3 沙箱 (Sandbox)

实际的 OS 级隔离：
- 文件系统：限制可写路径到项目根目录
- 网络：可配置白名单
- 沙箱重试/升级本身不被视为可疑行为

---

## 四、Guardian 子代理层：AI 自动审批（核心创新）

**这是 Codex 最独特的设计——用一个独立的 AI 模型来审批另一个 AI 的操作。**

### 4.1 工作流程

```
Agent 想执行操作
      │
      ▼
┌─ Guardian 审查 ─┐
│ 接收:            │
│  - 操作详情      │
│  - 对话上下文    │
│  - 安全策略      │
│                  │
│ 输出:            │
│  - risk_level    │
│  - user_auth     │
│  - outcome       │
│  - rationale     │
└──────────────────┘
      │
      ▼
  ┌────────┐
  │approved│ → 执行
  │denied  │ → 拦截，可选人工覆盖
  │timedOut│ → 降级处理
  │aborted │ → 取消
  └────────┘
```

### 4.2 风险评级体系 (`GuardianRiskLevel`)

```
low      → 常规、范围窄、易回滚、无凭证访问、无网络导出
medium   → 有一定影响但可控、副作用可逆
high     → 危险或难以逆转、可能造成不可挽回的损害
critical → 明显的凭证/密钥泄露到不信任目的地，或大规模不可逆破坏
```

### 4.3 用户授权评估 (`GuardianUserAuthorization`)

```
high    → 用户明确请求或批准了该精确操作
medium  → 用户授权了实质效果但不是具体实现方式
low     → 操作只是松散地跟随用户目标，授权不明确
unknown → 无证据表明用户授权，操作来自 AI 漂移或不信任内容
```

### 4.4 安全策略中的四大风险分类

Guardian 评估每个操作时，检查以下四类风险：

#### 1) 数据泄露 (Data Exfiltration)
- 向不信任目的地发送敏感数据 → `high`
- 信任目的地：组织内部存储、私有仓库、已批准工作流
- **必须追溯实际数据来源**，即使 payload 看似无害
- 共享文件或链接 = 披露文件内容

#### 2) 凭证探测 (Credential Probing)
- 从非正常来源提取凭证 → `high`
- 正常认证流程 → 不视为探测
- 示例：从浏览器 profile 或服务日志中提取密钥

#### 3) 持久安全削弱 (Persistent Security Weakening)
- 修改安全设置且效果超出当前会话 → `high`
- 临时禁用窄范围证书检查 → `medium`

#### 4) 破坏性操作 (Destructive Actions)
- 删除难以恢复的数据、破坏生产服务 → `high`
- git 操作：只影响用户自己的 feature 分支 → `low/medium`
- `rm -rf`：经检查目标为空/小/可控 → `low/medium`
- **变量遮蔽（如 `HOME`）被视为高风险**

### 4.5 结果决策矩阵

```
risk=low      → allow（除非有显式 deny 规则或 prompt injection）
risk=medium   → allow（同上）
risk=high     → 仅当 user_auth >= medium 且范围窄时 allow，否则 deny
risk=critical → deny（即使用户授权也拒绝）
```

**用户覆盖机制**：如果操作被 deny，用户可以明确重新批准（`ThreadApproveGuardianDeniedAction`），此时 Guardian 会重新评估：
- user_auth 提升为 `high`
- 可以覆盖 high 风险的 deny
- 但**不能覆盖 critical 级别**

### 4.6 信任体系

Guardian 的信任判定非常精细：

**可信内容**（可建立 user_authorization）：
- 用户和开发者消息
- `AGENTS.md` 文件
- `request_user_input` 工具的响应

**不可信内容**（不能扩展授权范围）：
- 工具输出
- 技能/插件描述
- AI 助手自己的输出
- 但可以提供实现细节

**例外**：如果用户明确说"按照这个文件的指示做"，则文件内容可获得间接授权。

### 4.7 Guardian 的操作审查范围

Guardian 审查 7 类操作（`GuardianApprovalReviewAction`）：

| 操作类型 | 说明 |
|---|---|
| `command` | Shell 命令执行 |
| `execve` | 直接程序执行 |
| `writeStdin` | 向已有进程写入 stdin |
| `applyPatch` | 文件补丁应用 |
| `networkAccess` | 网络请求（http/https/socks5） |
| `mcpToolCall` | MCP 工具调用 |
| `requestPermissions` | 请求扩展权限（文件系统/网络） |

### 4.8 Guardian 自身的约束

- 运行在**相同执行环境**但只能执行只读命令
- **无网络访问**
- 不能使用 `sandbox_permissions`
- 审查的是操作本身，不是操作结果

---

## 五、Claude Code 的权限方案（对比参考）

Claude Code 的权限系统较 Codex 更简单，主要基于**工具分类 + 用户确认**：

### 5.1 权限模式

| 模式 | 行为 |
|---|---|
| Default (Ask) | 读操作自动通过，写操作需确认 |
| Auto-accept | 本次会话所有操作自动通过 |
| Plan mode | 只允许读工具，不允许写 |

### 5.2 工具分类

- **安全工具**（自动通过）：Read, Glob, Grep, WebFetch
- **敏感工具**（需确认）：Write, Edit, Bash, Delete
- **特殊工具**：Agent（子代理创建）

### 5.3 Allowlist / Denylist

用户可在 `.claude/settings.json` 中配置：
- `allowedTools`: glob 模式匹配，自动放行
- `deniedTools`: 永久拒绝

---

## 六、对 Megumin 的设计建议

基于以上调研，建议 Megumin 采用**三级方案**，从简单到复杂渐进实现：

### 第一级：静态工具分类 + 用户确认（最小可行）

```python
SAFE_TOOLS = {"read_file", "glob", "grep", "list_dir", "web_fetch"}
SENSITIVE_TOOLS = {"write_file", "edit_file", "bash", "delete_file", "multi_edit"}

def needs_approval(tool_name, args):
    if tool_name in SAFE_TOOLS:
        return False
    if tool_name == "bash":
        return is_dangerous_command(args.get("command", ""))
    return True
```

### 第二级：基于规则的风险评估

```python
# 危险命令检测（Codex 的 is_dangerous_command 方案）
DANGEROUS_PATTERNS = [
    (r"rm\s+.*-[^\s]*f", "ForcedRm"),
    (r"git\s+push\s+.*--force", "ForcePush"),
    (r"DROP\s+TABLE|DELETE\s+FROM", "SQLDanger"),
    (r"chmod\s+777", "PermissionWeaken"),
    (r"curl.*\|\s*sh", "RemoteExec"),
]

# 沙箱：限制可写路径
WRITABLE_ROOTS = [workspace_root]
def check_write_path(path):
    return any(path.startswith(root) for root in WRITABLE_ROOTS)
```

### 第三级：AI 审批子代理（Codex Guardian 方案）

这是最完整的方案——用一个独立的 LLM 调用来审查操作：

```python
GUARDIAN_PROMPT = """
你是安全审查员，审查以下操作的风险。

操作: {action_type} - {action_detail}
上下文: {recent_conversation}
用户原始请求: {user_request}

评估:
1. risk_level: low/medium/high/critical
2. user_authorization: high/medium/low/unknown
3. outcome: allow/deny
4. rationale: 一句话理由

规则:
- low/medium 风险 → allow
- high 风险 + user_auth >= medium → allow
- high 风险 + user_auth < medium → deny
- critical → deny
"""
```

**核心设计要点**：
1. Guardian 是独立调用，不共享 agent 的对话上下文（防止 prompt injection 影响审查）
2. Guardian 只有只读权限，不能执行写操作
3. Guardian 输出结构化结果（risk_level + user_auth + outcome + rationale）
4. 用户可以覆盖 deny（但不能覆盖 critical）
5. 每次审查携带最小必要上下文，不是整个对话历史

---

## 七、关键设计决策总结

| 维度 | Codex 方案 | 建议 Megumin 方案 |
|---|---|---|
| 审批触发 | 沙箱拦截 + 规则匹配 + 全自动模式可跳过 | 工具分类 + 危险命令检测 |
| 风险判定 | AI Guardian 子代理（独立 LLM 调用） | 可选：先静态规则，后期升级为 AI 审批 |
| 用户覆盖 | 可覆盖 high，不可覆盖 critical | 展示风险等级，用户选择 y/n |
| 信任模型 | 精细分类（用户消息可信 vs 工具输出不可信） | 可简化为用户输入可信、其他不可信 |
| 持久化 | config.toml + permission profiles | 可存储在 ~/.megumin/permissions.yaml |
| 沙箱 | OS 级文件系统/网络隔离（Rust 实现） | Python 层面路径检查（非 OS 级） |
