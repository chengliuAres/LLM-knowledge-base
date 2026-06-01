"""LanceDB 内省工具 - 封装 schema/count/fragments/versions 等只读探查 API"""

import json
import time
from typing import Optional

from db import get_table
from embedder import embed_text, embed_batch, _model_name as EMBED_MODEL_NAME
from parser import chunk_text
from match_reasons import explain_match


def inspect_overview() -> dict:
    """表总体概览：schema、行数、版本、fragments、indices"""
    table = get_table()
    ds = table.to_lance()

    schema_fields = []
    vector_dim = None
    for field in ds.schema:
        type_str = str(field.type)
        is_vector = type_str.startswith("fixed_size_list")
        dim = None
        if is_vector:
            dim = field.type.list_size
            vector_dim = dim
        schema_fields.append({
            "name": field.name,
            "type": type_str,
            "is_vector": is_vector,
            "vector_dim": dim,
        })

    fragments = []
    for f in ds.get_fragments():
        fragments.append({
            "id": f.fragment_id,
            "rows": f.count_rows(),
        })

    versions = []
    for v in ds.versions()[-10:]:
        versions.append({
            "version": v["version"],
            "timestamp": v["timestamp"].isoformat() if hasattr(v["timestamp"], "isoformat") else str(v["timestamp"]),
        })

    return {
        "table_name": "documents",
        "total_rows": ds.count_rows(),
        "schema": schema_fields,
        "vector_dim": vector_dim,
        "current_version": ds.version,
        "version_count": len(ds.versions()),
        "recent_versions": versions,
        "fragments": fragments,
        "fragment_count": len(fragments),
        "indices": list(ds.list_indices()),
        "has_index": len(list(ds.list_indices())) > 0,
        "search_strategy": "全量余弦距离扫描" if not list(ds.list_indices()) else "索引检索",
    }


def list_rows(
    limit: int = 20,
    offset: int = 0,
    file_type: Optional[str] = None,
    keyword: Optional[str] = None,
    include_full_vector: bool = False,
) -> dict:
    """分页列出表内数据，可按 file_type 过滤或按 content 关键词模糊搜"""
    table = get_table()
    df = table.to_pandas()

    if file_type:
        df = df[df["file_type"] == file_type]
    if keyword:
        df = df[df["content"].str.contains(keyword, na=False, regex=False)]

    total = len(df)
    df = df.iloc[offset:offset + limit]

    fragment_map = _build_fragment_map(table)

    rows = []
    for _, r in df.iterrows():
        v = list(r["vector"])
        try:
            metadata = json.loads(r.get("metadata", "{}"))
        except Exception:
            metadata = {}
        rows.append({
            "id": r["id"],
            "filename": r["filename"],
            "chunk_index": int(r["chunk_index"]),
            "content": r["content"],
            "content_length": len(r["content"]),
            "file_type": r["file_type"],
            "uploaded_at": r["uploaded_at"],
            "metadata": metadata,
            "vector_dim": len(v),
            "vector_preview": [round(float(x), 4) for x in v[:16]],
            "vector_full": [round(float(x), 6) for x in v] if include_full_vector else None,
            "vector_norm": round(float(sum(x * x for x in v) ** 0.5), 4),
            "fragment_id": fragment_map.get(r["id"]),
        })

    return {
        "total": int(total),
        "offset": offset,
        "limit": limit,
        "rows": rows,
    }


def _build_fragment_map(table) -> dict:
    """从 lance dataset 抽出 id → fragment_id 映射，用于在数据浏览里展示物理存储位置"""
    ds = table.to_lance()
    mapping: dict = {}
    for f in ds.get_fragments():
        try:
            sub = f.to_table(columns=["id"]).to_pandas()
            for _id in sub["id"]:
                mapping[_id] = f.fragment_id
        except Exception:
            pass
    return mapping


