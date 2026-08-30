# Windows 部署指南（WSL2）

本项目的终端交互系统（readline、交互式菜单、ESC 中断、进程组管理）依赖 Linux/macOS 的底层 API（`termios`、`fcntl`、`SIGWINCH`、`os.killpg`），**无法直接在 Windows 原生环境运行**。

推荐方案：**在 Windows 上通过 WSL2（Windows Subsystem for Linux 2）运行**。WSL2 运行的是真正的 Linux 内核，所有 Linux API 完全可用，项目零代码改动即可运行，体验与 macOS/Linux 原生环境完全一致。

---

## 目录

1. [环境要求](#环境要求)
2. [安装 WSL2](#安装-wsl2)
3. [配置 Windows Terminal](#配置-windows-terminal)
4. [安装项目依赖](#安装项目依赖)
5. [配置与运行](#配置与运行)
6. [录制演示视频](#录制演示视频)
7. [常见问题](#常见问题)
8. [为什么不直接支持原生 Windows](#为什么不直接支持原生-windows)

---

## 环境要求

| 项目 | 最低要求 |
|------|----------|
| Windows 版本 | Windows 10 2004（Build 19041）或 Windows 11 |
| 内存 | 建议 8GB+（WSL2 默认分配一半物理内存） |
| 磁盘 | 约 2GB（WSL 发行版 + Python + 项目） |
| 网络 | 需要访问 API 端点（DeepSeek/OpenAI/智谱等） |

---

## 安装 WSL2

### 步骤 1：启用 WSL

以 **管理员身份** 打开 PowerShell，执行：

```powershell
wsl --install
```

这会自动：
- 启用 WSL 功能和虚拟机平台
- 下载并安装 Ubuntu（默认发行版）
- 设置 WSL2 为默认版本

> 如果你的 Windows 版本较老（低于 Build 19041），需要手动启用：
> ```powershell
> dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
> dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
> ```
> 然后重启，再执行 `wsl --set-default-version 2`。

### 步骤 2：重启电脑

安装完成后 **必须重启**。

### 步骤 3：初始化 Ubuntu

重启后打开 Windows Terminal（或搜索"Ubuntu"），首次启动会要求创建用户名和密码：

```
Enter new UNIX username: yourname
New password: ********
```

### 步骤 4：验证安装

```bash
# 在 WSL 终端中执行
cat /etc/os-release    # 应显示 Ubuntu 信息
uname -r               # 应显示 Linux 内核版本（如 5.15.x-microsoft-standard-WSL2）
python3 --version      # 应显示 Python 3.10+
```

---

## 配置 Windows Terminal

**强烈建议使用 Windows Terminal**（非旧版 cmd.exe 或 PowerShell 窗口），它完整支持：
- 256 色和 True Color（项目的 Megumin 惠惠主题色 `#e05252` 能正确渲染）
- Unicode 和 CJK 宽字符（中文输出不乱码）
- ANSI 转义序列（交互式菜单、spinner 动画、Markdown 渲染）

### 安装

Windows 11 已预装。Windows 10 从 Microsoft Store 搜索 "Windows Terminal" 安装。

### 推荐设置

打开 Windows Terminal → 设置（Ctrl+,）：

1. **默认配置文件**：选择 "Ubuntu"（这样每次打开直接进 WSL）
2. **字体**：推荐使用等宽字体支持中文，如：
   - **Cascadia Code**（Windows Terminal 默认，中文回退到系统字体）
   - **Sarasa Gothic Mono**（更好的中日韩等宽字体）
   - **JetBrains Mono + Noto Sans CJK**
3. **配色方案**：选择深色主题（如 "One Half Dark"），与项目的 Megumin 深色配色搭配最佳
4. **起始目录**：设为 `\\wsl$\Ubuntu\home\yourname`（直接打开 WSL 家目录）

### 可选：调整窗口大小

录制视频时建议：
- 列数 120+，行数 35+（设置 → Ubuntu 配置文件 → 起始大小）
- 字体大小 14-16pt（录屏清晰）

---

## 安装项目依赖

在 WSL 终端中执行以下命令：

### 1. 更新系统

```bash
sudo apt update && sudo apt upgrade -y
```

### 2. 安装 Python 和基础工具

```bash
# Ubuntu 22.04+ 自带 Python 3.10+，但确保完整安装
sudo apt install -y python3 python3-pip python3-venv git curl
```

### 3. 安装 uv（Python 包管理器）

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc   # 或重新打开终端使 uv 命令生效
```

### 4. 克隆项目

```bash
cd ~
git clone https://github.com/ShenHongQi/Code-Agent.git
cd Code-Agent
```

> **重要**：项目必须放在 WSL 文件系统内（`~/Code-Agent`），不要放在 `/mnt/c/...`（Windows 挂载路径）。WSL 访问 Windows 文件系统有严重性能损耗（10-50x 慢），会导致文件操作和 `glob`/`grep` 工具极慢。

### 5. 安装依赖并验证

```bash
# 同步依赖
uv sync

# 验证安装
uv run python -m agent --help
```

---

## 配置与运行

### 首次运行

```bash
cd ~/Code-Agent
uv run python -m agent
```

首次启动会进入交互式配置向导：

```
🔥 Megumin Coding Agent — 首次启动配置
==========================================

默认使用智谱 GLM-4-Flash（免费模型）
申请 API Key: https://open.bigmodel.cn/

请输入 API Key: <粘贴你的 API Key>

选择模型 provider:
  1. 智谱 GLM-4-Flash (免费，默认)
  2. DeepSeek
  3. OpenAI
  4. 自定义
选择 [1]:
```

配置保存在 `~/.megumin/config`，后续启动无需重新配置。

### 推荐的免费/低成本模型

| Provider | 模型 | 费用 | 申请地址 |
|----------|------|------|----------|
| 智谱 | GLM-4-Flash | **免费** | https://open.bigmodel.cn/ |
| DeepSeek | deepseek-chat | 极低（约 ¥1/M tokens） | https://platform.deepseek.com/ |

### 日常使用

```bash
# 进入你要操作的项目目录
cd ~/your-project

# 启动交互模式
megumin

# 或直接给出任务
megumin "帮我写一个 Flask REST API"
```

### 全局安装（可选）

如果希望在任意目录直接使用 `megumin` 命令：

```bash
cd ~/Code-Agent
uv tool install -e .
```

---

## 录制演示视频

### 方案 A：OBS Studio 录屏（推荐）

最简单的方案——在 Windows 上用 OBS 录制 Windows Terminal 窗口。

1. **下载安装 OBS Studio**：https://obsproject.com/download
2. **设置录制**：
   - 来源 → 添加 "窗口捕获" → 选择 Windows Terminal
   - 输出 → 录像路径设为桌面，格式 MP4
   - 视频 → 分辨率 1920×1080，帧率 30
3. **录制前准备**：
   - 调大 Windows Terminal 字体（14-16pt）
   - 窗口最大化或调至合适大小
   - 关掉其他可能弹通知的应用
4. **开始录制**：OBS 按 "开始录制"，切到 Windows Terminal 操作即可

### 方案 B：Xbox Game Bar 快速录屏

Windows 10/11 内置，无需安装额外软件。

1. 点击 Windows Terminal 窗口使其获得焦点
2. 按 `Win + G` 打开 Game Bar
3. 点击录制按钮（或按 `Win + Alt + R` 直接开始）
4. 操作完成后再按 `Win + Alt + R` 停止
5. 视频保存在 `C:\Users\你的用户名\Videos\Captures\`

### 方案 C：asciinema 终端录制

在 WSL 内录制纯终端会话，生成可回放的轻量文件。

```bash
# 安装
pip install asciinema

# 录制（按 Ctrl+D 或 exit 停止）
asciinema rec demo.cast

# 本地回放
asciinema play demo.cast

# 上传到 asciinema.org 获得分享链接
asciinema upload demo.cast

# 转换为 GIF（需要额外工具）
pip install asciinema-agg
agg demo.cast demo.gif
```

### 演示脚本建议

录制演示时的操作顺序建议：

```
1. 启动 megumin，展示 banner 和交互界面
2. 输入一个简单任务："写一个 Python 快速排序"
   → 展示流式输出、文件创建、工具调用
3. 输入 "/skill test sort.py"
   → 展示 skill 系统、自动测试生成
4. 展示斜杠命令补全（输入 / 后用方向键选择）
5. 展示权限确认交互（执行一个需要确认的命令）
6. 输入 "/resume" 展示会话恢复
7. 收尾
```

---

## 常见问题

### Q: WSL 里能访问 Windows 的文件吗？

可以。Windows 的 C 盘挂载在 `/mnt/c/`。但**不建议把项目放在那里**——跨文件系统性能极差。如果需要在 Windows 和 WSL 之间传文件：

```bash
# Windows → WSL
cp /mnt/c/Users/你的用户名/Desktop/file.txt ~/

# WSL → Windows
cp ~/output.txt /mnt/c/Users/你的用户名/Desktop/
```

### Q: 在 Windows 资源管理器里能看到 WSL 的文件吗？

可以。资源管理器地址栏输入 `\\wsl$\Ubuntu` 即可浏览 WSL 文件系统。

### Q: API Key 怎么配置？

首次启动自动引导。也可以手动编辑配置文件：

```bash
# 编辑配置
nano ~/.megumin/config
```

内容格式：
```
AGENT_API_KEY=你的API_Key
AGENT_BASE_URL=https://open.bigmodel.cn/api/paas/v4
AGENT_MODEL=glm-4-flash
```

### Q: 提示 `uv: command not found`？

```bash
source ~/.bashrc
# 或重新打开终端
```

如果还不行，重新安装 uv：
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Q: Python 版本太低？

项目需要 Python 3.11+。Ubuntu 22.04 自带 3.10，可以用 uv 管理 Python 版本：

```bash
uv python install 3.13
```

uv 会自动使用合适的 Python 版本。

### Q: 终端显示乱码？

1. 确认使用的是 **Windows Terminal**，不是旧版 cmd.exe
2. 检查字体是否支持中文（推荐 Cascadia Code 或 Sarasa Gothic Mono）
3. 确认 WSL 的 locale 设置正确：
   ```bash
   locale
   # 应显示 LANG=C.UTF-8 或 zh_CN.UTF-8
   ```

### Q: 录屏时 Windows Terminal 窗口闪烁？

OBS 录制时选择 "窗口捕获" 而不是 "显示器捕获"，可以减少闪烁。如果还有问题：
- OBS → 来源 → 窗口捕获 → 属性 → 捕获方式改为 "Windows 10 (1903+)"

### Q: WSL 占用太多内存？

创建 `C:\Users\你的用户名\.wslconfig` 文件：
```ini
[wsl2]
memory=4GB
processors=2
```
保存后执行 `wsl --shutdown` 重启 WSL。

---

## 为什么不直接支持原生 Windows

本项目的终端交互深度依赖 POSIX API，原生 Windows 缺少以下关键能力：

| 功能 | Linux/macOS API | Windows 现状 |
|------|-----------------|--------------|
| 单字符无缓冲读取 | `termios` + `tty.setcbreak` | 需用 `msvcrt.getch()`，API 完全不同 |
| 非阻塞 stdin 检测 | `fcntl` + `O_NONBLOCK` | 无直接等价物 |
| stdin 的 `select()` | `select.select([stdin])` | Windows `select` 仅支持 socket |
| 终端 resize 信号 | `signal.SIGWINCH` | 不存在 |
| 进程组信号 | `os.killpg` + `SIGTERM`/`SIGKILL` | 不存在，需用 `taskkill` |
| readline 历史/补全 | `readline` 模块 | 需额外安装 `pyreadline3` |

要完整支持原生 Windows，需要：
- 用 `msvcrt` 重写所有键盘输入逻辑（约 400 行）
- 用 `subprocess.Popen.terminate()` 替代进程组管理（语义不同，子进程可能泄漏）
- 或引入 `prompt_toolkit` 跨平台终端库（增加约 5MB 依赖）

**WSL2 是最优解**：零代码改动、完整功能、原生性能、视觉效果与 macOS 一致。
