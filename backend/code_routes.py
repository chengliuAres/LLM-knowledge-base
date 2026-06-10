"""代码知识库 REST API 路由"""

import os
import math
import uuid
import logging
import platform
import subprocess
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException

log = logging.getLogger("code_kb")
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from step_tracker import StepTracker
from code_parser import parse_repo, scan_directory
from code_db import insert_chunks, delete_by_repo, delete_by_file, get_stats
from code_skip_rules import get_skip_rules, save_skip_rules, reset_skip_rules, parse_gitignore_dirs, open_config_in_finder, get_skip_dirs, get_skip_exts
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
    project_type: str = ""  # 空字符串 = 自动检测工程类型
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


class TraceRequest(BaseModel):
    symbol: str = Field(..., min_length=1, description="符号名或搜索查询")
    repo_name: str = ""
    direction: str = "both"  # callers / callees / both
    depth: int = Field(default=2, ge=1, le=3)


class SkipRulesRequest(BaseModel):
    skip_dirs: list[dict] = Field(default_factory=list)
    skip_exts: list[dict] = Field(default_factory=list)
    gitignore_selections: list[dict] = Field(default_factory=list)


# ── 扫描任务管理 ─────────────────────────────────────────────────

import uuid
import threading
import asyncio
import json as _json
from typing import Dict, List

class ScanJob:
    """单个扫描任务的状态管理"""

    def __init__(self, scan_id: str, req: ScanRequest):
        self.scan_id = scan_id
        self.req = req
        self.status = "pending"  # pending / running / completed / cancelled / error
        self.cancel_event = threading.Event()
        self.progress: List[dict] = []  # 步骤列表 (SSE 推送用)
        self.current_step = ""
        self.current_detail = ""
        self.stats = {}
        self.error = ""
        self._written_chunk_ids: List[str] = []  # 本次写入的 chunk id (用于回滚)
        self._old_mtimes: dict = {}  # 扫描前的 mtime 快照 (用于回滚)
        self._subscribers: List[asyncio.Queue] = []  # SSE 订阅者

    def update(self, step: str, detail: str = "", **extra):
        """更新进度并通知所有 SSE 订阅者"""
        self.current_step = step
        self.current_detail = detail
        entry = {"step": step, "detail": detail, **extra}
        self.progress.append(entry)
        # 通知 SSE 订阅者
        for q in list(self._subscribers):
            try:
                q.put_nowait(entry)
            except asyncio.QueueFull:
                pass

    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self._subscribers:
            self._subscribers.remove(q)


# scan_id → ScanJob
_scan_jobs: Dict[str, ScanJob] = {}


# ── 后台扫描线程 ─────────────────────────────────────────────────

