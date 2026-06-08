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


# ── 中文检测 ───────────────────────────────────────────────────────

_CN_PATTERN = re.compile(r'[一-龥㐀-䶿豈-﫿]+')


def _has_chinese(text: str) -> bool:
    """检测文本是否包含中文"""
    return bool(_CN_PATTERN.search(text)) if text else False


# ── RRF 融合 ─────────────────────────────────────────────────────

RRF_K = 60  # RRF 公式常量
MIN_VECTOR_SIMILARITY = 0.3  # 向量搜索结果最低相似度阈值


def rrf_fusion(vector_results: list[dict], keyword_results: list[dict],
                top_k: int = 10, query: Optional[str] = None) -> list[dict]:
    """RRF (Reciprocal Rank Fusion) 融合排序

    score = 1 / (k + rank), k=60
    同一 chunk_id 两路都命中则分数相加。
    中文查询时关键词结果获得 1.8x 权重（补偿向量模型对中文代码效果差的问题）。
    """
    scores = {}   # chunk_id → rrf_score
    items = {}    # chunk_id → item_dict

    # 中文查询：关键词加权 1.8x
    keyword_weight = 1.8 if (query and _has_chinese(query)) else 1.0

    # 向量搜索结果
    for rank, item in enumerate(vector_results, start=1):
        cid = item["id"]
        rrf = 1.0 / (RRF_K + rank)
        scores[cid] = scores.get(cid, 0) + rrf
        items[cid] = item

    # 关键词搜索结果 (中文查询加权)
    for rank, item in enumerate(keyword_results, start=1):
        cid = item["id"]
        rrf = keyword_weight / (RRF_K + rank)
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

        from code_embedder import embed_code_query
        query_vec = embed_code_query(query)

        results = search_vector(
            query_vector=query_vec,
            top_k=top_k,
            repo_name=repo_name,
            language=language,
            chunk_type=chunk_type,
            file_path=file_path,
        )

        # 过滤低质量向量结果
        results = [r for r in results if r.get("score", 0) >= MIN_VECTOR_SIMILARITY]

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
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from code_embedder import embed_code_query

        if tracker:
            step_hybrid = tracker.add_step("hybrid_search", "混合搜索 (向量+关键词 并行)")
            step_hybrid.start()

        def _vector_search():
            query_vec = embed_code_query(query)
            return search_vector(
                query_vector=query_vec, top_k=top_k,
                repo_name=repo_name, language=language,
                chunk_type=chunk_type, file_path=file_path,
            )

        def _keyword_search():
            return search_keyword(
                query=query, top_k=top_k,
                repo_name=repo_name, language=language,
                chunk_type=chunk_type, file_path=file_path,
                symbol_name=symbol_name,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(_vector_search): "vector",
                executor.submit(_keyword_search): "keyword",
            }
            results_map = {}
            for future in as_completed(futures):
                results_map[futures[future]] = future.result()

        vector_results = results_map.get("vector", [])
        keyword_results = results_map.get("keyword", [])

        if tracker:
            step_hybrid.complete({
                "vector_hits": len(vector_results),
                "keyword_hits": len(keyword_results),
            })
            step_rrf = tracker.add_step("rrf_fusion", "RRF 融合排序")
            step_rrf.start()

        results = rrf_fusion(vector_results, keyword_results, top_k=top_k, query=query)

        # 标注来源: 在融合结果中判断每个 chunk 是哪路命中的
        vec_ids = {r["id"] for r in vector_results}
        kw_ids = {r["id"] for r in keyword_results}
        filtered = []
        for r in results:
            cid = r["id"]
            if cid in vec_ids and cid in kw_ids:
                r["source"] = "both"
            elif cid in vec_ids:
                r["source"] = "vector"
            else:
                r["source"] = "keyword"
            # 过滤仅向量命中且低相似度的结果
            if r["source"] == "vector" and r.get("score", 0) < MIN_VECTOR_SIMILARITY:
                continue
            filtered.append(r)
        results = filtered

        if tracker:
            step_rrf.complete({
                "vector_hits": len(vector_results),
                "keyword_hits": len(keyword_results),
                "merged": len(results),
            })

    # match_reason
    for r in results:
        r["match_reason"] = _generate_match_reason(r, query, mode)
        # parent_symbol_id: 所在类/协议的 chunk id
        parent_class = r.get("metadata", {}).get("parent_class", "")
        if parent_class:
            r["parent_symbol_id"] = f"{r['repo_name']}_{r['file_path']}___{parent_class}_0"
        else:
            r["parent_symbol_id"] = None

    return {
        "query": query,
        "mode": mode,
        "results": results,
        "steps": tracker.to_list() if tracker else [],
    }


