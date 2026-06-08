"""代码知识库 REST API 路由"""

import os
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from step_tracker import StepTracker
from code_parser import parse_repo, scan_directory
from code_db import insert_chunks, delete_by_repo, delete_by_file, get_stats, get_chunks_by_file
from code_search import search_code
from code_config import (
    list_repos, get_repo_config, register_repo, remove_repo,
    try_acquire_scan_lock, release_scan_lock, compute_incremental,
    get_file_mtimes, update_file_mtimes,
)

router = APIRouter(prefix="/api/code", tags=["code-kb"])


# ── 请求模型 ─────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    repo_name: str
    repo_path: str
    project_type: str = "generic"
    languages: list[str] = Field(default_factory=list)
    skip_dirs: list[str] = Field(default_factory=list)
    skip_extensions: list[str] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str
    mode: str = "hybrid"  # hybrid / vector / keyword
    top_k: int = 10
    filters: dict = Field(default_factory=dict)


class ChatRequest(BaseModel):
    question: str
    top_k: int = 5
    filters: dict = Field(default_factory=dict)
    stream: bool = False


# ── POST /api/code/scan ──────────────────────────────────────────

@router.post("/scan")
async def scan_repo_endpoint(req: ScanRequest):
    """增量扫描目录, 建立代码索引"""
    repo_path = os.path.abspath(req.repo_path)
    if not os.path.isdir(repo_path):
        raise HTTPException(400, detail=f"目录不存在: {repo_path}")

    # 并发锁
    if not try_acquire_scan_lock(req.repo_name):
        raise HTTPException(409, detail=f"仓库 {req.repo_name} 正在扫描中")

    tracker = StepTracker(operation_type="code_scan")
    try:
        # 1. 扫描文件
        step = tracker.add_step("scan_files", "扫描目录文件")
        step.start()
        files = scan_directory(
            repo_path, req.project_type,
            req.languages or None,
            set(req.skip_dirs) if req.skip_dirs else None,
            set(req.skip_extensions) if req.skip_extensions else None,
        )
        step.complete({"total_files": len(files)})

        # 2. 计算增量
        step = tracker.add_step("compute_diff", "计算增量差异")
        step.start()
        incremental = compute_incremental(req.repo_name, files)
        step.complete({
            "added": len(incremental["added"]),
            "updated": len(incremental["updated"]),
            "deleted": len(incremental["deleted"]),
            "skipped": len(incremental["skipped"]),
        })

        # 3. 处理删除的文件
        if incremental["deleted"]:
            step = tracker.add_step("delete_removed", "删除已移除文件的索引")
            step.start()
            for rel_path in incremental["deleted"]:
                delete_by_file(req.repo_name, rel_path)
            step.complete({"deleted_files": len(incremental["deleted"])})

        # 4. 解析新增/修改的文件
        files_to_parse = incremental["added"] + incremental["updated"]
        all_chunks = []
        parse_warnings = 0

        if files_to_parse:
            step = tracker.add_step("parse_files", f"解析 {len(files_to_parse)} 个文件")
            step.start()

            # 删除更新文件的旧 chunks
            for f in incremental["updated"]:
                delete_by_file(req.repo_name, f["rel_path"])

            # 逐文件解析
            from code_parser import chunk_code, pair_header_impl
            from embedder import embed_batch

            pairs = pair_header_impl(files_to_parse)
            batch_texts = []
            batch_chunks = []

            for f in files_to_parse:
                try:
                    with open(f["path"], "rb") as fh:
                        code_bytes = fh.read()
                except (OSError, PermissionError):
                    continue
                if not code_bytes.strip():
                    continue

                paired = pairs.get(f["rel_path"], "")
                chunks = chunk_code(
                    code_bytes, f["language"], f["rel_path"],
                    req.repo_name, req.project_type, repo_path, paired or "",
                )

                for c in chunks:
                    if c["metadata"].get("parse_warning"):
                        parse_warnings += 1
                    batch_texts.append(c["content"])
                    batch_chunks.append(c)

            step.complete({"parsed_chunks": len(batch_chunks), "parse_warnings": parse_warnings})

            # 5. 批量 embedding
            if batch_chunks:
                step = tracker.add_step("embedding", f"向量化 {len(batch_chunks)} 个 chunks")
                step.start()

                # 分批 embedding (每批 64)
                BATCH = 64
                for i in range(0, len(batch_texts), BATCH):
                    batch_t = batch_texts[i:i+BATCH]
                    vectors = embed_batch(batch_t)
                    for j, v in enumerate(vectors):
                        batch_chunks[i+j]["vector"] = v

                step.complete({"embedded": len(batch_chunks)})

                # 6. 双写入库
                step = tracker.add_step("store", "写入 LanceDB + SQLite")
                step.start()
                insert_chunks(batch_chunks)
                step.complete({"stored": len(batch_chunks)})

                all_chunks = batch_chunks

        # 7. 更新配置
        step = tracker.add_step("update_config", "更新仓库配置")
        step.start()

        # 从 DB 获取真实统计 (避免增量扫描虚增)
        from code_db import get_stats as get_code_stats
        db_stats = get_code_stats()
        total_stats = {
            "total_files": len(files),
            "total_chunks": db_stats.get("total_chunks", 0),
            "by_language": db_stats.get("by_language", {}),
            "by_chunk_type": db_stats.get("by_chunk_type", {}),
        }

        register_repo(req.repo_name, repo_path, req.project_type, req.languages, total_stats)

        # 更新 mtime 记录
        new_mtimes = {f["rel_path"]: f["mtime"] for f in files}
        update_file_mtimes(req.repo_name, new_mtimes)

        step.complete()

        tracker.flush()

        return {
            "status": "ok",
            "repo_name": req.repo_name,
            "total_files": len(files),
            "total_chunks": len(all_chunks),
            "by_language": total_stats["by_language"],
            "by_chunk_type": total_stats["by_chunk_type"],
            "parse_warnings": parse_warnings,
            "incremental": {
                "added": len(incremental["added"]),
                "updated": len(incremental["updated"]),
                "deleted": len(incremental["deleted"]),
                "skipped": len(incremental["skipped"]),
            },
            "elapsed_seconds": round(tracker.get_total_duration() / 1000, 2),
            "steps": tracker.to_list(),
        }

    except HTTPException:
        raise
    except Exception as e:
        tracker.flush(status="error")
        raise HTTPException(500, detail=str(e))
    finally:
        release_scan_lock(req.repo_name)