def _run_scan(job: ScanJob):
    """在后台线程中执行扫描"""
    req = job.req
    repo_path = os.path.abspath(req.repo_path)
    job.status = "running"
    log.info(f"[scan:{job.scan_id}] 后台线程启动: {req.repo_name}")

    try:
        # 0. 自动检测工程类型
        from code_parser import auto_detect_project_type
        effective_type = req.project_type or auto_detect_project_type(repo_path)

        # 1. 扫描目录
        job.update("scan_files", "扫描目录文件...")
        if job.is_cancelled():
            return
        log.info(f"[scan:{job.scan_id}] 开始扫描目录: {repo_path}, type={effective_type}")
        files = scan_directory(
            repo_path, effective_type,
            req.languages or None,
            set(req.skip_dirs) if req.skip_dirs else None,
            set(req.skip_extensions) if req.skip_extensions else None,
        )
        job.update("scan_files_done", f"发现 {len(files)} 个文件", total_files=len(files))

        # 2. 计算增量
        job.update("compute_diff", "计算增量差异 (比对 mtime)...")
        if job.is_cancelled():
            return
        log.info(f"[scan:{job.scan_id}] 计算增量: {len(files)} files")
        incremental = compute_incremental(req.repo_name, files)
        added_n = len(incremental["added"])
        updated_n = len(incremental["updated"])
        deleted_n = len(incremental["deleted"])
        skipped_n = len(incremental["skipped"])
        job.update("compute_diff_done",
                   f"新增 {added_n} / 更新 {updated_n} / 删除 {deleted_n} / 跳过 {skipped_n}",
                   added=added_n, updated=updated_n, deleted=deleted_n, skipped=skipped_n)

        # 保存 mtime 快照 (用于取消时回滚)
        job._old_mtimes = get_file_mtimes(req.repo_name)

        # 3. 删除已移除文件
        if deleted_n > 0:
            job.update("delete_removed", f"删除 {deleted_n} 个已移除文件的索引...")
            for i, rel_path in enumerate(incremental["deleted"]):
                if job.is_cancelled():
                    return
                delete_by_file(req.repo_name, rel_path)
            job.update("delete_removed_done", f"已删除 {deleted_n} 个文件索引")

        # 4. 解析 + embedding + 写入 (分批)
        files_to_parse = incremental["added"] + incremental["updated"]
        if not files_to_parse:
            job.update("done", "无新增/更新文件，扫描完成")
            _finalize_scan(job, files, effective_type)
            return

        log.info(f"[scan:{job.scan_id}] 解析 {len(files_to_parse)} 个文件...")
        from code_parser import chunk_code, pair_header_impl
        from code_embedder import embed_code_batch

        # 删除更新文件的旧 chunks
        for f in incremental["updated"]:
            if job.is_cancelled():
                return
            delete_by_file(req.repo_name, f["rel_path"])

        pairs = pair_header_impl(files_to_parse)
        total = len(files_to_parse)
        parse_warnings = 0
        total_chunks = 0
        BATCH = 64
        FILE_BATCH = 200  # 每批累积约 200 * 5 = 1000 chunks → embed → 写入

        # 流式处理: 分批解析 → 分批 embedding → 分批写入 (避免全部载入内存)
        batch_chunks = []
        batch_texts = []
        batch_seq = 0  # 批次序号

        def _process_batch():
            """对当前累积的 chunks 做 embedding + 写入，然后清空"""
            nonlocal total_chunks, batch_seq
            if not batch_chunks:
                return

            n = len(batch_chunks)
            batch_seq += 1

            # embedding
            job.update("embedding",
                       f"向量化 第{batch_seq}批 ({n} chunks，累计 {total_chunks + n})",
                       batch=batch_seq, chunks_this_batch=n, chunks_total=total_chunks + n)
            for i in range(0, len(batch_texts), BATCH):
                if job.is_cancelled():
                    return
                sub = batch_texts[i:i+BATCH]
                vectors = embed_code_batch(sub)
                for j, v in enumerate(vectors):
                    batch_chunks[i+j]["vector"] = v

            # 写入
            job.update("storing",
                       f"写入 第{batch_seq}批 ({n} chunks)",
                       batch=batch_seq, stored=total_chunks + n)
            insert_chunks(batch_chunks)

            # 记录写入的 chunk ids (用于取消回滚)
            for c in batch_chunks:
                job._written_chunk_ids.append(c["id"])

            total_chunks += n
            batch_chunks.clear()
            batch_texts.clear()

        for file_idx, f in enumerate(files_to_parse):
            if job.is_cancelled():
                return

            # 每 500 个文件报告一次进度
            if file_idx % 500 == 0 or file_idx == total - 1:
                pct = round((file_idx + 1) / total * 100)
                job.update("parsing",
                           f"解析中: {file_idx + 1}/{total} ({pct}%)",
                           file_idx=file_idx + 1, total_files=total,
                           chunks_so_far=total_chunks, pct=pct)

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
                req.repo_name, effective_type, repo_path, paired or "",
            )
            for c in chunks:
                if c["metadata"].get("parse_warning"):
                    parse_warnings += 1
                batch_texts.append(c.get("display_text", c["content"]))
                batch_chunks.append(c)

            # 每累积 ~2500 chunks 处理一批 (约 500 文件 * 5 chunks/file)
            if len(batch_chunks) >= FILE_BATCH * 5:  # ~500 files * ~5 chunks each
                _process_batch()

        # 处理最后一批
        _process_batch()

        job.update("parse_done", f"解析完成: {total_chunks} chunks (⚠️ {parse_warnings} 降级)",
                   total_chunks=total_chunks, parse_warnings=parse_warnings)
        job.update("store_done", f"写入完成: {total_chunks} chunks")
        log.info(f"[scan:{job.scan_id}] 写入完成: {total_chunks} chunks")

        # 6. 更新配置
        _finalize_scan(job, files, effective_type)

    except Exception as e:
        job.status = "error"
        job.error = str(e)
        job.update("error", f"扫描失败: {e}")
        log.exception(f"[scan:{job.scan_id}] 扫描异常: {e}")
    finally:
        # 如果被取消，清理已写入数据
        if job.is_cancelled():
            _cleanup_scan(job)
            job.update("cleanup_done", f"已清理 {len(job._written_chunk_ids)} 个 chunks")
            log.info(f"[scan:{job.scan_id}] 取消清理完成: {len(job._written_chunk_ids)} chunks")

        # 释放 MPS GPU 缓冲区 + Python 循环引用（tree-sitter Node 环）
        import gc
        gc.collect()
        try:
            import torch
            if hasattr(torch, 'backends') and hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                torch.mps.empty_cache()
        except Exception:
            pass

        release_scan_lock(req.repo_name)
        log.info(f"[scan:{job.scan_id}] 锁已释放, 最终状态={job.status}")

        # 通知所有 SSE 订阅者任务结束
        for q in list(job._subscribers):
            try:
                q.put_nowait({"_final": True, "status": job.status})
            except asyncio.QueueFull:
                pass


def _finalize_scan(job: ScanJob, files: list, effective_type: str = ""):
    """扫描完成后更新配置"""
    req = job.req
    from code_db import get_stats as get_code_stats
    db_stats = get_code_stats()
    register_repo(req.repo_name, os.path.abspath(req.repo_path),
                  effective_type or req.project_type, req.languages, db_stats)
    new_mtimes = {f["rel_path"]: f["mtime"] for f in files}
    update_file_mtimes(req.repo_name, new_mtimes)
    job.stats = db_stats
    job.status = "completed"
    job.update("done", f"扫描完成 ✅ — {db_stats.get('total_chunks', 0)} chunks")


