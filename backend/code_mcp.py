"""MCP Server — 代码知识库 AI 工具 (SSE 传输)

手动实现 MCP JSON-RPC 2.0 over SSE 协议, 不依赖 mcp SDK (兼容 Python 3.9+)。

暴露 4 个 tools:
- code_search: 搜索代码库
- code_chat: RAG 代码问答
- code_list_repos: 列出已索引仓库
- code_file_context: 获取文件上下文
"""

import os
import json
import uuid
import asyncio
from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

router = APIRouter(tags=["mcp"])

# ── MCP 工具定义 ─────────────────────────────────────────────────

TOOLS = [
    {
        "name": "code_search",
        "description": "搜索代码库, 支持语义搜索和关键词搜索",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索内容"},
                "repo": {"type": "string", "description": "仓库名过滤 (可选)"},
                "language": {"type": "string", "description": "语言过滤 (可选)"},
                "symbol": {"type": "string", "description": "符号名精确匹配 (可选)"},
                "mode": {"type": "string", "enum": ["hybrid", "vector", "keyword"], "default": "hybrid"},
                "top_k": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100},
            },
            "required": ["query"],
        },
    },
    {
        "name": "code_chat",
        "description": "基于代码知识库的 RAG 问答",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "问题"},
                "repo": {"type": "string", "description": "仓库名过滤 (可选)"},
                "language": {"type": "string", "description": "语言过滤 (可选)"},
            },
            "required": ["question"],
        },
    },
    {
        "name": "code_list_repos",
        "description": "列出已索引的代码仓库",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "code_file_context",
        "description": "获取某个文件的上下文内容",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "仓库名"},
                "file_path": {"type": "string", "description": "文件相对路径"},
                "line_start": {"type": "integer", "description": "起始行 (可选)"},
                "line_end": {"type": "integer", "description": "结束行 (可选)"},
            },
            "required": ["repo", "file_path"],
        },
    },
]


# ── 工具执行 ─────────────────────────────────────────────────────

async def execute_tool(name: str, arguments: dict) -> dict:
    """执行 MCP tool, 返回结果"""
    from code_search import search_code
    from code_config import list_repos
    from code_db import get_chunks_by_file

    if name == "code_search":
        result = search_code(
            query=arguments["query"],
            mode=arguments.get("mode", "hybrid"),
            top_k=arguments.get("top_k", 10),
            repo_name=arguments.get("repo"),
            language=arguments.get("language"),
            symbol_name=arguments.get("symbol"),
        )
        # 精简返回 (去掉 vector 等大字段)
        for r in result["results"]:
            r.pop("vector", None)
            r.pop("metadata", None)
        return {"results": result["results"], "mode": result["mode"], "count": len(result["results"])}

    elif name == "code_chat":
        from llm_client import get_llm_client
        client = get_llm_client()
        if not client:
            return {"error": "LLM 未配置, 无法进行问答"}

        search_result = search_code(
            query=arguments["question"],
            mode="hybrid",
            top_k=5,
            repo_name=arguments.get("repo"),
            language=arguments.get("language"),
        )

        sources = search_result["results"]
        if not sources:
            return {"answer": "未找到相关代码片段", "sources": []}

        context_parts = []
        for i, s in enumerate(sources, 1):
            ctx = f"[{i}] {s['file_path']}:{s['line_start']}-{s['line_end']} ({s['symbol_name']})\n```\n{s['content']}\n```"
            context_parts.append(ctx)

        context = "\n\n".join(context_parts)
        messages = [
            {"role": "system", "content": "你是代码助手, 基于检索到的代码片段回答问题。回答时引用具体的文件路径和行号。"},
            {"role": "user", "content": f"代码片段:\n{context}\n\n问题: {arguments['question']}"},
        ]

        answer = await client.chat(messages, stream=False)
        return {
            "answer": answer,
            "sources": [{"file_path": s["file_path"], "symbol_name": s["symbol_name"],
                         "line_start": s["line_start"], "line_end": s["line_end"]} for s in sources],
        }

    elif name == "code_list_repos":
        return {"repos": list_repos()}

    elif name == "code_file_context":
        repo = arguments["repo"]
        file_path = arguments["file_path"]
        line_start = arguments.get("line_start")
        line_end = arguments.get("line_end")

        chunks = get_chunks_by_file(repo, file_path)
        if not chunks:
            return {"error": f"文件不存在: {repo}/{file_path}"}

        # 拼接文件内容
        content = "\n".join(c["content"] for c in chunks)

        # 行号范围过滤
        if line_start is not None and line_end is not None:
            lines = content.split("\n")
            # 前后各 10 行上下文
            start = max(0, line_start - 11)
            end = min(len(lines), line_end + 10)
            content = "\n".join(lines[start:end])

        # 截断到 5000 字符
        truncated = len(content) > 5000
        if truncated:
            content = content[:5000]

        return {
            "repo": repo,
            "file_path": file_path,
            "content": content,
            "total_chunks": len(chunks),
            "truncated": truncated,
        }

    return {"error": f"未知工具: {name}"}


