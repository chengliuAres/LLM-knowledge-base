"""FastAPI 主入口 - 文档知识库"""

import os
import shutil
import time
import json
import uuid
from typing import Optional
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from logging_setup import configure_logging, get_logger, request_id_var
from log_routes import router as log_router
from parser import process_file
from embedder import embed_text, embed_query, embed_batch, _model_name as EMBED_MODEL_NAME, get_model_info


def _get_code_embedder_info() -> dict:
    """延迟加载代码 embedder 信息，避免 import 时触发模型加载"""
    try:
        from code_embedder import get_code_model_info
        return get_code_model_info()
    except Exception:
        return {"model_name": "nomic-ai/CodeRankEmbed", "dimension": 768}
from db import insert_documents, search_similar, list_documents, delete_document, get_stats
from email_db import init_db, get_all_emails, get_stats as get_email_stats, search_emails, init_sample_data
from email_parser import email_to_chunks, batch_convert_emails
from llm_client import get_llm_client, build_rag_prompt
from step_tracker import StepTracker
import metrics_db
import lancedb_inspect
from match_reasons import annotate_results
from code_routes import router as code_router
from code_mcp import router as mcp_router

log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期：启动时配置日志 + 初始化邮件 DB；关闭时无清理。"""
    configure_logging()
    log.info("服务启动")
    init_db()
    init_sample_data()
    log.info("服务启动完成")
    yield


app = FastAPI(title="文档知识库", version="2.0.0", lifespan=lifespan)
app.include_router(code_router)
app.include_router(mcp_router)
app.include_router(log_router)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """给每个请求注入 request_id（取自 X-Request-ID 头或生成 8 位 UUID），写回响应头。"""
    rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
    token = request_id_var.set(rid)
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers["X-Request-ID"] = rid
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """全局兜底：未捕获的 Exception 自动打 stack trace + request_id。"""
    rid = request_id_var.get()
    log.exception(f"unhandled path={request.url.path} method={request.method} request_id={rid}")
    return JSONResponse(
        status_code=500,
        content={"detail": "内部错误", "request_id": rid},
    )


# 上传目录
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 支持的文件格式
ALLOWED_EXTENSIONS = {'.pdf', '.txt', '.md', '.docx', '.eml'}


# ========== 请求/响应模型 ==========

class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    file_type: str = None  # 可选过滤类型


class SearchResponse(BaseModel):
    query: str
    results: list[dict]
    steps: list[dict]  # 执行步骤


class ChatRequest(BaseModel):
    query: str
    top_k: int = 5
    stream: bool = False


class ChatResponse(BaseModel):
    query: str
    answer: str
    sources: list[dict]
    steps: list[dict]


class UploadResponse(BaseModel):
    filename: str
    chunks: int
    status: str
    steps: list[dict] = []


class EmailImportRequest(BaseModel):
    count: int = 50  # 导入数量


# ========== API 路由 ==========

@app.post("/api/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)):
    """上传并解析文档"""
    log.info(f"upload_start filename={file.filename}")
    tracker = StepTracker(operation_type="insert_file")
    
    # 检查文件格式
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"不支持的文件格式: {ext}，支持: {ALLOWED_EXTENSIONS}")
    
    try:
        # 步骤1: 接收文件
        step1 = tracker.add_step("receive_file", "接收上传文件")
        step1.start()
        
        file_content = await file.read()
        file_size = len(file_content)
        
        step1.complete({
            "filename": file.filename,
            "file_type": ext,
            "file_size": f"{file_size / 1024:.1f} KB",
            "allowed_extensions": list(ALLOWED_EXTENSIONS)
        })

        tracker.set_extra(filename=file.filename, file_type=ext, file_size_bytes=file_size)
        
        # 步骤2: 保存文件到磁盘
        step2 = tracker.add_step("save_file", "保存文件到 uploads/ 目录")
        step2.start()
        
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as f:
            f.write(file_content)
        
        step2.complete({
            "path": file_path,
            "size_bytes": file_size
        })
        
        # 步骤3: 解析文档内容
        step3 = tracker.add_step("parse_document", "解析文档内容")
        step3.start()
        
        chunks = process_file(file_path)
        
        if not chunks:
            raise HTTPException(400, "文档内容为空或无法解析")
        
        # 统计分块信息
        total_chars = sum(len(c["content"]) for c in chunks)
        avg_chunk_size = total_chars // len(chunks) if chunks else 0
        
        # 分块详情
        chunk_details = []
        for i, c in enumerate(chunks[:3]):  # 展示前3个分块
            chunk_details.append({
                "index": i,
                "length": len(c["content"]),
                "preview": c["content"][:80] + "..." if len(c["content"]) > 80 else c["content"]
            })
        
        step3.complete({
            "total_chunks": len(chunks),
            "total_characters": total_chars,
            "avg_chunk_size": f"{avg_chunk_size} 字符",
            "chunk_strategy": "按段落分割，超长段落按句子切分",
            "sample_chunks": chunk_details
        })
        
        # 步骤4: 生成 Embedding 向量
        step4 = tracker.add_step("generate_embeddings", "生成 Embedding 向量")
        step4.start()
        
        contents = [c["content"] for c in chunks]
        vectors = embed_batch(contents)
        
        step4.complete({
            "model": EMBED_MODEL_NAME,
            "vector_dimension": len(vectors[0]) if vectors else 0,
            "total_vectors": len(vectors),
            "batch_processing": True,
            "sample_vector_first5": [round(v, 4) for v in vectors[0][:5]] if vectors else [],
            "sample_vector_last5": [round(v, 4) for v in vectors[0][-5:]] if vectors else []
        })
        
        # 步骤5: 存入 LanceDB
        step5 = tracker.add_step("store_vectors", "存入 LanceDB 向量数据库")
        step5.start()
        
        for chunk, vector in zip(chunks, vectors):
            chunk["vector"] = vector
            chunk.setdefault("metadata", {})
        
        insert_documents(chunks)
        
        step5.complete({
            "table_name": "documents",
            "stored_count": len(chunks),
            "index_type": "无索引（追加到下一个 fragment）",
            "stored_ids": [c["id"] for c in chunks[:3]],
            "data_fields": ["id", "filename", "chunk_index", "content", "vector", "file_type", "metadata"]
        })

        tracker.set_extra(chunk_count=len(chunks))
        tracker.flush()
        
        return UploadResponse(
            filename=file.filename,
            chunks=len(chunks),
            status="ok",
            steps=tracker.to_list()
        )
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"upload_failed filename={file.filename} error={e}")
        tracker.flush(status="error")
        raise HTTPException(500, f"处理失败: {str(e)}")


@app.post("/api/emails/import")
async def import_emails(request: EmailImportRequest):
    """从邮件DB导入邮件到 LanceDB"""
    log.info(f"email_import_start count={request.count}")
    tracker = StepTracker(operation_type="email_import")
    
    try:
        # 步骤1: 从邮件DB获取邮件
        step1 = tracker.add_step("fetch_emails", "从邮件数据库获取邮件")
        step1.start()
        
        emails = get_all_emails(limit=request.count)
        
        step1.complete({
            "email_count": len(emails),
            "sample_subjects": [e.get('subject', '') for e in emails[:3]]
        })
        
        # 步骤2: 转换邮件为文档块
        step2 = tracker.add_step("convert_emails", "将邮件转换为文档块")
        step2.start()
        
        chunks = batch_convert_emails(emails)
        
        step2.complete({
            "chunk_count": len(chunks),
            "avg_chunk_size": sum(len(c["content"]) for c in chunks) // len(chunks) if chunks else 0
        })
        
        # 步骤3: 生成 Embedding
        step3 = tracker.add_step("generate_embeddings", "生成文档向量")
        step3.start()
        
        contents = [c["content"] for c in chunks]
        vectors = embed_batch(contents)
        
        for chunk, vector in zip(chunks, vectors):
            chunk["vector"] = vector
        
        step3.complete({
            "vector_dimension": len(vectors[0]) if vectors else 0,
            "total_vectors": len(vectors)
        })
        
        # 步骤4: 存入 LanceDB
        step4 = tracker.add_step("store_vectors", "存入向量数据库")
        step4.start()
        
        insert_documents(chunks)
        
        step4.complete({"stored_count": len(chunks)})

        tracker.set_extra(email_count=len(emails), chunk_count=len(chunks))
        log.info(f"email_import_done emails={len(emails)} chunks={len(chunks)}")
        tracker.flush()
        
        return {
            "status": "ok",
            "imported_emails": len(emails),
            "total_chunks": len(chunks),
            "steps": tracker.to_list()
        }
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"email_import_failed count={request.count} error={e}")
        tracker.flush(status="error")
        raise HTTPException(500, f"导入失败: {str(e)}")


@app.post("/api/search", response_model=SearchResponse)
async def search(request: SearchRequest):
    """向量相似度搜索（带步骤追踪）"""
    log.info(f"search_start query={request.query!r} top_k={request.top_k} file_type={request.file_type}")
    if not request.query.strip():
        raise HTTPException(400, "查询内容不能为空")
    
    tracker = StepTracker(operation_type="search")
    tracker.set_extra(
        query=request.query,
        top_k=request.top_k,
        file_type_filter=request.file_type or "",
    )
    
    try:
        # 步骤1: 接收查询
        step1 = tracker.add_step("receive_query", "接收搜索请求")
        step1.start()
        step1.complete({
            "query": request.query,
            "top_k": request.top_k,
            "file_type_filter": request.file_type
        })
        
        # 步骤2: 预处理查询
        step2 = tracker.add_step("preprocess", "预处理查询文本")
        step2.start()
        
        query_clean = request.query.strip()
        query_length = len(query_clean)
        
        step2.complete({
            "cleaned_query": query_clean,
            "query_length": query_length
        })
        
        # 步骤3: 生成查询向量
        step3 = tracker.add_step("embed_query", "生成查询向量 (Embedding)")
        step3.start()
        
        query_vector = embed_query(query_clean)
        
        step3.complete({
            "model": EMBED_MODEL_NAME,
            "vector_dimension": len(query_vector),
            "vector_preview_first5": [round(v, 4) for v in query_vector[:5]],
            "vector_preview_last5": [round(v, 4) for v in query_vector[-5:]],
            "vector_magnitude": round(sum(v**2 for v in query_vector)**0.5, 4)
        })
        
        # 步骤4: LanceDB 查询准备
        step4 = tracker.add_step("lanceDB_prepare", "LanceDB 查询准备")
        step4.start()
        
        # 构建过滤条件
        filter_expr = None
        if request.file_type:
            filter_expr = f"file_type = '{request.file_type}'"
        
        step4.complete({
            "table_name": "documents",
            "distance_metric": "余弦距离 (cosine)",
            "index_type": "无索引 → 全量扫描所有行",
            "filter": filter_expr or "无过滤"
        })
        
        # 步骤5: LanceDB 向量检索
        step5 = tracker.add_step("lanceDB_search", "LanceDB 向量检索 (余弦距离)")
        step5.start()
        
        results = search_similar(query_vector, top_k=request.top_k, filter_expr=filter_expr)
        
        # 构建检索结果摘要
        search_summary = []
        for r in results[:3]:  # 展示前3个结果
            search_summary.append({
                "filename": r["filename"],
                "distance": round(r["distance"], 4),
                "similarity": round(r["score"], 4),
                "content_preview": r["content"][:50] + "..."
            })
        
        step5.complete({
            "scan_method": "全量余弦距离计算",
            "total_vectors": "所有文档向量",
            "returned_count": len(results),
            "score_formula": "similarity = 1 / (1 + distance)",
            "top3_results": search_summary
        })
        
        # 步骤6: 结果过滤与排序
        step6 = tracker.add_step("filter_results", "结果过滤与排序")
        step6.start()
        
        # 过滤掉低分结果
        filtered_results = [r for r in results if r["score"] > 0.3]

        annotate_results(request.query, filtered_results)

        step6.complete({
            "input_count": len(results),
            "output_count": len(filtered_results),
            "score_threshold": 0.3,
            "removed_count": len(results) - len(filtered_results),
            "final_results": [
                {"rank": i+1, "file": r["filename"], "score": round(r["score"], 4)}
                for i, r in enumerate(filtered_results[:5])
            ]
        })

        tracker.set_extra(returned_count=len(filtered_results), raw_count=len(results))
        log.info(f"search_done query={request.query!r} returned={len(filtered_results)}")
        tracker.flush()
        
        return SearchResponse(
            query=request.query,
            results=filtered_results,
            steps=tracker.to_list()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"search_failed query={request.query!r} error={e}")
        tracker.flush(status="error")
        raise HTTPException(500, f"搜索失败: {str(e)}")


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """智能问答（RAG）"""
    log.info(f"chat_start query={request.query!r} top_k={request.top_k} mode={'stream' if request.stream else 'sync'}")
    if not request.query.strip():
        raise HTTPException(400, "查询内容不能为空")
    
    tracker = StepTracker(operation_type="chat")
    tracker.set_extra(query=request.query, top_k=request.top_k, mode="stream" if request.stream else "sync")
    
    try:
        # 步骤1: 接收问题
        step1 = tracker.add_step("receive_question", "接收用户问题")
        step1.start()
        step1.complete({"query": request.query})
        
        # 步骤2: 检索相关文档
        step2 = tracker.add_step("retrieve_docs", "检索相关文档")
        step2.start()
        
        query_vector = embed_query(request.query)
        search_results = search_similar(query_vector, top_k=request.top_k)
        annotate_results(request.query, search_results)
        
        # 构建上下文
        context_parts = []
        for i, r in enumerate(search_results):
            source_info = f"[来源{i+1}] {r['filename']}"
            if r.get('metadata', {}).get('subject'):
                source_info += f" - {r['metadata']['subject']}"
            context_parts.append(f"{source_info}\n{r['content']}")
        
        context = "\n\n---\n\n".join(context_parts)
        
        step2.complete({
            "retrieved_count": len(search_results),
            "context_length": len(context),
            "sources": [r['filename'] for r in search_results]
        })

        tracker.set_extra(retrieved_count=len(search_results), context_length=len(context))
        
        # 步骤3: 调用 LLM 生成回答
        step3 = tracker.add_step("generate_answer", "调用 LLM 生成回答")
        step3.start()
        
        messages = build_rag_prompt(request.query, context)
        llm_client = get_llm_client()
        
        if request.stream:
            # 流式输出
            step3.complete({"mode": "stream"})
            
            async def generate():
                # 先发送步骤信息
                yield f"data: {json.dumps({'type': 'steps', 'data': tracker.to_list()})}\n\n"
                
                # 流式输出回答
                async for chunk in await llm_client.chat(messages, stream=True):
                    yield f"data: {json.dumps({'type': 'content', 'data': chunk})}\n\n"
                
                # 发送来源信息
                yield f"data: {json.dumps({'type': 'sources', 'data': search_results})}\n\n"
                yield "data: [DONE]\n\n"
                tracker.flush()
            
            return StreamingResponse(generate(), media_type="text/event-stream")
        else:
            # 非流式输出
            answer = await llm_client.chat(messages, stream=False)
            
            step3.complete({
                "answer_length": len(answer),
                "model": llm_client.model
            })

            tracker.flush()
            
            return ChatResponse(
                query=request.query,
                answer=answer,
                sources=search_results,
                steps=tracker.to_list()
            )
    
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"chat_failed query={request.query!r} error={e}")
        tracker.flush(status="error")
        raise HTTPException(500, f"问答失败: {str(e)}")


@app.get("/api/documents")
async def get_documents(file_type: str = None):
    """获取已上传的文档列表"""
    docs = list_documents(file_type)
    
    # 添加文件大小信息
    for doc in docs:
        filename = doc.get('filename', '')
        # 普通文件从 uploads 目录获取大小
        file_path = os.path.join(UPLOAD_DIR, filename)
        if os.path.exists(file_path):
            doc['file_size'] = os.path.getsize(file_path)
        else:
            # 邮件文件从数据库获取内容大小
            doc['file_size'] = None
    
    return docs


@app.delete("/api/documents/{filename}")
async def remove_document(filename: str):
    """删除指定文档"""
    count = delete_document(filename)
    
    # 同时删除上传的文件
    file_path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    
    return {"filename": filename, "deleted_chunks": count}


@app.get("/api/documents/{filename}/open")
async def open_document(filename: str):
    """打开文档（返回文件内容供浏览器查看）"""
    from fastapi.responses import HTMLResponse, FileResponse
    from email_db import get_email_by_id
    
    # 检查是否是邮件文件（email_xxx.eml）
    if filename.startswith("email_") and filename.endswith(".eml"):
        # 从数据库读取邮件内容
        try:
            email_id = int(filename.replace("email_", "").replace(".eml", ""))
            email = get_email_by_id(email_id)
            
            if not email:
                raise HTTPException(404, f"邮件不存在: {filename}")
            
            # 格式化邮件内容为 HTML
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>{email.get('subject', '无主题')}</title>
                <style>
                    body {{ font-family: -apple-system, sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; }}
                    .header {{ background: #f5f5f5; padding: 15px; border-radius: 8px; margin-bottom: 20px; }}
                    .field {{ margin: 8px 0; }}
                    .label {{ font-weight: bold; color: #666; }}
                    .body {{ line-height: 1.6; white-space: pre-wrap; }}
                </style>
            </head>
            <body>
                <div class="header">
                    <div class="field"><span class="label">📧 主题:</span> {email.get('subject', '无主题')}</div>
                    <div class="field"><span class="label">👤 发件人:</span> {email.get('sender_name', '')} &lt;{email.get('sender', '')}&gt;</div>
                    <div class="field"><span class="label">📥 收件人:</span> {email.get('recipients', '')}</div>
                    <div class="field"><span class="label">📅 时间:</span> {email.get('received_at', '')}</div>
                    {f'<div class="field"><span class="label">📎 附件:</span> {email.get("attachment_names", "")}</div>' if email.get('has_attachments') else ''}
                </div>
                <div class="body">{email.get('body', '无内容')}</div>
            </body>
            </html>
            """
            
            return HTMLResponse(content=html_content)
            
        except (ValueError, Exception) as e:
            raise HTTPException(500, f"读取邮件失败: {str(e)}")
    
    # 普通文件：从 uploads 目录读取
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(404, f"文件不存在: {filename}")
    
    # 根据文件类型设置 Content-Type
    ext = Path(filename).suffix.lower()
    content_types = {
        '.txt': 'text/plain',
        '.md': 'text/markdown',
        '.pdf': 'application/pdf',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.eml': 'message/rfc822',
    }
    
    content_type = content_types.get(ext, 'application/octet-stream')
    
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=content_type
    )