def _cleanup_scan(job: ScanJob):
    """取消后清理已写入的数据"""
    req = job.req
    if not job._written_chunk_ids:
        return

    # SQLite 批量删除
    from code_db import get_sqlite
    conn = get_sqlite()
    conn.executemany("DELETE FROM code_fts WHERE chunk_id = ?",
                     [(cid,) for cid in job._written_chunk_ids])
    conn.executemany("DELETE FROM code_meta WHERE chunk_id = ?",
                     [(cid,) for cid in job._written_chunk_ids])
    conn.executemany("DELETE FROM code_relations WHERE caller_chunk_id = ?",
                     [(cid,) for cid in job._written_chunk_ids])
    conn.commit()

    # LanceDB 批量删除 (用 OR 条件一次删完)
    try:
        table = get_table_from_db()
        # 分批删 (每批 500)
        for i in range(0, len(job._written_chunk_ids), 500):
            batch = job._written_chunk_ids[i:i+500]
            conditions = " OR ".join(f"id = '{cid}'" for cid in batch)
            table.delete(conditions)
    except Exception:
        pass

    # 恢复 mtime
    if job._old_mtimes:
        update_file_mtimes(req.repo_name, job._old_mtimes)
    if not job._old_mtimes:
        remove_repo(req.repo_name)


def get_table_from_db():
    from code_db import get_table
    return get_table()


# ── POST /api/code/scan (启动后台任务) ───────────────────────────

def _start_scan_job(req: ScanRequest) -> str:
    """同步启动扫描任务并返回 scan_id

    锁不归本函数管，由调用方在调本函数前通过 try_acquire_scan_lock 拿取；
    释放由 _run_scan 后台线程 finally 块负责（code_routes.py:309）。
    watchdog 后台线程复用此入口（线程不能 await）。
    """
    scan_id = str(uuid.uuid4())[:8]
    log.info(f"[scan] 分配 scan_id={scan_id} (req.repo_name={req.repo_name})")
    job = ScanJob(scan_id, req)
    _scan_jobs[scan_id] = job

    # 启动后台线程
    thread = threading.Thread(target=_run_scan, args=(job,), daemon=True)
    thread.start()

    return scan_id


@router.post("/scan")
async def scan_repo_endpoint(req: ScanRequest):
    """启动异步扫描, 返回 scan_id"""
    repo_path = os.path.abspath(req.repo_path)

    # 自动检测工程类型
    from code_parser import auto_detect_project_type
    detected_type = req.project_type or auto_detect_project_type(repo_path)
    log.info(f"[scan] 启动扫描: repo={req.repo_name}, path={repo_path}, type={detected_type} (指定={req.project_type or '自动'}), langs={req.languages}")

    if not os.path.isdir(repo_path):
        log.warning(f"[scan] 目录不存在: {repo_path}")
        raise HTTPException(400, detail=f"目录不存在: {repo_path}")

    if not try_acquire_scan_lock(req.repo_name):
        log.warning(f"[scan] 锁冲突: {req.repo_name} 正在扫描中")
        raise HTTPException(409, detail=f"仓库 {req.repo_name} 正在扫描中")

    scan_id = _start_scan_job(req)
    log.info(f"[scan] 启动扫描: scan_id={scan_id}, repo={req.repo_name}")

    return {
        "status": "started",
        "scan_id": scan_id,
        "repo_name": req.repo_name,
        "message": "扫描已启动，通过 SSE 获取实时进度",
    }


# ── GET /api/code/scan/{scan_id}/sse (进度 SSE) ─────────────────

@router.get("/scan/{scan_id}/sse")
async def scan_progress_sse(scan_id: str):
    """SSE 实时推送扫描进度"""
    if scan_id not in _scan_jobs:
        raise HTTPException(404, detail="扫描任务不存在")

    job = _scan_jobs[scan_id]

    async def event_generator():
        # 先发送已有进度
        for entry in job.progress:
            if entry.get("_final"):
                continue
            yield {"event": "progress", "data": _json.dumps(entry, ensure_ascii=False)}

        # 如果已完成/取消/出错，发送最终状态
        if job.status in ("completed", "cancelled", "error"):
            yield {"event": "done", "data": _json.dumps({
                "status": job.status,
                "error": job.error,
                "stats": job.stats,
            }, ensure_ascii=False)}
            return

        # 订阅后续更新
        queue = job.subscribe()
        try:
            while True:
                # 取消后缩短超时，快速响应
                timeout = 3 if job.status in ("cancelled", "error") else 60
                try:
                    entry = await asyncio.wait_for(queue.get(), timeout=timeout)

                    # 后台线程发来的最终信号
                    if entry.get("_final"):
                        yield {"event": "done", "data": _json.dumps({
                            "status": entry.get("status", job.status),
                            "error": job.error,
                            "stats": job.stats,
                        }, ensure_ascii=False)}
                        return

                    yield {"event": "progress", "data": _json.dumps(entry, ensure_ascii=False)}

                    if job.status in ("completed", "cancelled", "error"):
                        yield {"event": "done", "data": _json.dumps({
                            "status": job.status,
                            "error": job.error,
                            "stats": job.stats,
                        }, ensure_ascii=False)}
                        return
                except asyncio.TimeoutError:
                    # 心跳
                    yield {"event": "heartbeat", "data": ""}
                    if job.status in ("completed", "cancelled", "error"):
                        break
        finally:
            job.unsubscribe(queue)

    from sse_starlette.sse import EventSourceResponse
    return EventSourceResponse(event_generator())