# ── 调用链追踪 ──────────────────────────────────────────────────────

def trace_code(
    symbol_name: str,
    repo_name: str = "",
    direction: str = "both",
    depth: int = 2,
    tracker: Optional[StepTracker] = None,
) -> dict:
    """追踪符号的调用链

    先混搜定位符号 → 再查 code_relations 表做多跳追踪。
    搜索找到的每个相关符号都会做一次 trace_chain。

    Args:
        symbol_name: 要追踪的符号名或搜索查询
        repo_name: 仓库名过滤
        direction: "callers" / "callees" / "both"
        depth: 追踪跳数 (1-3)
        tracker: 步骤追踪器

    Returns:
        {"query": str, "matched_symbols": [...], "traces": [...], "steps": [...]}
    """
    from code_db import trace_chain, get_callees

    if tracker:
        step_search = tracker.add_step("trace_search", f"搜索起始符号: {symbol_name}")
        step_search.start()

    # 1. 混搜定位符号 (找前 5 个匹配的 chunk 作为起始入口)
    search_result = search_code(
        query=symbol_name,
        mode="hybrid",
        top_k=5,
        repo_name=repo_name or None,
        tracker=None,  # 避免嵌套 tracker
    )

    if tracker:
        step_search.complete({"hits": len(search_result["results"])})

    if not search_result["results"]:
        return {
            "query": symbol_name,
            "matched_symbols": [],
            "traces": [],
            "steps": tracker.to_list() if tracker else [],
        }

    # 2. 对每个匹配的符号做调用链追踪（去重，同一符号名只 trace 一次）
    if tracker:
        step_trace = tracker.add_step("trace_chain", f"追踪调用链: depth={depth}, direction={direction}")
        step_trace.start()

    traced_symbols = set()
    traces = []
    matched_symbols = []

    for r in search_result["results"]:
        sym = r.get("symbol_name", "")
        if not sym or sym in traced_symbols:
            continue
        # 过滤掉文件名被设为 symbol_name 的 file 类型 chunk（非符号）
        if r.get("chunk_type") == "file":
            # file 类型没有具体符号，直接查它的 callee 列表
            callee_list = get_callees(r["id"])
            if callee_list:
                traces.append({
                    "entry_symbol": sym,
                    "entry_file": r["file_path"],
                    "entry_type": "file",
                    "entry_chunk_id": r["id"],
                    "chain": {"nodes": [], "edges": []},
                    "callee_list": callee_list[:20],
                })
                matched_symbols.append({
                    "symbol": sym,
                    "file_path": r["file_path"],
                    "line_start": r.get("line_start", 0),
                    "chunk_type": r.get("chunk_type", ""),
                })
                traced_symbols.add(sym)
            continue

        traced_symbols.add(sym)

        # 执行调用链追踪
        chain = trace_chain(
            symbol_name=sym,
            repo_name=repo_name or r.get("repo_name", ""),
            direction=direction,
            depth=depth,
        )

        traces.append({
            "entry_symbol": sym,
            "entry_file": r["file_path"],
            "entry_type": r.get("chunk_type", ""),
            "entry_chunk_id": r.get("chunk_id", r["id"]),
            "chain": chain.get("chain", {"nodes": [], "edges": []}),
            "direct_callers": chain.get("direct_callers", []),
            "direct_callees": chain.get("direct_callees", []),
        })

        matched_symbols.append({
            "symbol": sym,
            "file_path": r["file_path"],
            "line_start": r.get("line_start", 0),
            "chunk_type": r.get("chunk_type", ""),
            "match_reason": r.get("match_reason", ""),
        })

    if tracker:
        step_trace.complete({"traced": len(traces)})
        tracker.flush()

    return {
        "query": symbol_name,
        "depth": depth,
        "direction": direction,
        "matched_symbols": matched_symbols,
        "traces": traces,
        "steps": tracker.to_list() if tracker else [],
    }