@app.get("/api/documents/{filename}/show-in-finder")
async def show_in_finder(filename: str):
    """在 Finder 中显示文件"""
    # 邮件文件不支持 Finder 显示
    if filename.startswith("email_") and filename.endswith(".eml"):
        raise HTTPException(400, "邮件数据存储在数据库中，不支持在 Finder 中显示")
    
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(404, f"文件不存在: {filename}")
    
    import subprocess
    
    # macOS: 使用 open -R 在 Finder 中显示文件
    try:
        subprocess.run(['open', '-R', file_path], check=True)
        return {"status": "ok", "message": f"已在 Finder 中显示: {filename}"}
    except subprocess.CalledProcessError as e:
        raise HTTPException(500, f"无法在 Finder 中显示: {str(e)}")


@app.get("/api/stats")
async def stats():
    """获取数据库统计 + 性能指标"""
    doc_stats = get_stats()
    email_stats = get_email_stats()

    lancedb_path = os.path.join(os.path.dirname(__file__), "..", "data", "lancedb")
    search_summary = metrics_db.get_summary("search")
    chat_summary = metrics_db.get_summary("chat")
    insert_throughput = metrics_db.get_insert_throughput()

    return {
        "documents": doc_stats,
        "emails": email_stats,
        "embedder": get_model_info(),
        "code_embedder": _get_code_embedder_info(),
        "performance": {
            "lancedb_disk_bytes": metrics_db.get_disk_usage(lancedb_path),
            "search": search_summary,
            "chat": chat_summary,
            "insert": insert_throughput,
        },
    }