# ── POST /api/code/scan/{scan_id}/cancel (取消扫描) ──────────────

@router.post("/scan/{scan_id}/cancel")
async def cancel_scan(scan_id: str):
    """取消扫描 (清理由后台线程的 finally 块执行)"""
    if scan_id not in _scan_jobs:
        raise HTTPException(404, detail="扫描任务不存在")

    job = _scan_jobs[scan_id]
    if job.status not in ("pending", "running"):
        raise HTTPException(400, detail=f"任务状态为 {job.status}，无法取消")

    log.info(f"[scan:{scan_id}] 用户取消扫描")
    job.cancel_event.set()
    job.status = "cancelled"  # 立即标记状态，SSE 心跳可检测
    return {"status": "cancelling", "scan_id": scan_id}


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

        system_prompt = get_agent_system_prompt()
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


# ── POST /api/code/trace ──────────────────────────────────────────

@router.post("/trace")
async def trace_endpoint(req: TraceRequest):
    """调用链追踪：追踪符号的调用者和被调用者"""
    from code_search import trace_code

    if not req.symbol.strip():
        raise HTTPException(400, detail="symbol 不能为空")

    tracker = StepTracker(operation_type="code_trace")
    try:
        result = trace_code(
            symbol_name=req.symbol,
            repo_name=req.repo_name,
            direction=req.direction,
            depth=req.depth,
            tracker=tracker,
        )
        return result
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
    from code_embedder import get_code_model_info
    db_stats = get_stats()
    db_stats["code_embedder"] = get_code_model_info()
    return db_stats


# ── GET /api/code/dashboard ──────────────────────────────────────

@router.get("/dashboard")
async def code_dashboard_endpoint():
    """代码知识库仪表盘：总览 + 仓库清单 + embedder 信息"""
    from code_embedder import get_code_model_info

    db_stats = get_stats()
    repos_cfg = list_repos()

    # 合并 stats 与 config：按 repo_name 索引以便补充 last_scanned/languages
    by_repo = db_stats.get("by_repo", {})  # {repo_name: count}
    repos_view = []
    for r in repos_cfg:
        repos_view.append({
            "name": r["name"],
            "project_type": r.get("project_type", ""),
            "chunks": by_repo.get(r["name"], r.get("total_chunks", 0)),
            "languages": r.get("languages", []),
            "last_scanned": r.get("last_scanned", ""),
        })

    return {
        "total_chunks": db_stats.get("total_chunks", 0),
        "total_repos": db_stats.get("total_repos", 0),
        "total_languages": len(db_stats.get("by_language", {})),
        "total_chunk_types": len(db_stats.get("by_chunk_type", {})),
        "by_language": db_stats.get("by_language", {}),
        "by_chunk_type": db_stats.get("by_chunk_type", {}),
        "repos": repos_view,
        "embedder": get_code_model_info(),
    }


# ── GET /api/code/lancedb/inspect ─────────────────────────────────

@router.get("/lancedb/inspect")
async def code_lancedb_inspect():
    """code_chunks 表的内省信息：schema / 行数 / fragments / versions / indices"""
    from code_db import get_table as get_code_table

    table = get_code_table()
    ds = table.to_lance()

    schema_fields = []
    vector_dim = None
    for field in ds.schema:
        type_str = str(field.type)
        is_vector = type_str.startswith("fixed_size_list")
        dim = field.type.list_size if is_vector else None
        if is_vector:
            vector_dim = dim
        schema_fields.append({
            "name": field.name,
            "type": type_str,
            "is_vector": is_vector,
            "vector_dim": dim,
        })

    fragments = [
        {"id": f.fragment_id, "rows": f.count_rows()}
        for f in ds.get_fragments()
    ]

    versions = []
    for v in ds.versions()[-10:]:
        ts = v["timestamp"]
        versions.append({
            "version": v["version"],
            "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
        })

    indices = list(ds.list_indices())
    return {
        "table_name": "code_chunks",
        "total_rows": ds.count_rows(),
        "schema": schema_fields,
        "vector_dim": vector_dim,
        "current_version": ds.version,
        "version_count": len(ds.versions()),
        "recent_versions": versions,
        "fragments": fragments,
        "fragment_count": len(fragments),
        "indices": indices,
        "has_index": len(indices) > 0,
        "search_strategy": "全量余弦距离扫描" if not indices else "索引检索",
    }


# ── GET /api/code/lancedb/rows ────────────────────────────────────