# ── POST /api/code/search ────────────────────────────────────────

@router.post("/search")
async def search_endpoint(req: SearchRequest):
    """混合搜索代码"""
    if not req.query.strip():
        raise HTTPException(400, detail="query 不能为空")

    tracker = StepTracker(operation_type="code_search")
    try:
        filters = req.filters or {}
        result = search_code(
            query=req.query,
            mode=req.mode,
            top_k=req.top_k,
            repo_name=filters.get("repo_name"),
            project_type=filters.get("project_type"),
            language=filters.get("language"),
            chunk_type=filters.get("chunk_type"),
            file_path=filters.get("file_path"),
            symbol_name=filters.get("symbol_name"),
            tracker=tracker,
        )
        tracker.flush()
        result["steps"] = tracker.to_list()
        return result
    except Exception as e:
        tracker.flush(status="error")
        raise HTTPException(500, detail=str(e))


# ── POST /api/code/chat ──────────────────────────────────────────

@router.post("/chat")
async def chat_endpoint(req: ChatRequest):
    """RAG 代码问答"""
    from llm_client import get_llm_client, build_rag_prompt

    client = get_llm_client()
    if not client:
        raise HTTPException(503, detail="LLM 未配置, 无法进行问答")

    tracker = StepTracker(operation_type="code_chat")
    try:
        filters = req.filters or {}

        # 1. 搜索相关代码
        search_result = search_code(
            query=req.question,
            mode="hybrid",
            top_k=req.top_k,
            repo_name=filters.get("repo_name"),
            language=filters.get("language"),
            tracker=tracker,
        )

        sources = search_result["results"]
        if not sources:
            return {
                "question": req.question,
                "answer": "未找到相关代码片段, 请尝试换个关键词。",
                "sources": [],
                "steps": tracker.to_list(),
            }

        # 2. 构造 RAG prompt
        context_parts = []
        for i, s in enumerate(sources, 1):
            ctx = f"[{i}] {s['file_path']}:{s['line_start']}-{s['line_end']} ({s['symbol_name']})\n```\n{s['content']}\n```"
            context_parts.append(ctx)

        context = "\n\n".join(context_parts)

        step = tracker.add_step("llm_generate", "LLM 生成回答")
        step.start()

        system_prompt = (
            "你是代码助手, 基于检索到的代码片段回答问题。"
            "回答时引用具体的文件路径和行号。"
            "如果代码片段不足以回答, 明确告知。"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"代码片段:\n{context}\n\n问题: {req.question}"},
        ]

        if req.stream:
            async def stream_gen():
                import json
                yield f"data: {json.dumps({'type': 'steps', 'data': tracker.to_list()})}\n\n"

                full_answer = ""
                async for chunk in await client.chat(messages, stream=True):
                    full_answer += chunk
                    yield f"data: {json.dumps({'type': 'content', 'data': chunk})}\n\n"

                yield f"data: {json.dumps({'type': 'sources', 'data': [{'file_path': s['file_path'], 'symbol_name': s['symbol_name'], 'line_start': s['line_start'], 'line_end': s['line_end']} for s in sources]})}\n\n"
                yield "data: [DONE]\n\n"

                step.complete({"answer_length": len(full_answer)})
                tracker.flush()

            return StreamingResponse(stream_gen(), media_type="text/event-stream")

        answer = await client.chat(messages, stream=False)
        step.complete({"answer_length": len(answer)})

        tracker.flush()
        return {
            "question": req.question,
            "answer": answer,
            "sources": [{
                "file_path": s["file_path"],
                "symbol_name": s["symbol_name"],
                "line_start": s["line_start"],
                "line_end": s["line_end"],
                "score": s.get("score", 0),
            } for s in sources],
            "steps": tracker.to_list(),
        }

    except Exception as e:
        tracker.flush(status="error")
        raise HTTPException(500, detail=str(e))