@app.get("/api/performance/trend")
async def performance_trend(type: str = Query("search"), days: int = Query(7, ge=1, le=90)):
    """按天聚合趋势数据，给前端折线图用"""
    return {
        "type": type,
        "days": days,
        "trend": metrics_db.get_trend(type, days=days),
    }


@app.get("/api/performance/breakdown")
async def performance_breakdown(type: str = Query("search"), days: int = Query(0, ge=0, le=90)):
    """按 step 拆分耗时，定位瓶颈在哪一步"""
    since = days if days > 0 else None
    return {
        "type": type,
        "since_days": since,
        "breakdown": metrics_db.get_step_breakdown(type, since_days=since),
    }


@app.get("/api/performance/baselines")
async def performance_baselines(limit: int = Query(20, ge=1, le=200)):
    """列出所有压测基线快照"""
    return {"baselines": metrics_db.list_baselines(limit=limit)}


@app.get("/api/lancedb/inspect")
async def lancedb_inspect_overview():
    """LanceDB 表概览：schema/行数/版本/fragments/indices"""
    return lancedb_inspect.inspect_overview()


@app.get("/api/lancedb/rows")
async def lancedb_list_rows(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    file_type: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    include_full_vector: bool = Query(False),
):
    """分页浏览 LanceDB 表内数据，可按 file_type 过滤或按关键词模糊搜"""
    return lancedb_inspect.list_rows(
        limit=limit, offset=offset,
        file_type=file_type, keyword=keyword,
        include_full_vector=include_full_vector,
    )