def demo_insert(text: str, chunk_size: int = 500, overlap: int = 50) -> dict:
    """演示插入流程（sandbox：不写主表，仅返回每步中间数据）"""
    if not text or not text.strip():
        raise ValueError("文本不能为空")

    table = get_table()
    ds = table.to_lance()

    t0 = time.time()
    chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
    parse_ms = (time.time() - t0) * 1000

    t1 = time.time()
    vectors = embed_batch(chunks)
    embed_ms = (time.time() - t1) * 1000

    chunks_view = [
        {
            "index": i,
            "length": len(c),
            "preview": c[:120] + ("..." if len(c) > 120 else ""),
            "full": c,
        }
        for i, c in enumerate(chunks)
    ]

    vectors_view = [
        {
            "chunk_index": i,
            "dim": len(v),
            "preview_first16": [round(float(x), 4) for x in v[:16]],
            "preview_last8": [round(float(x), 4) for x in v[-8:]],
            "norm": round(float(sum(x * x for x in v) ** 0.5), 4),
            "min": round(float(min(v)), 4),
            "max": round(float(max(v)), 4),
        }
        for i, v in enumerate(vectors)
    ]

    next_fragment_id = max((f.fragment_id for f in ds.get_fragments()), default=-1) + 1

    return {
        "sandbox": True,
        "input": {"text": text, "length": len(text), "chunk_size": chunk_size, "overlap": overlap},
        "steps": [
            {
                "name": "parse_and_chunk",
                "title": "1. 文本分块",
                "duration_ms": round(parse_ms, 2),
                "description": f"按段落切分，超长段落按句号切，目标 chunk_size={chunk_size} 字符，重叠 {overlap} 字符",
                "output": {
                    "chunk_count": len(chunks),
                    "total_chars": sum(len(c) for c in chunks),
                    "avg_chars": int(sum(len(c) for c in chunks) / len(chunks)) if chunks else 0,
                    "chunks": chunks_view,
                },
            },
            {
                "name": "embed_chunks",
                "title": f"2. Embedding（{EMBED_MODEL_NAME} → 384 维）",
                "duration_ms": round(embed_ms, 2),
                "description": "每个 chunk 通过 sentence-transformers 编码成单位向量（norm≈1.0）",
                "output": {
                    "model": EMBED_MODEL_NAME,
                    "vector_dim": len(vectors[0]) if vectors else 0,
                    "vectors": vectors_view,
                },
            },
            {
                "name": "would_insert",
                "title": "3. 写入 LanceDB（仅演示，未真实写入）",
                "duration_ms": 0,
                "description": "若真实写入：每条记录构造 id={filename}_{chunk_index}，追加到下一个 fragment 并产生新 version",
                "output": {
                    "would_create_fragment_id": next_fragment_id,
                    "current_version": ds.version,
                    "version_after_insert": ds.version + 1,
                    "records_preview": [
                        {
                            "id": f"demo_{int(time.time())}_{i}",
                            "filename": f"demo_{int(time.time())}.txt",
                            "chunk_index": i,
                            "content_preview": c[:60] + ("..." if len(c) > 60 else ""),
                            "vector_preview_first8": [round(float(x), 4) for x in v[:8]],
                        }
                        for i, (c, v) in enumerate(zip(chunks, vectors))
                    ],
                },
            },
        ],
    }