@router.get("/lancedb/rows")
async def code_lancedb_rows(
    limit: int = 20,
    offset: int = 0,
    repo_name: Optional[str] = None,
    language: Optional[str] = None,
    chunk_type: Optional[str] = None,
    keyword: Optional[str] = None,
    include_full_vector: bool = False,
):
    """分页列出 code_chunks 表内的数据，可按 repo_name/language/chunk_type 过滤或按 content 关键词模糊搜"""
    from code_db import get_table as get_code_table

    table = get_code_table()
    df = table.to_pandas()

    if repo_name:
        df = df[df["repo_name"] == repo_name]
    if language:
        df = df[df["language"] == language]
    if chunk_type:
        df = df[df["chunk_type"] == chunk_type]
    if keyword:
        df = df[df["content"].str.contains(keyword, na=False, regex=False)]

    total = len(df)
    df = df.iloc[offset:offset + limit]

    rows = []
    for _, r in df.iterrows():
        v = list(r["vector"])
        try:
            metadata = _json.loads(r.get("metadata", "{}"))
        except Exception:
            metadata = {}
        rows.append({
            "id": r["id"],
            "repo_name": r.get("repo_name", ""),
            "project_type": r.get("project_type", ""),
            "file_path": r.get("file_path", ""),
            "file_name": r.get("file_name", ""),
            "language": r.get("language", ""),
            "chunk_type": r.get("chunk_type", ""),
            "symbol_name": r.get("symbol_name", ""),
            "content": r.get("content", ""),
            "content_length": len(r.get("content", "")),
            "line_start": int(r.get("line_start", 0)),
            "line_end": int(r.get("line_end", 0)),
            "metadata": metadata,
            "vector_dim": len(v),
            "vector_preview": [round(float(x), 4) for x in v[:16]],
            "vector_full": [round(float(x), 6) for x in v] if include_full_vector else None,
            "vector_norm": round(float(sum(x * x for x in v) ** 0.5), 4),
        })

    return {
        "total": int(total),
        "offset": offset,
        "limit": limit,
        "rows": rows,
    }


# ── POST /api/code/fts/migrate-chinese ─────────────────────────────

@router.post("/fts/migrate-chinese")
async def migrate_fts_chinese_endpoint(repo_name: str = ""):
    """迁移现有 FTS5 索引：对中文内容进行 jieba 分词重建。

    可选传 repo_name 仅迁移指定仓库。
    新索引写入时已自动分词，此端点用于迁移历史数据。
    """
    from code_db import migrate_fts_chinese
    result = migrate_fts_chinese(repo_name or None)
    return {"status": "ok", **result}


# ── DELETE /api/code/repos (清空全部) ─────────────────────────────

@router.delete("/repos")
async def clear_all_repos():
    """清空所有索引数据 (LanceDB + SQLite + 配置)"""
    from code_db import clear_all as db_clear_all
    from code_config import load_config, save_config

    repos = list_repos()
    repo_names = [r["name"] for r in repos]
    log.info(f"[clear] 清空全部: {len(repo_names)} 个仓库")

    # 清空 DB
    deleted = db_clear_all()

    # 清空配置
    save_config({"repos": {}, "file_mtimes": {}})

    # 释放所有扫描锁
    for name in repo_names:
        release_scan_lock(name)

    log.info(f"[clear] 完成: 删除 {deleted} chunks")
    return {"status": "ok", "deleted_chunks": deleted, "cleared_repos": repo_names}


# ── DELETE /api/code/repos/{name} ────────────────────────────────

@router.delete("/repos/{name}")
async def delete_repo_endpoint(name: str):
    """删除仓库索引"""
    log.info(f"[delete] 开始删除仓库: {name}")
    if not get_repo_config(name):
        log.warning(f"[delete] 仓库不存在: {name}")
        raise HTTPException(404, detail=f"仓库 {name} 不存在")

    deleted = delete_by_repo(name)
    remove_repo(name)
    release_scan_lock(name)  # 释放可能残留的扫描锁
    log.info(f"[delete] 完成: {name}, 删除 {deleted} chunks")

    return {
        "status": "ok",
        "deleted_chunks": deleted,
        "repo_name": name,
    }


# ── POST /api/code/repos/{name}/refresh ──────────────────────────

@router.post("/repos/{name}/refresh")
async def refresh_repo_endpoint(name: str):
    """刷新仓库索引 (增量：按 mtime 新增/更新/删除)"""
    repo_config = get_repo_config(name)
    if not repo_config:
        raise HTTPException(404, detail=f"仓库 {name} 不存在")

    # 直接触发增量扫描（scan 内部通过 mtime diff 自动处理新增/更新/删除）
    req = ScanRequest(
        repo_name=name,
        repo_path=repo_config["repo_path"],
        project_type=repo_config.get("project_type", "generic"),
        languages=repo_config.get("languages", []),
    )
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


# ── GET /api/code/skip-rules ──────────────────────────────────────

@router.get("/skip-rules")
async def api_get_skip_rules():
    """获取当前可配置排除规则"""
    return get_skip_rules()


# ── PUT /api/code/skip-rules ──────────────────────────────────────

@router.put("/skip-rules")
async def api_save_skip_rules(req: SkipRulesRequest):
    """保存可配置排除规则"""
    rules = {"skip_dirs": req.skip_dirs, "skip_exts": req.skip_exts, "gitignore_selections": req.gitignore_selections}
    try:
        save_skip_rules(rules)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "ok", "message": "规则已保存"}


# ── POST /api/code/skip-rules/reset ───────────────────────────────

@router.post("/skip-rules/reset")
async def api_reset_skip_rules():
    """恢复默认排除规则"""
    rules = reset_skip_rules()
    return {"status": "ok", "message": "已恢复默认规则", "rules": rules}


# ── GET /api/code/gitignore-dirs ──────────────────────────────────

@router.get("/gitignore-dirs")
async def api_get_gitignore_dirs(repo_path: str = ""):
    """读取 .gitignore 并提取目录名"""
    if not repo_path or not os.path.isdir(repo_path):
        return {"dirs": []}
    return {"dirs": parse_gitignore_dirs(repo_path)}