# ── GET /api/code/repos ──────────────────────────────────────────

@router.get("/repos")
async def list_repos_endpoint():
    """已索引的仓库列表"""
    return {"repos": list_repos()}


# ── GET /api/code/stats ──────────────────────────────────────────

@router.get("/stats")
async def stats_endpoint():
    """索引统计信息"""
    return get_stats()


# ── DELETE /api/code/repos/{name} ────────────────────────────────

@router.delete("/repos/{name}")
async def delete_repo_endpoint(name: str):
    """删除仓库索引"""
    if not get_repo_config(name):
        raise HTTPException(404, detail=f"仓库 {name} 不存在")

    deleted = delete_by_repo(name)
    remove_repo(name)

    return {
        "status": "ok",
        "deleted_chunks": deleted,
        "repo_name": name,
    }


# ── POST /api/code/repos/{name}/refresh ──────────────────────────

@router.post("/repos/{name}/refresh")
async def refresh_repo_endpoint(name: str):
    """全量刷新仓库索引 (幂等)"""
    repo_config = get_repo_config(name)
    if not repo_config:
        raise HTTPException(404, detail=f"仓库 {name} 不存在")

    # 清空旧数据
    delete_by_repo(name)

    # 复用 scan 接口的逻辑
    req = ScanRequest(
        repo_name=name,
        repo_path=repo_config["repo_path"],
        project_type=repo_config.get("project_type", "generic"),
        languages=repo_config.get("languages", []),
    )

    # 直接调用 scan endpoint 逻辑 (不经过 HTTP)
    return await scan_repo_endpoint(req)


# ── GET /api/code/browse ─────────────────────────────────────────

@router.get("/browse")
async def browse_directory(path: str = "/"):
    """列出指定路径下的子目录 (用于前端文件夹浏览)"""
    path = os.path.abspath(path)

    if not os.path.isdir(path):
        raise HTTPException(400, detail=f"目录不存在: {path}")

    try:
        entries = sorted(os.listdir(path))
    except PermissionError:
        raise HTTPException(403, detail=f"无权限访问: {path}")

    dirs = []
    for name in entries:
        if name.startswith('.'):
            continue
        full = os.path.join(path, name)
        if os.path.isdir(full):
            dirs.append({"name": name, "path": full})

    return {
        "current": path,
        "parent": os.path.dirname(path) if path != "/" else None,
        "dirs": dirs,
    }
