"""代码知识库 REST API 路由"""

import os
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException

log = logging.getLogger("code_kb")
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from step_tracker import StepTracker
from code_parser import parse_repo, scan_directory
from code_db import insert_chunks, delete_by_repo, delete_by_file, get_stats
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
                batch_texts.append(c["content"])
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

    scan_id = str(uuid.uuid4())[:8]
    log.info(f"[scan] 分配 scan_id={scan_id}")
    job = ScanJob(scan_id, req)
    _scan_jobs[scan_id] = job

    # 启动后台线程
    thread = threading.Thread(target=_run_scan, args=(job,), daemon=True)
    thread.start()

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
    from code_embedder import get_code_model_info
    db_stats = get_stats()
    db_stats["code_embedder"] = get_code_model_info()
    return db_stats


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
