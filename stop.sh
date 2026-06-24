#!/bin/bash
# 停止脚本 — 文档知识库
# 用法: 
#   ./stop.sh        # 停止所有本项目服务
#   ./stop.sh 8001   # 只停止 8001 端口的服务

set -e

cd "$(dirname "$0")"

PORT=$1
PID_FILE=".start.pid"

echo "=========================================="
echo "  文档知识库 v2.0 — 停止服务"
echo "=========================================="
echo ""

killed=0

# 优雅停止一个进程
kill_process() {
    local pid=$1
    local desc=$2
    
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        echo "🛑 停止 $desc (PID: $pid)..."
        kill "$pid" 2>/dev/null || true
        # 等最多 3 秒
        for i in 1 2 3; do
            if ! kill -0 "$pid" 2>/dev/null; then
                break
            fi
            sleep 1
        done
        if kill -0 "$pid" 2>/dev/null; then
            echo "   💀 强制停止 $pid"
            kill -9 "$pid" 2>/dev/null || true
        fi
        killed=1
    fi
}

# 清理 PID 文件记录的进程
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null || true)
    if [ -n "$OLD_PID" ]; then
        kill_process "$OLD_PID" "PID 文件记录的进程"
    fi
    rm -f "$PID_FILE"
fi

if [ -n "$PORT" ]; then
    # 传参模式：只停止指定端口
    echo "🔍 查找端口 $PORT 的服务..."
    
    if command -v lsof &> /dev/null; then
        PIDS=$(lsof -ti tcp:"$PORT" 2>/dev/null || true)
    else
        PIDS=""
    fi
    
    for pid in $PIDS; do
        kill_process "$pid" "端口 $PORT"
    done
else
    # 无参模式：停止所有本项目服务
    echo "🔍 查找所有本项目服务..."
    
    # 查找所有 uvicorn main:app 进程
    PIDS=$(pgrep -f "uvicorn main:app" 2>/dev/null || true)
    
    if [ -n "$PIDS" ]; then
        for pid in $PIDS; do
            kill_process "$pid" "uvicorn main:app"
        done
    fi
fi

if [ "$killed" -eq 1 ]; then
    echo ""
    echo "✅ 服务已停止"
else
    echo "ℹ️  没有找到运行中的服务"
fi
