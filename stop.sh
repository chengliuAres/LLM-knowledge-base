#!/bin/bash
# 停止脚本 — 文档知识库
# 用法: ./stop.sh [端口号，默认8000]

set -e

cd "$(dirname "$0")"

PORT=${1:-8000}
PID_FILE=".start.pid"

echo "=========================================="
echo "  文档知识库 v2.0 — 停止服务"
echo "=========================================="
echo ""

killed=0

# 优先：按 PID 文件记录的进程
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE" 2>/dev/null || true)
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        echo "🛑 优雅停止进程 $PID ..."
        kill "$PID" 2>/dev/null || true
        # 等最多 5 秒让它自己退出
        for i in 1 2 3 4 5; do
            if ! kill -0 "$PID" 2>/dev/null; then
                break
            fi
            sleep 1
        done
        if kill -0 "$PID" 2>/dev/null; then
            echo "💀 进程未响应，强杀 $PID"
            kill -9 "$PID" 2>/dev/null || true
        fi
        killed=1
    fi
    rm -f "$PID_FILE"
fi

# 兜底：清理占用 8000 端口的所有进程（处理脚本异常退出无 PID 文件的情况）
if command -v lsof &> /dev/null; then
    PIDS=$(lsof -ti tcp:"$PORT" 2>/dev/null || true)
elif command -v fuser &> /dev/null; then
    PIDS=$(fuser "$PORT"/tcp 2>/dev/null | tr -s ' ' '\n' | grep -v '^$' || true)
else
    PIDS=""
fi

if [ -n "$PIDS" ]; then
    echo "🧹 清理端口 $PORT 残留进程: $PIDS"
    kill $PIDS 2>/dev/null || true
    sleep 1
    kill -9 $PIDS 2>/dev/null || true
    killed=1
fi

# 兜底兜底：再扫一遍 uvicorn/python main 进程
EXTRA=$(pgrep -f "uvicorn main:app" || true)
if [ -n "$EXTRA" ]; then
    echo "🧹 清理 uvicorn 残留: $EXTRA"
    kill $EXTRA 2>/dev/null || true
    sleep 1
    kill -9 $EXTRA 2>/dev/null || true
    killed=1
fi

if [ "$killed" -eq 1 ]; then
    echo "✅ 服务已停止"
else
    echo "ℹ️  没有运行中的服务"
fi
