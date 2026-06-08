"""代码搜索层 - 混合搜索 + RRF 融合排序

支持三种模式:
- vector: 纯向量搜索 (语义)
- keyword: 纯关键词搜索 (精确)
- hybrid: 混合搜索 + RRF 融合 (默认)
"""

import re
from typing import Optional
from step_tracker import StepTracker
from code_db import search_vector, search_keyword


# ── RRF 融合 ─────────────────────────────────────────────────────

RRF_K = 60  # RRF 公式常量


def rrf_fusion(vector_results: list[dict], keyword_results: list[dict], top_k: int = 10) -> list[dict]:
    """RRF (Reciprocal Rank Fusion) 融合排序

    score = 1 / (k + rank), k=60
    同一 chunk_id 两路都命中则分数相加
    """
    scores = {}   # chunk_id → rrf_score
    items = {}    # chunk_id → item_dict

    # 向量搜索结果
    for rank, item in enumerate(vector_results, start=1):
        cid = item["id"]
        rrf = 1.0 / (RRF_K + rank)
        scores[cid] = scores.get(cid, 0) + rrf
        items[cid] = item

    # 关键词搜索结果
    for rank, item in enumerate(keyword_results, start=1):
        cid = item["id"]
        rrf = 1.0 / (RRF_K + rank)
        scores[cid] = scores.get(cid, 0) + rrf
        if cid not in items:
            items[cid] = item

    # 按融合分数排序
    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

    result = []
    for cid in sorted_ids[:top_k]:
        item = items[cid].copy()
        item["rrf_score"] = round(scores[cid], 6)
        # 保留原始 score (向量相似度或关键词 rank)
        result.append(item)

    return result


# ── match_reason 生成 ─────────────────────────────────────────────

def _generate_match_reason(item: dict, query: str, mode: str) -> str:
    """生成匹配原因描述"""
    source = item.get("source", "")
    symbol = item.get("symbol_name", "")

    if mode == "vector":
        return "语义相似"
    elif mode == "keyword":
        if symbol and query.strip().lower() in symbol.lower():
            return f"符号匹配: {symbol}"
        return f"关键词匹配: {query.strip()}"
    else:
        # hybrid
        if source == "keyword":
            if symbol and query.strip().lower() in symbol.lower():
                return f"符号匹配: {symbol}"
            return f"关键词匹配: {query.strip()}"
        elif source == "vector":
            return "语义相似"
        return "混合匹配"


# ── 主搜索函数 ────────────────────────────────────────────────────

def search_code(
    query: str,
    mode: str = "hybrid",
    top_k: int = 10,
    repo_name: Optional[str] = None,
    project_type: Optional[str] = None,
    language: Optional[str] = None,
    chunk_type: Optional[str] = None,
    file_path: Optional[str] = None,
    symbol_name: Optional[str] = None,
    tracker: Optional[StepTracker] = None,
) -> dict:
    """代码搜索主入口

    Args:
        query: 搜索内容
        mode: vector / keyword / hybrid
        top_k: 返回数量 (1-100)
        repo_name, project_type, language, chunk_type, file_path, symbol_name: 过滤条件
        tracker: 步骤追踪器

    Returns:
        {"query": str, "mode": str, "results": [...], "steps": [...]}
    """
    # top_k 限流
    top_k = max(1, min(top_k, 100))

    results = []

    if mode == "vector":
        if tracker:
            step = tracker.add_step("vector_search", "向量搜索 (LanceDB cosine)")
            step.start()

        from embedder import embed_text
        query_vec = embed_text(query)

        results = search_vector(
            query_vector=query_vec,
            top_k=top_k,
            repo_name=repo_name,
            language=language,
            chunk_type=chunk_type,
            file_path=file_path,
        )

        if tracker:
            step.complete({"results_count": len(results)})

    elif mode == "keyword":
        if tracker:
            step = tracker.add_step("keyword_search", "关键词搜索 (SQLite FTS5)")
            step.start()

        results = search_keyword(
            query=query,
            top_k=top_k,
            repo_name=repo_name,
            language=language,
            chunk_type=chunk_type,
            file_path=file_path,
            symbol_name=symbol_name,
        )

        if tracker:
            step.complete({"results_count": len(results)})

    else:
        # hybrid: 两路并行 + RRF
        if tracker:
            step_vec = tracker.add_step("vector_search", "向量搜索 (LanceDB cosine)")
            step_vec.start()

        from embedder import embed_text
        query_vec = embed_text(query)

        vector_results = search_vector(
            query_vector=query_vec,
            top_k=top_k,
            repo_name=repo_name,
            language=language,
            chunk_type=chunk_type,
            file_path=file_path,
        )

        if tracker:
            step_vec.complete({"results_count": len(vector_results)})
            step_kw = tracker.add_step("keyword_search", "关键词搜索 (SQLite FTS5)")
            step_kw.start()

        keyword_results = search_keyword(
            query=query,
            top_k=top_k,
            repo_name=repo_name,
            language=language,
            chunk_type=chunk_type,
            file_path=file_path,
            symbol_name=symbol_name,
        )

        if tracker:
            step_kw.complete({"results_count": len(keyword_results)})
            step_rrf = tracker.add_step("rrf_fusion", "RRF 融合排序")
            step_rrf.start()

        results = rrf_fusion(vector_results, keyword_results, top_k=top_k)

        # 标注来源: 在融合结果中判断每个 chunk 是哪路命中的
        vec_ids = {r["id"] for r in vector_results}
        kw_ids = {r["id"] for r in keyword_results}
        for r in results:
            cid = r["id"]
            if cid in vec_ids and cid in kw_ids:
                r["source"] = "both"
            elif cid in vec_ids:
                r["source"] = "vector"
            else:
                r["source"] = "keyword"

        if tracker:
            step_rrf.complete({
                "vector_hits": len(vector_results),
                "keyword_hits": len(keyword_results),
                "merged": len(results),
            })

    # 后处理: 结构化过滤 + match_reason
    if project_type:
        results = [r for r in results if r.get("project_type") == project_type]

    for r in results:
        r["match_reason"] = _generate_match_reason(r, query, mode)

    return {
        "query": query,
        "mode": mode,
        "results": results,
        "steps": tracker.to_list() if tracker else [],
    }