class DemoInsertRequest(BaseModel):
    text: str
    chunk_size: int = 500
    overlap: int = 50


class DemoSearchRequest(BaseModel):
    query: str
    top_k: int = 5
    score_threshold: float = 0.3


@app.post("/api/lancedb/demo/insert")
async def lancedb_demo_insert(req: DemoInsertRequest):
    """演示存入流程（sandbox：不写主表）"""
    try:
        return lancedb_inspect.demo_insert(req.text, chunk_size=req.chunk_size, overlap=req.overlap)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/lancedb/demo/search")
async def lancedb_demo_search(req: DemoSearchRequest):
    """演示搜索流程（真实只读路径，每步详细中间数据）"""
    try:
        return lancedb_inspect.demo_search(req.query, top_k=req.top_k, score_threshold=req.score_threshold)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/emails")
async def get_emails(folder: str = None, limit: int = 100):
    """获取邮件列表"""
    emails = get_all_emails(folder=folder, limit=limit)
    return {
        "emails": emails,
        "total": len(emails)
    }


@app.get("/api/emails/search")
async def search_email_api(q: str = Query(...), limit: int = 20):
    """搜索邮件"""
    results = search_emails(q, limit=limit)
    return {
        "query": q,
        "results": results,
        "total": len(results)
    }


# ========== 静态文件服务 ==========

# 挂载前端静态文件
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


@app.get("/")
async def index():
    """返回前端页面"""
    return FileResponse(os.path.join(frontend_dir, "index.html"))


# ========== 启动入口 ==========

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
