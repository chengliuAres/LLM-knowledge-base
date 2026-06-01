"""插入压测 - 不同规模的合成文档批量灌入，测平均耗时"""

import os
import sys
import json
import argparse
import time
import uuid
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from embedder import embed_batch
from db import insert_documents, delete_document
from step_tracker import StepTracker
import metrics_db
from config import INSERT_BENCHMARK, DEFAULT_CONFIG
from generate_data import generate_chunks


def run_insert_once(chunks: list, label: str = "benchmark") -> dict:
    """模拟一次完整插入路径，复用 main.py 同款埋点结构"""
    tracker = StepTracker(operation_type="insert_file")
    tracker.set_extra(
        filename=chunks[0]["filename"],
        chunk_count=len(chunks),
        file_size_bytes=sum(len(c["content"]) for c in chunks),
        source=label,
    )

    s_emb = tracker.add_step("generate_embeddings", "生成 Embedding")
    s_emb.start()
    contents = [c["content"] for c in chunks]
    vectors = embed_batch(contents)
    s_emb.complete({"vector_count": len(vectors), "dim": len(vectors[0]) if vectors else 0})

    s_store = tracker.add_step("store_vectors", "存入 LanceDB")
    s_store.start()
    for c, v in zip(chunks, vectors):
        c["vector"] = v
    insert_documents(chunks)
    s_store.complete({"stored": len(chunks)})

    tracker.flush()
    return {"request_id": tracker.request_id, "duration_ms": tracker.get_total_duration()}


def benchmark_insert(doc_sizes: list = None, warmup: int = 1, runs: int = 3, prefix_base: str = "bench") -> dict:
    """跑插入压测：每个 doc_size 跑 runs 次（先 warmup），收集平均/P95"""
    sizes = doc_sizes or INSERT_BENCHMARK["doc_sizes"]
    print(f"📋 插入压测 doc_sizes={sizes} runs={runs} warmup={warmup}")

    bench_start = datetime.now().isoformat()
    label = f"insert_bench_{uuid.uuid4().hex[:8]}"
    inserted_filenames: list = []

    print(f"🔥 预热（{warmup} 次小规模插入）...")
    for i in range(warmup):
        prefix = f"{prefix_base}_warmup_{i}"
        chunks = generate_chunks(10, prefix=prefix)
        run_insert_once(chunks, label="warmup")
        inserted_filenames.extend({c["filename"] for c in chunks})

    print(f"⏱️  正式压测...")
    per_size_results = {}
    for size in sizes:
        size_results = []
        for run_idx in range(runs):
            prefix = f"{prefix_base}_{label}_size{size}_run{run_idx}"
            chunks = generate_chunks(size, prefix=prefix)
            result = run_insert_once(chunks, label=label)
            size_results.append(result["duration_ms"])
            inserted_filenames.extend({c["filename"] for c in chunks})
            print(f"  size={size} run={run_idx + 1}/{runs} duration={result['duration_ms']:.0f}ms")
        per_size_results[size] = {
            "runs": runs,
            "avg_ms": round(sum(size_results) / len(size_results), 2),
            "min_ms": round(min(size_results), 2),
            "max_ms": round(max(size_results), 2),
            "avg_per_chunk_ms": round(sum(size_results) / len(size_results) / size, 2),
        }

    summary = _summarize_since(bench_start)

    print(f"\n✅ 插入压测完成")
    print(f"   per_size: {per_size_results}")
    print(f"   summary: {summary}")

    return {
        "label": label,
        "per_size": per_size_results,
        "summary": summary,
        "inserted_files": list(set(inserted_filenames)),
    }


def _summarize_since(since_iso: str) -> dict:
    """聚合本次压测段的插入统计（按 file 粒度 + 按 chunk 粒度平摊）"""
    import sqlite3
    conn = sqlite3.connect(metrics_db.DB_PATH)
    cur = conn.execute('''
        SELECT duration_ms, extra FROM operations
        WHERE operation_type IN ('insert_file', 'email_import')
          AND status = 'completed' AND step_name IS NULL
          AND created_at >= ?
    ''', (since_iso,))
    rows = cur.fetchall()
    conn.close()

    total_dur = 0.0
    total_chunks = 0
    durations = []
    for dur, extra_json in rows:
        extra = json.loads(extra_json) if extra_json else {}
        chunk_count = extra.get("chunk_count", 0)
        if chunk_count > 0:
            durations.append(dur)
            total_dur += dur
            total_chunks += chunk_count

    n = len(durations)
    if n == 0:
        return {"file_count": 0, "chunk_count": 0}
    return {
        "file_count": n,
        "chunk_count": total_chunks,
        "avg_per_file_ms": round(total_dur / n, 2),
        "avg_per_chunk_ms": round(total_dur / total_chunks, 2),
    }


def cleanup(filenames: list):
    """删除压测产生的合成数据，避免污染主表"""
    print(f"🧹 清理 {len(filenames)} 个合成文件...")
    for fn in filenames:
        try:
            delete_document(fn)
        except Exception as e:
            print(f"  warn: 删除 {fn} 失败: {e}")
    print("   清理完成")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc-sizes", nargs="+", type=int, default=INSERT_BENCHMARK["doc_sizes"],
                        help="不同规模的文档（chunk 数），如 --doc-sizes 10 100 1000")
    parser.add_argument("--runs", type=int, default=INSERT_BENCHMARK["measure_runs"])
    parser.add_argument("--warmup", type=int, default=INSERT_BENCHMARK["warmup_runs"])
    parser.add_argument("--cleanup", action="store_true", help="跑完后清理合成数据")
    args = parser.parse_args()

    result = benchmark_insert(doc_sizes=args.doc_sizes, runs=args.runs, warmup=args.warmup)
    if args.cleanup:
        cleanup(result["inserted_files"])
    print("\n=== 最终结果 ===")
    print(json.dumps({k: v for k, v in result.items() if k != "inserted_files"}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
