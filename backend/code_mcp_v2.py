"""MCP Server v2 — 代码知识库 AI 工具 (官方 mcp SDK, Streamable HTTP)

基于 mcp SDK v1.x, 使用 FastMCP + streamable_http_app 挂载到 FastAPI。

暴露 5 个 tools:
- code_search: 搜索代码库
- code_chat: RAG 代码问答 (非流式, stream=False)
- code_list_repos: 列出已索引仓库
- code_file_context: 获取文件上下文
- code_trace: 调用链追踪
"""

from mcp.server.fastmcp import FastMCP

# 创建 MCP server（stateless + json_response）
mcp = FastMCP("CodeKB", stateless_http=True, json_response=True)
# 设置 endpoint 路径为 /，这样 Mount("/mcp") 后客户端连 http://host/mcp
mcp.settings.streamable_http_path = "/"


@mcp.tool()
async def code_search(
    query: str,
    repo: str = "",
    language: str = "",
    symbol: str = "",
    mode: str = "hybrid",
    top_k: int = 10,
) -> str:
    """搜索代码库，支持语义搜索和关键词搜索"""
    import json
    from code_search import search_code
    from code_config import is_repo_scanning

    if repo and is_repo_scanning(repo):
        return f"⚠️ {repo} 代码索引正在更新中，请稍后再试。"

    query = query.strip()
    if not query:
        return json.dumps({"error": "query 不能为空"}, ensure_ascii=False)

    result = search_code(
        query=query,
        mode=mode,
        top_k=min(max(top_k, 1), 100),
        repo_name=repo or None,
        language=language or None,
        symbol_name=symbol or None,
    )
    # 精简返回（去掉 vector/metadata 大字段）
    for r in result["results"]:
        r.pop("vector", None)
        r.pop("metadata", None)
    return json.dumps({
        "results": result["results"],
        "mode": result["mode"],
        "count": len(result["results"]),
    }, ensure_ascii=False, indent=2)


@mcp.tool()
async def code_chat(
    question: str,
    repo: str = "",
    language: str = "",
) -> str:
    """基于代码知识库的 RAG 问答"""
    import json
    from code_search import search_code
    from llm_client import get_llm_client
    from code_config import is_repo_scanning

    if repo and is_repo_scanning(repo):
        return f"⚠️ {repo} 代码索引正在更新中，请稍后再试。"

    question = question.strip()
    if not question:
        return json.dumps({"error": "question 不能为空"}, ensure_ascii=False)

    client = get_llm_client()
    if not client:
        return json.dumps({"error": "LLM 未配置，无法进行问答"}, ensure_ascii=False)

    search_result = search_code(
        query=question,
        mode="hybrid",
        top_k=5,
        repo_name=repo or None,
        language=language or None,
    )

    sources = search_result["results"]
    if not sources:
        return json.dumps({"answer": "未找到相关代码片段", "sources": []}, ensure_ascii=False)

    context_parts = []
    for i, s in enumerate(sources, 1):
        ctx = f"[{i}] {s['file_path']}:{s['line_start']}-{s['line_end']} ({s['symbol_name']})\n```\n{s['content']}\n```"
        context_parts.append(ctx)

    context = "\n\n".join(context_parts)
    messages = [
        {"role": "system", "content": "你是代码助手，基于检索到的代码片段回答问题。回答时引用具体的文件路径和行号。"},
        {"role": "user", "content": f"代码片段:\n{context}\n\n问题: {question}"},
    ]

    answer = await client.chat(messages, stream=False)

    return json.dumps({
        "answer": answer,
        "sources": [{"file_path": s["file_path"], "symbol_name": s["symbol_name"],
                     "line_start": s["line_start"], "line_end": s["line_end"]} for s in sources],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
async def code_list_repos() -> str:
    """列出已索引的代码仓库"""
    import json
    from code_config import list_repos
    return json.dumps({"repos": list_repos()}, ensure_ascii=False, indent=2)


@mcp.tool()
async def code_file_context(
    repo: str,
    file_name: str,
    line_start: int = 0,
    line_end: int = 0,
) -> str:
    """按文件名获取文件内容（v2.1 改造：原 file_path 入口已废弃）

    - 唯一命中：直接返回 content
    - 多匹配（如 Pods/ 下几百个同名 .hpp）：返回 candidates 列表让 AI 挑
    - 无匹配：返回 error
    """
    import json
    from code_db import resolve_file_by_name, get_chunks_by_file
    from code_config import is_repo_scanning

    if repo and is_repo_scanning(repo):
        return f"⚠️ {repo} 代码索引正在更新中，请稍后再试。"

    matches = resolve_file_by_name(repo, file_name)
    if not matches:
        return json.dumps(
            {"error": f"仓库 {repo} 中找不到文件: {file_name}",
             "hint": "用 code_search 先定位文件路径，再传 file_name"},
            ensure_ascii=False, indent=2,
        )

    if len(matches) > 1:
        return json.dumps({
            "error": f"文件 {file_name} 在 {repo} 中有 {len(matches)} 个匹配",
            "hint": "请用 code_search 精确定位，或从 candidates 中挑一个再调用",
            "candidates": matches[:20],  # 限 20 防爆
        }, ensure_ascii=False, indent=2)

    # 唯一命中：取 file_path 走原有逻辑
    file_path = matches[0]["file_path"]
    chunks = get_chunks_by_file(repo, file_path)
    if not chunks:
        return json.dumps({"error": f"文件元数据找到但 chunk 为空: {file_path}"},
                          ensure_ascii=False, indent=2)

    content = "\n".join(c["content"] for c in chunks)

    if line_start > 0 and line_end > 0:
        lines = content.split("\n")
        start = max(0, line_start - 11)
        end = min(len(lines), line_end + 10)
        content = "\n".join(lines[start:end])

    truncated = len(content) > 5000
    if truncated:
        content = content[:5000]

    return json.dumps({
        "repo": repo,
        "file_name": file_name,
        "file_path": file_path,
        "content": content,
        "total_chunks": len(chunks),
        "truncated": truncated,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
async def code_trace(
    symbol: str,
    repo: str = "",
    direction: str = "both",
    depth: int = 2,
) -> str:
    """追踪符号的调用链：谁调用了它 / 它调用了谁"""
    import json
    from code_search import trace_code
    from code_config import is_repo_scanning

    if repo and is_repo_scanning(repo):
        return f"⚠️ {repo} 代码索引正在更新中，请稍后再试。"

    symbol = symbol.strip()
    if not symbol:
        return json.dumps({"error": "symbol 不能为空"}, ensure_ascii=False)

    result = trace_code(
        symbol_name=symbol,
        repo_name=repo or "",
        direction=direction,
        depth=min(max(depth, 1), 5),  # hierarchy 允许更深的链（最多 5）
    )
    result.pop("steps", None)
    return json.dumps(result, ensure_ascii=False, indent=2)
