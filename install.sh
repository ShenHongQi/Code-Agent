#!/bin/bash
# Megumin Coding Agent 一键安装脚本
set -e

echo "🔥 Megumin Coding Agent 安装程序"
echo "=================================="
echo

# Check uv
if ! command -v uv &> /dev/null; then
    echo "正在安装 uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# Get script directory (where the repo is)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Install as global tool
echo "📦 安装 megumin 命令..."
uv tool install -e "$SCRIPT_DIR" --force 2>/dev/null || uv tool install -e "$SCRIPT_DIR"

# Setup API key
CONFIG_DIR="$HOME/.megumin"
CONFIG_FILE="$CONFIG_DIR/config"
mkdir -p "$CONFIG_DIR"

if [ -f "$CONFIG_FILE" ] && grep -q "AGENT_API_KEY" "$CONFIG_FILE"; then
    echo "✓ 已检测到 API Key 配置"
    read -p "是否重新设置 API Key？[y/N]: " reset
    if [ "$reset" != "y" ] && [ "$reset" != "Y" ]; then
        echo
        echo "✅ 安装完成！在任意目录运行: megumin"
        exit 0
    fi
fi

echo
echo "请输入你的 API Key（默认使用智谱 GLM-4-Flash 免费模型）"
echo "智谱 API Key 申请: https://open.bigmodel.cn/"
echo
read -p "API Key: " api_key

if [ -z "$api_key" ]; then
    echo "❌ API Key 不能为空"
    exit 1
fi

# Write config
cat > "$CONFIG_FILE" << EOF
AGENT_API_KEY=$api_key
AGENT_BASE_URL=https://open.bigmodel.cn/api/paas/v4
AGENT_MODEL=glm-4-flash
EOF

chmod 600 "$CONFIG_FILE"

echo
echo "✅ 安装完成！"
echo
echo "使用方式："
echo "  cd /path/to/your/project"
echo "  megumin                    # 交互模式"
echo "  megumin \"写一个排序算法\"   # 单次任务"
echo
echo "配置文件: ~/.megumin/config"
