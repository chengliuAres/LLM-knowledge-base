#!/bin/bash
# 启动脚本

cd "$(dirname "$0")"

echo "=========================================="
echo "  文档知识库 Demo v2.0"
echo "=========================================="
echo ""

# 检查 Python 环境
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到 python3，请先安装 Python 3.9+"
    exit 1
fi

# 安装依赖（如果需要）
if [ ! -d "backend/venv" ]; then
    echo "📦 正在创建虚拟环境并安装依赖..."
    cd backend
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    cd ..
else
    source backend/venv/bin/activate
fi

# 检查是否需要安装 openai
pip show openai > /dev/null 2>&1 || pip install openai

echo ""
echo "🚀 启动服务..."
echo "   访问地址: http://localhost:8000"
echo ""
echo "   功能说明："
echo "   - 📄 文档管理: 上传文档并建立索引"
echo "   - 📧 邮件导入: 从邮件DB导入数据"
echo "   - 💬 智能问答: 基于知识库的RAG问答"
echo ""
echo "   按 Ctrl+C 停止"
echo ""

cd backend
python3 -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
