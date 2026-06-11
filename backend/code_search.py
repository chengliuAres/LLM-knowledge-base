"""代码搜索层 - 语义优先 + 多路召回 + 匹配层级提权

支持三种模式:
- vector: 纯向量搜索 (语义)
- keyword: 纯关键词搜索 (精确)
- hybrid: 混合搜索 + RRF 融合 (默认)

中文查询自动翻译为英文关键词，三路召回融合：
  路径1: 向量搜索（每个关键词分别 embed，递减权重 RRF）     权重 1.0
  路径2: keyword_dual — 英文 FTS5 + 中文 FTS5 双路           权重 0.5
  路径3: 符号名 LIKE 搜索（兜底 FTS5 驼峰拆分盲区）           权重 1.5
  匹配层级提权：文件名 > 类名 > 方法名 > 语义近似
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


# ── 驼峰拆词（搜索侧，用于将英文 query 拆成子词做 symbol LIKE 匹配） ──


def _split_camel_case(name: str) -> list[str]:
    """驼峰命名拆分为独立单词列表

    GHMineViewController → ['GH', 'Mine', 'View', 'Controller']
    mineviewcontroller → ['mineviewcontroller']（全小写无法拆，原样返回）
    """
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', name)
    s = re.sub(r'([a-z])([A-Z])', r'\1 \2', s)
    parts = s.split()
    return parts if len(parts) > 1 else [name]


# ── RRF 融合 ─────────────────────────────────────────────────────

RRF_K = 60  # RRF 公式常量
# 向量结果最低相似度阈值。score = (1 + 余弦相似度) / 2，所以 0.5 = 正交(完全不相关)。
# 设 0.5 表示只保留与查询「正相关」的向量结果，砍掉「最近邻但语义无关」的长尾噪声。
# 可按实际分数分布调高(更严)或调低(更宽)。
MIN_VECTOR_SIMILARITY = 0.5

# 多路召回每路关键词数上限——每次 embed/FTS5/LIKE 约 10-20ms，
# 翻译层可能产出较多关键词（词典展开、LLM 翻译等），设上限避免串行检索延迟线性膨胀。
MAX_KEYWORDS = 5


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


# ── 文件级去重 ─────────────────────────────────────────────────────

def _dedup_by_file(results: list[dict]) -> list[dict]:
    """按 repo_name::file_path 去重，每组只保留排序分数最高的一条

    hybrid 模式用 rrf_score，其他模式用 score。
    """
    if not results:
        return results
    best_by_file: dict[str, dict] = {}
    for r in results:
        repo = r.get("repo_name") or ""
        fname = r.get("file_path") or r.get("file_name") or ""
        dedup_key = f"{repo}::{fname}"
        # hybrid 模式优先用 rrf_score，其他模式用 score
        r_score = r.get("rrf_score") or r.get("score", 0)
        cur = best_by_file.get(dedup_key)
        cur_score = (cur.get("rrf_score") or cur.get("score", 0)) if cur else 0
        if cur is None or r_score > cur_score:
            best_by_file[dedup_key] = r
    return list(best_by_file.values())


# ── 匹配层级提权 ─────────────────────────────────────────────────

def _apply_match_boost(results: list[dict], keywords: list[str]) -> list[dict]:
    """按匹配层级提权：文件名 > 类名 > 方法名 > 语义近似

    提权通过调整 rrf_score / score 实现：
    - 文件名匹配: 1.5x（文件名是最强信号）
    - 类名匹配 (interface/class/file): 1.4x
    - 方法名匹配 (implementation): 1.2x
    - 多词匹配叠加：每多匹配一个关键词 +0.2x（匹配越多区分度越高）
    多个提权可叠加。
    """
    if not keywords:
        return results

    kw_lower = [k.lower() for k in keywords]

    for r in results:
        boost = 1.0
        file_path = (r.get("file_path") or "").lower()
        symbol_name = (r.get("symbol_name") or "").lower()
        chunk_type = r.get("chunk_type") or ""

        # 文件名匹配（最高优先级）
        file_name = file_path.split("/")[-1] if "/" in file_path else file_path
        file_kw_hits = sum(1 for kw in kw_lower if kw in file_name)
        if file_kw_hits > 0:
            boost *= 1.5

        # 符号名匹配
        sym_kw_hits = sum(1 for kw in kw_lower if kw in symbol_name)
        if sym_kw_hits > 0:
            if chunk_type in ("interface", "class", "file"):
                boost *= 1.4
            elif chunk_type == "implementation":
                boost *= 1.2

        # 多词匹配叠加：匹配的关键词越多，区分度越高，额外提权
        # 例如 GHMineViewController 匹配 mine+viewcontroller+view(3词) > ViewController 匹配 viewcontroller+view(2词)
        total_kw_hits = file_kw_hits + sym_kw_hits
        if total_kw_hits > 1:
            boost *= 1.0 + 0.2 * (total_kw_hits - 1)

        if boost > 1.0:
            r["rrf_score"] = r.get("rrf_score", 0) * boost
            r["score"] = r.get("score", 0) * boost
            r["match_boost"] = boost

    results.sort(key=lambda x: x.get("rrf_score") or x.get("score", 0), reverse=True)
    return results


# ── match_reason 生成 ─────────────────────────────────────────────

def _generate_match_reason(item: dict, query: str, mode: str, translated_keywords: Optional[list[str]] = None) -> str:
    """生成匹配原因描述"""
    source = item.get("source", "")
    symbol = item.get("symbol_name", "")

    if mode == "vector":
        reason = "语义相似"
    elif mode == "keyword":
        if symbol and query.strip().lower() in symbol.lower():
            reason = f"符号匹配: {symbol}"
        else:
            reason = f"关键词匹配: {query.strip()}"
    else:
        # hybrid
        if source == "symbol":
            kws = item.get("matched_keywords", translated_keywords or [])
            reason = f"符号匹配: {', '.join(kws[:3])}" if kws else "符号匹配"
        elif source == "keyword":
            if symbol and query.strip().lower() in symbol.lower():
                reason = f"符号匹配: {symbol}"
            else:
                reason = f"关键词匹配: {query.strip()}"
        elif source == "vector":
            reason = "语义相似"
        else:
            reason = "混合匹配"

    # 提权信息
    boost = item.get("match_boost", 1.0)
    if boost > 1.0:
        boost_parts = []
        kw_lower = [k.lower() for k in (translated_keywords or [query])]
        fp = (item.get("file_path") or "").lower()
        sn = (item.get("symbol_name") or "").lower()
        fn = fp.split("/")[-1] if "/" in fp else fp
        if any(kw in fn for kw in kw_lower):
            boost_parts.append("文件名")
        if any(kw in sn for kw in kw_lower):
            boost_parts.append("符号名")
        if boost_parts:
            reason += f" ({'+'.join(boost_parts)}匹配提权)"

    return reason


# ── 向量搜索辅助 ──────────────────────────────────────────────────

def _vector_search_per_keyword(
    keywords: list[str],
    top_k: int,
    repo_name=None, language=None, chunk_type=None, file_path=None,
) -> tuple[list[dict], list[float]]:
    """每个关键词分别 embed + 向量搜索，返回 (结果列表, 权重列表)

    权重递减：第一个关键词 2.0，后续 0.5。
    只有一路结果时返回 weights=[1.0]。
    """
    from code_embedder import embed_query

    vec_per_kw = []
    for kw in keywords:
        vec = embed_query(kw)
        results = search_vector(
            query_vector=vec, top_k=top_k,
            repo_name=repo_name, language=language,
            chunk_type=chunk_type, file_path=file_path,
        )
        results = [r for r in results if r.get("score", 0) >= MIN_VECTOR_SIMILARITY]
        if results:
            vec_per_kw.append(results)

    if not vec_per_kw:
        return [], []

    # 递减权重：首词最重要
    weights = [2.0] + [0.5] * (len(vec_per_kw) - 1)

    if len(vec_per_kw) == 1:
        return vec_per_kw[0], [1.0]

    fused = rrf_fusion(*vec_per_kw, top_k=top_k, weights=weights)
    return fused, weights


# ── FTS5 双路搜索辅助 ────────────────────────────────────────────

def _keyword_search_dual(
    query: str,
    translated_keywords: list[str],
    top_k: int,
    repo_name=None, language=None, chunk_type=None, file_path=None, symbol_name=None,
) -> list[dict]:
    """英文 FTS5 + 中文 FTS5 双路搜索

    英文 FTS5：用翻译后的关键词搜（精确匹配代码标识符），权重 1.0
    中文 FTS5：用原始中文 query 搜（命中注释/字符串中的中文），权重 0.3
    无翻译时只走原始 query 的 FTS5。
    """
    if translated_keywords:
        # 英文 FTS5：每个关键词分别搜，合并去重（关键词数上限控制串行检索延迟）
        fts_keywords = translated_keywords[:MAX_KEYWORDS]
        en_fts = []
        for kw in fts_keywords:
            results = search_keyword(
                query=kw, top_k=max(top_k // len(fts_keywords), 20),
                repo_name=repo_name, language=language,
                chunk_type=chunk_type, file_path=file_path, symbol_name=symbol_name,
            )
            en_fts.extend(results)
        # 去重
        seen = set()
        deduped = []
        for r in en_fts:
            if r["id"] not in seen:
                seen.add(r["id"])
                deduped.append(r)
        en_fts = deduped[:top_k]

        # 中文 FTS5
        cn_fts = search_keyword(
            query=query, top_k=top_k,
            repo_name=repo_name, language=language,
            chunk_type=chunk_type, file_path=file_path, symbol_name=symbol_name,
        )

        # 两路 RRF 融合
        if en_fts and cn_fts:
            return rrf_fusion(en_fts, cn_fts, top_k=top_k, weights=[1.0, 0.3])
        return en_fts or cn_fts
    else:
        # 无翻译：只走原始 query
        return search_keyword(
            query=query, top_k=top_k,
            repo_name=repo_name, language=language,
            chunk_type=chunk_type, file_path=file_path, symbol_name=symbol_name,
        )


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

    # ── 查询翻译（中文 → 英文关键词） ──
    translated_keywords = []
    translation_info = None
    if _has_chinese(query):
        step_trans = None
        if tracker:
            step_trans = tracker.add_step("query_translate", "查询翻译: 中文→英文关键词")
            step_trans.start()

        from query_translator import translate_query_sync
        translation = translate_query_sync(query, use_llm=True, timeout=3.0, tracker=tracker)
        translated_keywords = translation.translated
        translation_info = {
            "original": translation.original,
            "translated": translated_keywords,
            "method": translation.method,
            "confidence": translation.confidence,
            "duration_ms": getattr(translation, "duration_ms", 0.0),
            "steps": getattr(translation, "steps", []) or [],
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

        if translated_keywords:
            # 每个关键词分别 embed + RRF（修复 join embed 语义稀释）
            # 关键词数上限与 hybrid 模式一致，避免串行 embed 延迟线性膨胀
            vector_kw = translated_keywords[:MAX_KEYWORDS]
            results, _ = _vector_search_per_keyword(
                vector_kw, top_k,
                repo_name=repo_name, language=language,
                chunk_type=chunk_type, file_path=file_path,
            )
            if not results:
                # 降级：用原始 query
                query_vec = embed_query(query)
                results = search_vector(
                    query_vector=query_vec, top_k=top_k,
                    repo_name=repo_name, language=language,
                    chunk_type=chunk_type, file_path=file_path,
                )
                results = [r for r in results if r.get("score", 0) >= MIN_VECTOR_SIMILARITY]
        else:
            query_vec = embed_query(query)
            results = search_vector(
                query_vector=query_vec, top_k=top_k,
                repo_name=repo_name, language=language,
                chunk_type=chunk_type, file_path=file_path,
            )
            results = [r for r in results if r.get("score", 0) >= MIN_VECTOR_SIMILARITY]

        # 匹配层级提权
        boost_kw = translated_keywords if translated_keywords else ([query] if query else [])
        results = _apply_match_boost(results, boost_kw)

        # 文件级去重
        results = _dedup_by_file(results)

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

        # 文件级去重
        results = _dedup_by_file(results)

        if tracker:
            step.complete({"results_count": len(results)})

    else:
        # ── hybrid: 语义优先 + 多路召回 + 匹配层级提权 ──
        from code_embedder import embed_query

        if tracker:
            step_hybrid = tracker.add_step("hybrid_search", "混合搜索 (向量+关键词+符号)")
            step_hybrid.start()

        pool_k = max(top_k * 5, 100)

        # 1. 向量搜索（每个关键词分别 embed，递减权重 RRF）
        #    关键词数设上限避免串行检索延迟线性膨胀（每次 embed 约 10-20ms）
        search_keywords = translated_keywords[:MAX_KEYWORDS] if translated_keywords else []
        if search_keywords:
            vector_results, _ = _vector_search_per_keyword(
                search_keywords, pool_k,
                repo_name=repo_name, language=language,
                chunk_type=chunk_type, file_path=file_path,
            )
        else:
            query_vec = embed_query(query)
            vector_results = search_vector(
                query_vector=query_vec, top_k=pool_k,
                repo_name=repo_name, language=language,
                chunk_type=chunk_type, file_path=file_path,
            )
            vector_results = [r for r in vector_results if r.get("score", 0) >= MIN_VECTOR_SIMILARITY]

        # 2. FTS5 搜索（英文 + 中文双路）
        keyword_results = _keyword_search_dual(
            query, translated_keywords, pool_k,
            repo_name=repo_name, language=language,
            chunk_type=chunk_type, file_path=file_path, symbol_name=symbol_name,
        )

        # 3. 符号名 LIKE 搜索（最精准的标识符匹配路径）
        #    - 中文 query：用翻译后的英文 keywords（同向量/FTS5 上限）
        #    - 英文 query：原 query + camelCase 拆词子词（原 query 保证完整标识符匹配）
        symbol_keywords = []
        if translated_keywords:
            symbol_keywords = translated_keywords[:MAX_KEYWORDS]
        elif query and not _has_chinese(query):
            # 英文 query：原 query 放首位（保证完整匹配），再加拆词子词
            camel_parts = _split_camel_case(query)
            if camel_parts != [query]:
                # 拆出了子词：原 query + 子词（过滤 < 3 字符的短词避免噪声，上限 MAX_KEYWORDS）
                long_parts = [p for p in camel_parts if len(p) >= 3]
                symbol_keywords = ([query] + long_parts)[:MAX_KEYWORDS]
            else:
                # 全小写/无法拆词：只用原 query
                symbol_keywords = [query]

        symbol_results = []
        if symbol_keywords:
            symbol_results = search_symbol_by_keywords(
                keywords=symbol_keywords,
                top_k=pool_k,
                repo_name=repo_name,
                language=language,
                chunk_type=chunk_type,
                file_path=file_path,
                symbol_name=symbol_name,
            )

        if tracker:
            step_hybrid.complete({
                "vector_hits": len(vector_results),
                "keyword_hits": len(keyword_results),
                "symbol_hits": len(symbol_results),
                "translated_keywords": translated_keywords,
                "symbol_keywords": symbol_keywords,
            })
            step_rrf = tracker.add_step("rrf_fusion", "RRF 融合排序 (向量+FTS5+符号)")
            step_rrf.start()

        # 4. 扁平 RRF 融合（向量 + FTS5 + 符号，一次融合）
        #    权重：向量 1.0 / FTS5 0.5 / 符号 1.5（符号最精准，最高权重）
        results = rrf_fusion(
            vector_results, keyword_results, symbol_results,
            top_k=top_k * 2,
            weights=[1.0, 0.5, 1.5],
        )

        # 5. 来源标注
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

        # 6. 匹配层级提权
        boost_kw = symbol_keywords if symbol_keywords else (translated_keywords if translated_keywords else ([query] if query else []))
        results = _apply_match_boost(results, boost_kw)

        # 7. 文件级去重 + 截断（先去重再截断，避免同文件重复挤占多样性）
        results = _dedup_by_file(results)
        results = results[:top_k]

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