# ── POST /api/code/skip-rules/open-finder ─────────────────────────

@router.post("/skip-rules/open-finder")
async def api_open_skip_rules_in_finder():
    """在 Finder 中打开配置文件"""
    open_config_in_finder()
    return {"status": "ok"}


# ── POST /api/code/skip-rules/preview ─────────────────────────────

@router.post("/skip-rules/preview")
async def api_skip_rules_preview(repo_path: str = ""):
    """预览应用排除规则后将扫描的文件数"""
    if not repo_path or not os.path.isdir(repo_path):
        return {"total_files": 0, "filtered_files": 0, "skipped_files": 0}

    from pathlib import Path
    from code_parser import EXTENSION_MAP

    skip_dirs = get_skip_dirs()
    skip_exts = get_skip_exts()
    repo = os.path.abspath(repo_path)

    def _count_files(dirs_filter=None, exts_filter=None):
        """遍历目录计数代码文件"""
        count = 0
        for root, dirs, filenames in os.walk(repo):
            if dirs_filter is not None:
                dirs[:] = [d for d in dirs if d not in dirs_filter]
            for fname in filenames:
                ext = Path(fname).suffix.lower()
                if ext not in EXTENSION_MAP:
                    continue
                if exts_filter and ext in exts_filter:
                    continue
                abs_path = os.path.join(root, fname)
                try:
                    if os.path.getsize(abs_path) > 100 * 1024:
                        continue
                except OSError:
                    continue
                count += 1
        return count

    # total: 不排除任何目录/扩展名
    total = _count_files()
    # filtered: 应用排除规则
    filtered = _count_files(dirs_filter=skip_dirs, exts_filter=skip_exts)

    return {
        "total_files": total,
        "filtered_files": filtered,
        "skipped_files": total - filtered,
    }


# ── LanceDB 原理演示端点 ─────────────────────────────────────────

class DemoInsertRequest(BaseModel):
    text: str = "def hello():\n    print('hello world')\n\ndef add(a, b):\n    return a + b"
    language: str = "python"
    repo_name: str = "demo-repo"
    file_path: str = "demo.py"


@router.post("/lancedb/demo/insert")
async def demo_insert(req: DemoInsertRequest):
    """Sandbox 演示：解析→分块→向量化，不真实写入"""
    from code_parser import chunk_code
    from code_embedder import embed_batch, get_code_model_info
    from code_db import get_table

    try:
        steps = []
        code_bytes = req.text.encode("utf-8")

        # Step 1: AST 解析 + 分块
        chunks = chunk_code(code_bytes, req.language, req.file_path, req.repo_name)
        steps.append({
            "name": "ast_parse_and_chunk",
            "description": f"使用 tree-sitter 解析 {req.language} 代码 AST，按顶层符号分块",
            "output": {
                "language": req.language,
                "chunk_count": len(chunks),
                "chunks": [
                    {
                        "index": i,
                        "chunk_type": c.get("chunk_type", "unknown"),
                        "symbol_name": c.get("symbol_name") or "(anonymous)",
                        "line_start": c.get("line_start", 0),
                        "line_end": c.get("line_end", 0),
                    }
                    for i, c in enumerate(chunks)
                ],
            },
        })

        # Step 2: 向量化
        model_info = get_code_model_info()
        model_name = model_info["model_name"]
        texts = [c["content"] for c in chunks]
        # embed_batch 返回 list[list[float]]（2D），每个元素是一个向量
        raw = embed_batch(texts)
        vectors: list[list[float]] = raw if raw and isinstance(raw[0], list) else [raw]  # type: ignore
        dim = len(vectors[0]) if vectors and vectors[0] else 0

        vec_details = []
        for i, vec in enumerate(vectors):
            norm = round(math.sqrt(sum(x * x for x in vec)), 4)
            vec_details.append({
                "chunk_index": i,
                "dim": dim,
                "norm": str(norm),
                "min": str(round(min(vec), 4)),
                "max": str(round(max(vec), 4)),
                "preview_first16": [round(v, 4) for v in vec[:16]],
            })

        steps.append({
            "name": "embed_chunks",
            "description": f"使用 {model_name} 将每个 chunk 转为 {dim} 维向量",
            "output": {
                "model": model_name,
                "vector_dim": dim,
                "vectors": vec_details,
            },
        })

        # Step 3: Sandbox 不写入
        table = get_table()
        current_ver = getattr(table, 'version', getattr(table, '_version', 0))
        frag_id = uuid.uuid4().hex[:12]

        steps.append({
            "name": "would_insert",
            "description": "Sandbox 模式：仅演示，不真实写入数据库",
            "output": {
                "would_create_fragment_id": f"fragment_{frag_id}",
                "current_version": current_ver,
                "version_after_insert": current_ver + 1,
                "records_preview": [
                    {
                        "id": c.get("id", f"{req.file_path}_{i}"),
                        "file_path": req.file_path,
                        "chunk_type": c.get("chunk_type", "unknown"),
                        "symbol_name": c.get("symbol_name") or "(anonymous)",
                        "content_preview": c["content"][:80] + ("..." if len(c["content"]) > 80 else ""),
                    }
                    for i, c in enumerate(chunks)
                ],
            },
        })

        return {"steps": steps}

    except Exception as e:
        log.exception("demo_insert failed")
        raise HTTPException(500, detail=str(e))