# ── JSON-RPC 处理 ────────────────────────────────────────────────

SERVER_INFO = {
    "name": "code-knowledge-base",
    "version": "1.0.0",
}

CAPABILITIES = {
    "tools": {},
}


def handle_jsonrpc(request: dict) -> Optional[dict]:
    """处理 JSON-RPC 2.0 请求, 返回响应 (同步部分)"""
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": CAPABILITIES,
                "serverInfo": SERVER_INFO,
            },
        }

    elif method == "notifications/initialized":
        return None  # 通知不需要响应

    elif method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS},
        }

    elif method == "tools/call":
        # 异步执行, 返回 None (结果通过 SSE 发送)
        return None

    else:
        if req_id is not None:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        return None


# ── SSE 连接管理 ─────────────────────────────────────────────────

# session_id → asyncio.Queue
_sessions: dict[str, asyncio.Queue] = {}


# ── MCP SSE 端点 ─────────────────────────────────────────────────

@router.get("/mcp/sse")
async def mcp_sse(request: Request):
    """MCP SSE 传输端点 — 客户端连接此端点接收事件"""
    session_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    _sessions[session_id] = queue

    # 发送 endpoint 事件 (告诉客户端消息发送地址)
    message_url = f"/mcp/message?session_id={session_id}"

    async def event_generator():
        try:
            # 首次连接: 发送 endpoint
            yield {"event": "endpoint", "data": message_url}

            # 持续发送队列中的消息
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30)
                    yield {"event": "message", "data": json.dumps(data, ensure_ascii=False)}
                except asyncio.TimeoutError:
                    # 心跳
                    yield {"event": "ping", "data": ""}
                except asyncio.CancelledError:
                    break
        finally:
            _sessions.pop(session_id, None)

    return EventSourceResponse(event_generator())


@router.post("/mcp/message")
async def mcp_message(request: Request, session_id: str = ""):
    """MCP 消息端点 — 客户端发送 JSON-RPC 请求"""
    if session_id not in _sessions:
        raise HTTPException(404, detail="Session not found")

    body = await request.json()
    queue = _sessions[session_id]

    # 处理 JSON-RPC
    response = handle_jsonrpc(body)

    if body.get("method") == "tools/call":
        # 异步执行工具
        tool_name = body["params"].get("name", "")
        tool_args = body["params"].get("arguments", {})
        req_id = body.get("id")

        try:
            result = await execute_tool(tool_name, tool_args)
            await queue.put({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
                },
            })
        except Exception as e:
            await queue.put({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"错误: {str(e)}"}],
                    "isError": True,
                },
            })
    elif response is not None:
        await queue.put(response)

    return JSONResponse({"status": "ok"})
