"""搜索压测 - 用固定查询集 × N 次跑搜索路径，落库后查 P50/P95/avg"""

import os
import sys
import json
import argparse
import time
import uuid
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from embedder import embed_text
from db import search_similar
from step_tracker import StepTracker
import metrics_db
from config import SEARCH_BENCHMARK, DEFAULT_CONFIG


def load_queries(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["queries"]


def run_search_once(query: str, top_k: int, label: str = "benchmark") -> dict:
    """模拟一次完整搜索请求，复用 main.py 同款埋点"""
    tracker = StepTracker(operation_type="search")
    tracker.set_extra(query=query, top_k=top_k, source=label)

    s_pre = tracker.add_step("preprocess", "预处理查询")
    s_pre.start()
    q = query.strip()
    s_pre.complete({"length": len(q)})

    s_emb = tracker.add_step("embed_query", "生成查询向量")
    s_emb.start()
    vector = embed_text(q)
    s_emb.complete({"dim": len(vector)})

    s_search = tracker.add_step("lanceDB_search", "向量检索")
    s_search.start()
    results = search_similar(vector, top_k=top_k)
    s_search.complete({"returned": len(results)})

    s_filter = tracker.add_step("filter_results", "结果过滤")
    s_filter.start()
    filtered = [r for r in results if r["score"] > DEFAULT_CONFIG["score_threshold"]]
    s_filter.complete({"filtered": len(filtered)})

    tracker.set_extra(returned_count=len(filtered))
    tracker.flush()
    return {"request_id": tracker.request_id, "duration_ms": tracker.get_total_duration(), "results": len(filtered)}


def benchmark_search(runs: int = 30, top_k: int = 5, warmup: int = 3, queries_file: str = None) -> dict:
    """跑 runs 轮搜索（每轮遍历所有查询），返回仅本次压测的聚合统计"""
    queries_path = queries_file or SEARCH_BENCHMARK["queries_file"]
    queries = load_queries(queries_path)
    print(f"📋 加载 {len(queries)} 条查询")

    print(f"🔥 预热 {warmup} 轮（不计入统计）...")
    for _ in range(warmup):
        for q in queries[:5]:
            run_search_once(q["text"], top_k, label="warmup")

    print(f"⏱️  正式压测 {runs} 轮 × {len(queries)} 查询 = {runs * len(queries)} 次搜索")
    label = f"bench_{uuid.uuid4().hex[:8]}"
    t0 = time.time()
    bench_start_iso = datetime.now().isoformat()
    for run_idx in range(runs):
        for q in queries:
            run_search_once(q["text"], top_k, label=label)
        if (run_idx + 1) % 5 == 0:
            print(f"  完成 {run_idx + 1}/{runs} 轮")
    elapsed = time.time() - t0

    summary = _summarize_since("search", bench_start_iso)
    breakdown = _breakdown_since("search", bench_start_iso)

    print(f"\n✅ 完成，总耗时 {elapsed:.2f}s")
    print(f"   summary: {summary}")
    return {
        "wall_time_seconds": round(elapsed, 2),
        "label": label,
        "queries_count": len(queries),
        "runs": runs,
        "top_k": top_k,
        "summary": summary,
        "breakdown": breakdown,
    }


def _summarize_since(op_type: str, since_iso: str) -> dict:
    """按 created_at >= since_iso 过滤的聚合（仅当前压测段）"""
    import sqlite3
    conn = sqlite3.connect(metrics_db.DB_PATH)
    cur = conn.execute('''
        SELECT duration_ms FROM operations
        WHERE operation_type = ? AND status = 'completed' AND step_name IS NULL
          AND created_at >= ?
        ORDER BY duration_ms
    ''', (op_type, since_iso))
    durations = [r[0] for r in cur.fetchall()]
    conn.close()
    n = len(durations)
    if n == 0:
        return {"count": 0}
    return {
        "count": n,
        "avg_ms": round(sum(durations) / n, 2),
        "p50_ms": round(durations[int(n * 0.50)], 2),
        "p95_ms": round(durations[min(int(n * 0.95), n - 1)], 2),
        "max_ms": round(durations[-1], 2),
        "min_ms": round(durations[0], 2),
    }


def _breakdown_since(op_type: str, since_iso: str) -> list:
    """按 created_at >= since_iso 过滤的 step 拆解"""
    import sqlite3
    conn = sqlite3.connect(metrics_db.DB_PATH)
    cur = conn.execute('''
        SELECT step_name, COUNT(*), AVG(duration_ms), MAX(duration_ms)
        FROM operations
        WHERE operation_type = ? AND status = 'completed' AND step_name IS NOT NULL
          AND created_at >= ?
        GROUP BY step_name ORDER BY AVG(duration_ms) DESC
    ''', (op_type, since_iso))
    rows = [{"step_name": r[0], "count": r[1], "avg_ms": round(r[2], 2), "max_ms": round(r[3], 2)} for r in cur.fetchall()]
    conn.close()
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=SEARCH_BENCHMARK["measure_runs"])
    parser.add_argument("--top-k", type=int, default=DEFAULT_CONFIG["top_k"])
    parser.add_argument("--warmup", type=int, default=SEARCH_BENCHMARK["warmup_runs"])
    parser.add_argument("--queries", default=SEARCH_BENCHMARK["queries_file"])
    args = parser.parse_args()

    result = benchmark_search(runs=args.runs, top_k=args.top_k, warmup=args.warmup, queries_file=args.queries)
    print("\n=== 最终结果 ===")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
