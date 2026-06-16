#!/bin/bash
# 启动脚本 — 文档知识库 v2.0
# 用法: ./start.sh [端口号，默认8000]

set -e

cd "$(dirname "$0")"

PORT=${1:-8000}
PID_FILE=".start.pid"

echo "=========================================="
echo "  文档知识库 v2.0"
echo "=========================================="
echo ""

# 检查 Python 环境
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到 python3，请先安装 Python 3.9+"
    exit 1
fi

# 创建/激活虚拟环境
if [ ! -d "backend/venv" ]; then
    echo "📦 正在创建虚拟环境并安装依赖..."
    cd backend
    python3 -m venv venv
    # shellcheck disable=SC1091
    source venv/bin/activate
    pip install --upgrade pip > /dev/null
    pip install -r requirements.txt
    cd ..
else
    # shellcheck disable=SC1091
    source backend/venv/bin/activate
fi

# 检查依赖文件
if [ ! -f "backend/requirements.txt" ]; then
    echo "❌ 未找到 backend/requirements.txt"
    exit 1
fi

# 检查 openai（问答功能依赖）
pip show openai > /dev/null 2>&1 || pip install openai

# 清理占用端口的旧进程（解决 "Address already in use"）
kill_port() {
    local port=$1
    # lsof 优先（macOS/Linux 都有），fallback fuser
    if command -v lsof &> /dev/null; then
        local pids
        pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
    elif command -v fuser &> /dev/null; then
        local pids
        pids=$(fuser "$port"/tcp 2>/dev/null | tr -s ' ' '\n' | grep -v '^$' || true)
    else
        local pids=""
    fi

    if [ -n "$pids" ]; then
        echo "🧹 清理占用端口 $port 的旧进程: $pids"
        # 先优雅终止，超时再强杀
        kill $pids 2>/dev/null || true
        sleep 1
        kill -9 $pids 2>/dev/null || true
    fi
}

# 清理上一次记录的 PID（防 Ctrl+C 后残留）
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null || true)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "🧹 清理上一次的进程: $OLD_PID"
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
        kill -9 "$OLD_PID" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
fi

kill_port "$PORT"

# 优雅退出：Ctrl+C 时杀 uvicorn 子进程
cleanup() {
    echo ""
    echo "👋 正在停止服务..."
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE" 2>/dev/null || true)
        if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
            kill "$PID" 2>/dev/null || true
            sleep 1
            kill -9 "$PID" 2>/dev/null || true
        fi
        rm -f "$PID_FILE"
    fi
    exit 0
}
trap cleanup INT TERM EXIT

echo ""
# HTTPS 支持：存在 cert.pem/key.pem 时自动启用（Chrome 148 PNA 需要）
SSL_ARGS=""
SCHEME="http"
if [ -f "cert.pem" ] && [ -f "key.pem" ]; then
    SSL_ARGS="--ssl-keyfile=$PWD/key.pem --ssl-certfile=$PWD/cert.pem"
    SCHEME="https"
    echo "🔒 检测到 SSL 证书，启用 HTTPS"
    echo "   ⚠️  首次访问浏览器会提示不安全，点\"继续访问\"即可"
    echo ""
else
    echo "🔑 正在生成自签 SSL 证书（Chrome 148 PNA 需要 HTTPS）..."
    openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=10.242.15.251" 2>/dev/null
    SSL_ARGS="--ssl-keyfile=$PWD/key.pem --ssl-certfile=$PWD/cert.pem"
    SCHEME="https"
    echo "🔒 证书已生成，启用 HTTPS"
    echo "   ⚠️  首次访问浏览器会提示不安全，点\"继续访问\"即可"
    echo ""
fi

echo "🚀 启动服务..."
echo "   访问地址: ${SCHEME}://localhost:$PORT"
echo ""
echo "   功能说明："
echo "   - 📄 文档管理: 上传文档并建立索引"
echo "   - 📧 邮件导入: 从邮件DB导入数据"
echo "   - 💬 智能问答: 基于知识库的RAG问答"
echo ""
echo "   按 Ctrl+C 停止"
echo ""

cd backend
python3 -m uvicorn main:app --reload --host 0.0.0.0 --port "$PORT" $SSL_ARGS &
SERVER_PID=$!
echo "$SERVER_PID" > "../$PID_FILE"

# 等待子进程退出（让 trap 能接收到信号）
wait "$SERVER_PID"