def demo_search(query: str, top_k: int = 5, score_threshold: float = 0.3) -> dict:
    """演示搜索流程（真实只读路径，返回每步详细中间数据）"""
    if not query or not query.strip():
        raise ValueError("查询不能为空")

    table = get_table()
    ds = table.to_lance()

    t0 = time.time()
    query_vec = embed_text(query.strip())
    embed_ms = (time.time() - t0) * 1000

    has_index = bool(list(ds.list_indices()))
    fragment_count = sum(1 for _ in ds.get_fragments())
    total_rows = ds.count_rows()

    t1 = time.time()
    raw = table.search(query_vec).metric("cosine").limit(max(top_k * 4, 20)).to_list()
    scan_ms = (time.time() - t1) * 1000

    distance_distribution = []
    for r in raw:
        distance_distribution.append({
            "id": r["id"],
            "filename": r["filename"],
            "distance": round(float(r.get("_distance", 0)), 6),
            "content_preview": r["content"][:60] + ("..." if len(r["content"]) > 60 else ""),
        })

    top_k_rows = distance_distribution[:top_k]

    raw_by_id = {r["id"]: r for r in raw}
    scored = []
    for r in top_k_rows:
        raw_rec = raw_by_id.get(r["id"], {})
        d = r["distance"]
        score = (1.0 - d + 1.0) / 2.0  # 余弦距离 → [0,1] 相似度
        try:
            metadata = json.loads(raw_rec.get("metadata") or "{}")
        except Exception:
            metadata = {}
        explanation = explain_match(query, raw_rec.get("content", ""), score, metadata)
        scored.append({
            **r,
            "similarity_score": round(score, 4),
            "kept": score > score_threshold,
            "match_reasons": explanation["reasons"],
            "hit_keywords": explanation["hit_keywords"],
        })

    kept = [s for s in scored if s["kept"]]
    dropped = [s for s in scored if not s["kept"]]

    return {
        "query": query,
        "steps": [
            {
                "name": "embed_query",
                "title": "1. 查询向量化",
                "duration_ms": round(embed_ms, 2),
                "description": "查询文本经过同款 embedding 模型编码，得到 384 维查询向量",
                "output": {
                    "model": EMBED_MODEL_NAME,
                    "dim": len(query_vec),
                    "preview_first16": [round(float(x), 4) for x in query_vec[:16]],
                    "preview_last8": [round(float(x), 4) for x in query_vec[-8:]],
                    "norm": round(float(sum(x * x for x in query_vec) ** 0.5), 4),
                },
            },
            {
                "name": "scan_strategy",
                "title": "2. 检索策略",
                "duration_ms": 0,
                "description": "无索引 → 全量遍历每个 fragment 中的所有行，逐行计算余弦距离",
                "output": {
                    "has_index": has_index,
                    "strategy": "full_scan" if not has_index else "indexed_search",
                    "fragments_to_scan": fragment_count,
                    "total_rows_to_scan": total_rows,
                    "expected_distance_computations": total_rows,
                    "vector_dim": len(query_vec),
                    "flops_estimate": total_rows * len(query_vec) * 2,
                },
            },
            {
                "name": "compute_distances",
                "title": "3. 计算余弦距离 + 排序",
                "duration_ms": round(scan_ms, 2),
                "description": "余弦距离 = 1 - cosine_similarity，取距离最小的若干条",
                "output": {
                    "candidates_returned": len(distance_distribution),
                    "distance_min": distance_distribution[0]["distance"] if distance_distribution else None,
                    "distance_max": distance_distribution[-1]["distance"] if distance_distribution else None,
                    "candidates": distance_distribution,
                },
            },
            {
                "name": "top_k_selection",
                "title": f"4. 取 Top-{top_k}",
                "duration_ms": 0,
                "description": f"从候选中按距离升序取前 {top_k} 条",
                "output": {
                    "k": top_k,
                    "selected": top_k_rows,
                },
            },
            {
                "name": "score_conversion",
                "title": "5. 距离 → 相似度分数",
                "duration_ms": 0,
                "description": "公式：similarity = (1 - cosine_distance + 1) / 2，把余弦距离映射到 [0, 1] 相似度",
                "output": {
                    "formula": "similarity = (2 - distance) / 2",
                    "examples": scored,
                },
            },
            {
                "name": "filter",
                "title": "6. 阈值过滤",
                "duration_ms": 0,
                "description": f"丢弃 similarity ≤ {score_threshold} 的低分结果",
                "output": {
                    "threshold": score_threshold,
                    "kept": len(kept),
                    "dropped": len(dropped),
                    "kept_results": kept,
                    "dropped_results": dropped,
                },
            },
        ],
    }

