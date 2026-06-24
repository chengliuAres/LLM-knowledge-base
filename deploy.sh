#!/bin/bash
# 一键部署脚本 — 文档&代码知识库
# 用法: ./deploy.sh [端口号，默认8000]

set -e

cd "$(dirname "$0")"

BASE_PORT=${1:-8000}
PROJECT_DIR="$(pwd)"

# 检查端口是否被占用，自动找可用端口
find_available_port() {
    local port=$1
    while true; do
        if ! lsof -ti tcp:"$port" > /dev/null 2>&1; then
            echo $port
            return
        fi
        echo "   ⚠️  端口 $port 被占用，尝试 $((port+1))..." >&2
        port=$((port+1))
    done
}

PORT=$(find_available_port $BASE_PORT)

echo "=========================================="
echo "  文档&代码知识库 — 一键部署"
echo "=========================================="
echo ""

# ========== 环境检查 ==========
echo "🔍 检查环境..."

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到 python3"
    echo "   安装方式: brew install python@3.11"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]); then
    echo "❌ Python 版本过低: $PYTHON_VERSION（需要 >= 3.10）"
    echo "   安装方式: brew install python@3.11"
    exit 1
fi
echo "   ✅ Python $PYTHON_VERSION"

# 检查 pip
if ! python3 -m pip --version &> /dev/null; then
    echo "❌ 未找到 pip"
    echo "   安装方式: python3 -m ensurepip --upgrade"
    exit 1
fi
echo "   ✅ pip 可用"

# 检查 git（可选，用于克隆）
if command -v git &> /dev/null; then
    echo "   ✅ git $(git --version | awk '{print $3}')"
else
    echo "   ⚠️  git 未安装（非必需，但建议安装）"
fi

# ========== 创建虚拟环境 ==========
echo ""
echo "📦 创建虚拟环境..."

if [ -d "backend/venv" ]; then
    echo "   ℹ️  已存在 backend/venv，跳过创建"
else
    cd backend
    python3 -m venv venv
    cd ..
    echo "   ✅ 虚拟环境创建完成"
fi

# 激活虚拟环境
# shellcheck disable=SC1091
source backend/venv/bin/activate

# ========== 安装依赖 ==========
echo ""
echo "📥 安装 Python 依赖..."

# 升级 pip
pip install --upgrade pip > /dev/null 2>&1

# 安装项目依赖
if [ -f "backend/requirements.txt" ]; then
    pip install -r backend/requirements.txt
    echo "   ✅ 项目依赖安装完成"
else
    echo "❌ 未找到 backend/requirements.txt"
    exit 1
fi

# ========== 预下载模型（可选，首次启动也会自动下载）==========
echo ""
echo "🤖 检查 Embedding 模型..."

MODEL_DIR="config/models"
mkdir -p "$MODEL_DIR"

# 检查模型是否已存在
if [ -d "$MODEL_DIR/bge-base-zh-v1.5" ] && [ -d "$MODEL_DIR/bge-small-en-v1.5" ]; then
    echo "   ✅ 模型已存在，跳过下载"
else
    echo "   ⏳ 下载模型（约 200MB，首次需要）..."
    echo "      - BAAI/bge-base-zh-v1.5 (768维，中文文档)"
    echo "      - BAAI/bge-small-en-v1.5 (384维，英文代码)"
    echo ""
    
    # 使用 huggingface-hub 下载
    pip install huggingface-hub > /dev/null 2>&1
    
    python3 -c "
from huggingface_hub import snapshot_download
import os

model_dir = '$MODEL_DIR'

# 下载 bge-base-zh-v1.5
print('   📥 下载 BAAI/bge-base-zh-v1.5...')
snapshot_download(
    repo_id='BAAI/bge-base-zh-v1.5',
    local_dir=os.path.join(model_dir, 'bge-base-zh-v1.5'),
    local_dir_use_symlinks=False
)

# 下载 bge-small-en-v1.5
print('   📥 下载 BAAI/bge-small-en-v1.5...')
snapshot_download(
    repo_id='BAAI/bge-small-en-v1.5',
    local_dir=os.path.join(model_dir, 'bge-small-en-v1.5'),
    local_dir_use_symlinks=False
)

print('   ✅ 模型下载完成')
"
fi

# ========== 创建 .env（如果不存在）==========
echo ""
echo "⚙️  检查配置文件..."

if [ ! -f "backend/.env" ]; then
    cat > backend/.env << 'EOF'
# LLM 配置（问答功能需要）
# 以下为示例，按需修改
LLM_PROVIDER=openai
LLM_API_KEY=your-api-key-here
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-3.5-turbo

# 小米 MiMo 配置（可选）
# LLM_PROVIDER=xiaomi
# LLM_API_KEY=your-mimo-key
# LLM_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1
# LLM_MODEL=mimo-v2.5-pro
EOF
    echo "   ⚠️  已创建 backend/.env，请编辑填入 LLM API Key"
    echo "      文件位置: $PROJECT_DIR/backend/.env"
else
    echo "   ✅ backend/.env 已存在"
fi

# ========== 启动服务 ==========
echo ""
echo "🚀 启动服务..."
echo "   访问地址: http://localhost:$PORT"
echo ""
echo "   功能说明："
echo "   - 📄 文档管理: 上传 PDF/TXT/MD/DOCX，自动分块建立向量索引"
echo "   - 📧 邮件导入: 从 SQLite 邮件库导入到向量库"
echo "   - 🔍 代码知识库: 扫描代码仓库，支持混合搜索和调用链追踪"
echo "   - 💬 RAG 问答: 基于知识库的智能问答"
echo "   - 🔧 MCP 服务: 暴露 AI 工具能力"
echo ""
echo "   按 Ctrl+C 停止服务"
echo ""

# 切换到 backend 目录并启动
cd backend
python3 -m uvicorn main:app --reload --host 0.0.0.0 --port "$PORT"
