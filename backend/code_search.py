"""代码搜索层 - 混合搜索 + RRF 融合排序 + 查询翻译

支持三种模式:
- vector: 纯向量搜索 (语义)
- keyword: 纯关键词搜索 (精确)
- hybrid: 混合搜索 + RRF 融合 (默认)

中文查询自动翻译为英文关键词，三路搜索融合：
  路径A: FTS5 关键词搜索（中文 content）
  路径B: 向量搜索（翻译后英文，bge-small-en）
  路径C: 符号名搜索（翻译后英文关键词 LIKE symbol_name）
"""

import re
from typing import Optional
from step_tracker import StepTracker
from code_db import search_vector, search_keyword, search_symbol_by_keywords


# ── 中文检测 ───────────────────────────────────────────────────────

_CN_PATTERN = re.compile(r'[一-龥㐀-䶿豈-﫿]+')


def _has_chinese(text: str) -> bool:
    """检测文本是否包含中文"""
    return bool(_CN_PATTERN.search(text)) if text else False


# ── RRF 融合 ─────────────────────────────────────────────────────

RRF_K = 60  # RRF 公式常量
MIN_VECTOR_SIMILARITY = 0.3  # 向量搜索结果最低相似度阈值


def rrf_fusion(
    *result_lists: list[dict],
    top_k: int = 10,
    weights: Optional[list[float]] = None,
) -> list[dict]:
    """RRF (Reciprocal Rank Fusion) 融合排序 — 支持 N 路结果

    Args:
        *result_lists: N 路搜索结果
        top_k: 返回数量
        weights: 每路的权重（默认全 1.0）
    """
    if weights is None:
        weights = [1.0] * len(result_lists)

    scores = {}   # chunk_id → rrf_score
    items = {}    # chunk_id → item_dict

    for weight, results in zip(weights, result_lists):
        for rank, item in enumerate(results, start=1):
            cid = item["id"]
            rrf = weight / (RRF_K + rank)
            scores[cid] = scores.get(cid, 0) + rrf
            if cid not in items:
                items[cid] = item
            else:
                # 合并 source 标记
                existing_source = items[cid].get("source", "")
                new_source = item.get("source", "")
                if existing_source and new_source and existing_source != new_source:
                    items[cid]["source"] = "both"

    # 按融合分数排序
    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

    result = []
    for cid in sorted_ids[:top_k]:
        item = items[cid].copy()
        item["rrf_score"] = round(scores[cid], 6)
        result.append(item)

    return result


# ── match_reason 生成 ─────────────────────────────────────────────