class DemoSearchRequest(BaseModel):
    query: str = "hello function"
    top_k: int = 3
    score_threshold: float = 0.3


@router.post("/lancedb/demo/search")
async def demo_search(req: DemoSearchRequest):
    """Sandbox 演示：查询→向量化→扫描→排序→转换"""
    from code_embedder import embed_query, get_code_model_info
    from code_db import get_table, search_vector

    try:
        steps = []

        # Step 1: 向量化查询
        model_info = get_code_model_info()
        model_name = model_info["model_name"]
        query_vec = embed_query(req.query)
        dim = len(query_vec)
        norm = round(math.sqrt(sum(x * x for x in query_vec)), 4)

        steps.append({
            "name": "embed_query",
            "description": "将查询文本转为向量",
            "output": {
                "model": model_name,
                "dim": dim,
                "norm": str(norm),
                "preview_first16": [round(v, 4) for v in query_vec[:16]],
            },
        })

        # Step 2: 查询翻译（简化：按空格分词）
        terms = [t for t in req.query.split() if len(t) > 1]
        steps.append({
            "name": "query_translate",
            "description": "查询翻译（关键词提取）",
            "output": {
                "original_query": req.query,
                "translated_terms": terms,
                "method": "whitespace_tokenizer",
            },
        })

        # Step 3: 扫描策略
        table = get_table()
        total_rows = table.count_rows()
        has_idx = False
        try:
            indices = table.list_indices()
            has_idx = len(indices) > 0
        except Exception:
            pass

        flops = total_rows * dim * 2 if total_rows > 0 else 0
        frag_count = 0
        try:
            frag_count = len(table.to_lance().get_fragments())
        except Exception:
            pass
        steps.append({
            "name": "scan_strategy",
            "description": "LanceDB 扫描策略分析",
            "output": {
                "has_index": has_idx,
                "strategy": "IVF-PQ 索引检索" if has_idx else "全量余弦距离扫描",
                "fragments_to_scan": frag_count,
                "total_rows_to_scan": total_rows,
                "flops_estimate": flops,
            },
        })

        # Step 4: 计算距离
        candidates = []
        if total_rows > 0:
            results = search_vector(query_vec, top_k=req.top_k + 5)
            for r in results:
                candidates.append({
                    "id": r.get("id", ""),
                    "symbol_name": r.get("symbol_name", ""),
                    "distance": round(r.get("_distance", 1.0), 4),
                    "content_preview": (r.get("content", ""))[:80],
                })

        # 按距离排序
        candidates.sort(key=lambda c: c["distance"])
        dist_min = candidates[0]["distance"] if candidates else 0
        dist_max = candidates[-1]["distance"] if candidates else 0

        steps.append({
            "name": "compute_distances",
            "description": "计算查询向量与所有文档向量的余弦距离",
            "output": {
                "candidates_returned": len(candidates),
                "distance_min": dist_min,
                "distance_max": dist_max,
                "candidates": candidates[:10],
            },
        })

        # Step 5: Top-K 选取
        selected = candidates[: req.top_k]
        steps.append({
            "name": "top_k_selection",
            "description": f"选取 Top-{req.top_k} 结果",
            "output": {
                "k": req.top_k,
                "selected": selected,
            },
        })

        # Step 6: 分数转换
        examples = []
        for c in selected[:3]:
            sim = round(1.0 / (1.0 + c["distance"]), 4)
            examples.append({
                "id": c["id"],
                "distance": c["distance"],
                "similarity_score": sim,
            })

        steps.append({
            "name": "score_conversion",
            "description": "将距离转换为相似度分数",
            "output": {
                "formula": "similarity = 1 / (1 + distance)",
                "examples": examples,
            },
        })

        return {"steps": steps}

    except Exception as e:
        log.exception("demo_search failed")
        raise HTTPException(500, detail=str(e))


# ── Agent 配置 ───────────────────────────────────────────────────

import threading

_agent_config_lock = threading.Lock()
_AGENT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "code_agent_config.json")

DEFAULT_AGENT_PROMPT = """你是 Email Wiki 知识库管理员，负责基于已索引的代码仓库回答问题。

**能力范围**：
- 向量语义搜索：根据代码含义查找相关片段
- FTS5 全文检索：精确匹配关键词、符号名、函数名
- 调用链追踪：沿函数调用关系向上/向下追踪数据流
- 文件内容浏览：查阅具体文件的详细内容
- 关联分析：将多个搜索来源的数据组合、对比、归纳

**工作原则**：
1. 以事实为依据：所有结论必须引用具体的文件路径和行号
2. 不可胡编乱造：不确定时明确说明"未找到相关代码"或"需要更多信息"
3. 主动关联：自动联想相关模块、调用方、被调用方
4. 深入追问：发现线索不完整时，建议搜索更多关键词或追踪调用链
5. 数据优先：先展示代码证据，再给出分析结论

**回答格式**：
- 先列出找到的关键代码片段（文件路径+行号+内容）
- 再给出分析、关联和总结
- 不确定的位置标注"(待确认)"
"""