def _generate_match_reason(item: dict, query: str, mode: str, translated_keywords: Optional[list[str]] = None) -> str:
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
        if source == "symbol":
            kws = item.get("matched_keywords", translated_keywords or [])
            return f"符号匹配: {', '.join(kws[:3])}" if kws else "符号匹配"
        elif source == "keyword":
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
        {\"query\": str, \"mode\": str, \"results\": [...], \"steps\": [...]}
    """
    # top_k 限流
    top_k = max(1, min(top_k, 100))

    # ── 查询翻译（中文 → 英文关键词） ──
    translated_keywords = []
    translation_info = None
    if _has_chinese(query):
        step_trans = None
        if tracker:
            step_trans = tracker.add_step("query_translate", "查询翻译: 中文→英文关键词")
            step_trans.start()

        from query_translator import translate_query_sync
        translation = translate_query_sync(query, use_llm=True, timeout=3.0)
        translated_keywords = translation.translated
        translation_info = {
            "original": translation.original,
            "translated": translated_keywords,
            "method": translation.method,
            "confidence": translation.confidence,
        }

        if tracker and step_trans:
            step_trans.complete({
                "method": translation.method,
                "keywords": translated_keywords,
                "confidence": translation.confidence,
            })

    results = []

    if mode == "vector":
        if tracker:
            step = tracker.add_step("vector_search", "向量搜索 (bge-small-en)")
            step.start()

        from code_embedder import embed_query
        # 向量搜索用翻译后的英文关键词（如果有）
        search_text = " ".join(translated_keywords) if translated_keywords else query
        query_vec = embed_query(search_text)

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
        # ── hybrid: 三路搜索 + RRF ──
        from code_embedder import embed_query

        if tracker:
            step_hybrid = tracker.add_step("hybrid_search", "混合搜索 (向量+关键词+符号名)")
            step_hybrid.start()

        # 路径A: FTS5 关键词搜索（搜原始中文 content）
        keyword_results = search_keyword(
            query=query, top_k=top_k,
            repo_name=repo_name, language=language,
            chunk_type=chunk_type, file_path=file_path,
            symbol_name=symbol_name,
        )

        # 路径B: 向量搜索（用翻译后的英文关键词 embed）
        search_text = " ".join(translated_keywords) if translated_keywords else query
        query_vec = embed_query(search_text)
        vector_results = search_vector(
            query_vector=query_vec, top_k=top_k,
            repo_name=repo_name, language=language,
            chunk_type=chunk_type, file_path=file_path,
        )

        # 路径C: 符号名搜索（翻译后的英文关键词 LIKE symbol_name）
        symbol_results = []
        if translated_keywords:
            symbol_results = search_symbol_by_keywords(
                keywords=translated_keywords, top_k=top_k,
                repo_name=repo_name, language=language,
                chunk_type=chunk_type,
            )

        # 过滤低质量向量结果
        vector_results = [r for r in vector_results if r.get("score", 0) >= MIN_VECTOR_SIMILARITY]

        if tracker:
            step_hybrid.complete({
                "vector_hits": len(vector_results),
                "keyword_hits": len(keyword_results),
                "symbol_hits": len(symbol_results),
                "translated_keywords": translated_keywords,
            })
            step_rrf = tracker.add_step("rrf_fusion", "RRF 融合排序 (3路)")
            step_rrf.start()

        # RRF 融合：向量 1.0x，关键词 1.0x，符号名 1.5x（中文查询时符号名更精准）
        symbol_weight = 1.5 if translated_keywords else 1.0
        results = rrf_fusion(
            vector_results, keyword_results, symbol_results,
            top_k=top_k,
            weights=[1.0, 1.0, symbol_weight],
        )

        # 标注来源
        vec_ids = {r["id"] for r in vector_results}
        kw_ids = {r["id"] for r in keyword_results}
        sym_ids = {r["id"] for r in symbol_results}

        filtered = []
        for r in results:
            cid = r["id"]
            sources = []
            if cid in vec_ids:
                sources.append("vector")
            if cid in kw_ids:
                sources.append("keyword")
            if cid in sym_ids:
                sources.append("symbol")
            r["source"] = "+".join(sources) if len(sources) > 1 else (sources[0] if sources else "unknown")

            # 过滤仅向量命中且低相似度的结果
            if r["source"] == "vector" and r.get("score", 0) < MIN_VECTOR_SIMILARITY:
                continue
            filtered.append(r)
        results = filtered

        if tracker:
            step_rrf.complete({
                "vector_hits": len(vector_results),
                "keyword_hits": len(keyword_results),
                "symbol_hits": len(symbol_results),
                "merged": len(results),
            })

    # match_reason
    for r in results:
        r["match_reason"] = _generate_match_reason(r, query, mode, translated_keywords)
        # parent_symbol_id: 所在类/协议的 chunk id
        parent_class = r.get("metadata", {}).get("parent_class", "")
        if parent_class:
            r["parent_symbol_id"] = f"{r['repo_name']}_{r['file_path']}___{parent_class}_0"
        else:
            r["parent_symbol_id"] = None

    response = {
        "query": query,
        "mode": mode,
        "results": results,
        "steps": tracker.to_list() if tracker else [],
    }
    if translation_info:
        response["translation"] = translation_info

    return response


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
        direction: \"callers\" / \"callees\" / \"both\"
        depth: 追踪跳数 (1-3)
        tracker: 步骤追踪器

    Returns:
        {\"query\": str, \"matched_symbols\": [...], \"traces\": [...], \"steps\": [...]}
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