DEFAULT_AGENT_CONFIG = {
    "bot_name": "知识库管理员",
    "bot_style": "专业、严谨、以数据说话",
    "system_prompt": DEFAULT_AGENT_PROMPT,
}


def _load_agent_config() -> dict:
    """加载 Agent 配置，不存在则返回默认"""
    if not os.path.exists(_AGENT_CONFIG_PATH):
        return dict(DEFAULT_AGENT_CONFIG)
    try:
        with open(_AGENT_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 合并缺失的 key
        for k, v in DEFAULT_AGENT_CONFIG.items():
            data.setdefault(k, v)
        return data
    except Exception:
        return dict(DEFAULT_AGENT_CONFIG)


def _save_agent_config(config: dict) -> None:
    """保存 Agent 配置"""
    os.makedirs(os.path.dirname(_AGENT_CONFIG_PATH), exist_ok=True)
    with open(_AGENT_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_agent_system_prompt() -> str:
    """获取当前 Agent 的 system prompt（供 chat 端点使用）"""
    config = _load_agent_config()
    return config.get("system_prompt", DEFAULT_AGENT_PROMPT)


@router.get("/agent-config")
async def api_get_agent_config():
    """获取 Agent 配置"""
    return _load_agent_config()


@router.put("/agent-config")
async def api_update_agent_config(config: dict):
    """更新 Agent 配置"""
    with _agent_config_lock:
        current = _load_agent_config()
        # 只更新提供的字段
        for key in ("bot_name", "bot_style", "system_prompt"):
            if key in config:
                current[key] = str(config[key])
        _save_agent_config(current)
        return current


@router.post("/agent-config/reset")
async def api_reset_agent_config():
    """恢复 Agent 默认配置"""
    with _agent_config_lock:
        _save_agent_config(dict(DEFAULT_AGENT_CONFIG))
        return dict(DEFAULT_AGENT_CONFIG)


# ── GET /api/code/resolve-path ─────────────────────────────────

@router.get("/resolve-path")
async def resolve_path(name: str, parent: Optional[str] = None):
    """在 parent 下找名为 name 的子目录。

    - 唯一命中：返回 {"path": "..."}
    - 多匹配：返回 {"matches": [...]}（最多 20 个）
    - 无匹配：404
    - parent 无效：400
    """
    search_root = os.path.abspath(parent) if parent else os.path.expanduser("~")
    if not os.path.isdir(search_root):
        raise HTTPException(400, detail=f"搜索根目录不存在: {search_root}")

    # 跳过这些大目录避免扫得慢
    SKIP_DIRS = {".git", "node_modules", "venv", "__pycache__", "Library", "Applications"}

    matches: list[str] = []
    search_root = search_root.rstrip(os.sep)
    root_depth = search_root.count(os.sep)
    MAX_DEPTH = 3

    for dirpath, dirnames, _ in os.walk(search_root):
        # 过滤隐藏目录和大目录
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS]
        if name in dirnames:
            matches.append(os.path.join(dirpath, name))
        # 限深
        cur_depth = dirpath.count(os.sep) - root_depth
        if cur_depth >= MAX_DEPTH:
            dirnames[:] = []

    if len(matches) == 0:
        raise HTTPException(404, detail=f"在 {search_root} 下未找到目录: {name}")
    if len(matches) == 1:
        return {"path": matches[0]}
    return {"matches": matches[:20]}


# ── 黑名单：危险目录禁止打开 ─────────────────────────────────────

_OPEN_DENY_PREFIXES = (
    os.path.expanduser("~/.ssh"),
    "/etc", "/var", "/usr", "/bin", "/sbin",
    "/System", "/Library/Apple", "/private",
)


# ── POST /api/code/open-in-finder ─────────────────────────────────

@router.post("/open-in-finder")
async def open_in_finder(payload: dict):
    """在系统文件管理器中打开指定路径。

    - macOS: open
    - Windows: explorer
    - Linux: xdg-open
    - 未知系统 / 命令缺失: 返回 {skipped: True} 让前端兜底
    """
    raw = (payload or {}).get("path", "")
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(400, detail="path 必填且为非空字符串")

    path = os.path.abspath(raw.strip())
    if not os.path.isdir(path):
        raise HTTPException(400, detail=f"不是有效目录: {path}")

    # 测试环境跳过黑名单：macOS 的 tmp_path 在 /private/var/... 下会被黑名单误伤
    # 用环境变量显式开启，生产环境默认关闭
    if os.environ.get("EMAIL_WIKI_SKIP_PATH_DENYLIST") != "1":
        for deny in _OPEN_DENY_PREFIXES:
            if path == deny or path.startswith(deny + os.sep):
                raise HTTPException(403, detail=f"禁止访问: {deny}")

    system = platform.system()
    if system == "Darwin":
        cmd = ["open", path]
    elif system == "Windows":
        cmd = ["explorer", path]
    elif system == "Linux":
        cmd = ["xdg-open", path]
    else:
        return {"path": path, "skipped": True, "reason": f"不支持的系统: {system}"}

    try:
        # start_new_session=True 让子进程脱离父进程组，避免成为 zombie
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except FileNotFoundError:
        return {"path": path, "skipped": True, "reason": f"未找到命令: {cmd[0]}"}
    return {"path": path, "opened": True}
