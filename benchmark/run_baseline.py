"""一键基线 - 跑完整压测套件 → 聚合 summary → 入库 baselines + 落盘 results/"""

import os
import sys
import json
import argparse
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import metrics_db
from config import DEFAULT_CONFIG, SEARCH_BENCHMARK, INSERT_BENCHMARK, RESULTS_DIR
from benchmark_search import benchmark_search
from benchmark_insert import benchmark_insert, cleanup as cleanup_insert


def run_full_baseline(
    label: str,
    notes: str = "",
    search_runs: int = None,
    insert_doc_sizes: list = None,
    cleanup: bool = True,
) -> dict:
    """跑完整基线：search + insert，聚合产出 summary"""
    started_at = datetime.now().isoformat()
    print(f"🚀 基线压测开始 label={label} at {started_at}")

    print("\n--- 1/2 搜索压测 ---")
    search_result = benchmark_search(
        runs=search_runs or SEARCH_BENCHMARK["measure_runs"],
        top_k=DEFAULT_CONFIG["top_k"],
        warmup=SEARCH_BENCHMARK["warmup_runs"],
    )

    print("\n--- 2/2 插入压测 ---")
    insert_result = benchmark_insert(
        doc_sizes=insert_doc_sizes or INSERT_BENCHMARK["doc_sizes"],
        runs=INSERT_BENCHMARK["measure_runs"],
        warmup=INSERT_BENCHMARK["warmup_runs"],
    )

    if cleanup:
        cleanup_insert(insert_result["inserted_files"])

    lancedb_path = os.path.join(os.path.dirname(__file__), "..", "data", "lancedb")
    disk_bytes = metrics_db.get_disk_usage(lancedb_path)

    summary = {
        "search": search_result["summary"],
        "search_breakdown": search_result["breakdown"],
        "insert": insert_result["summary"],
        "insert_per_size": insert_result["per_size"],
        "lancedb_disk_bytes": disk_bytes,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(),
    }

    config_snapshot = {
        **DEFAULT_CONFIG,
        "search_runs": search_runs or SEARCH_BENCHMARK["measure_runs"],
        "search_queries": search_result["queries_count"],
        "insert_doc_sizes": insert_doc_sizes or INSERT_BENCHMARK["doc_sizes"],
        "insert_runs": INSERT_BENCHMARK["measure_runs"],
    }

    baseline_id = metrics_db.save_baseline(
        label=label,
        config=config_snapshot,
        summary=summary,
        notes=notes,
    )

    os.makedirs(RESULTS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(RESULTS_DIR, f"{timestamp}_{label}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "baseline_id": baseline_id,
            "label": label,
            "notes": notes,
            "config": config_snapshot,
            "summary": summary,
        }, f, indent=2, ensure_ascii=False)

    print(f"\n🎯 基线已入库: id={baseline_id}, label={label}")
    print(f"📁 结果落盘: {out_path}")
    print("\n=== 摘要 ===")
    print(f"  搜索: avg={summary['search'].get('avg_ms', 0)}ms p95={summary['search'].get('p95_ms', 0)}ms n={summary['search'].get('count', 0)}")
    print(f"  插入(file): avg={summary['insert'].get('avg_per_file_ms', 0)}ms n={summary['insert'].get('file_count', 0)}")
    print(f"  插入(chunk): avg={summary['insert'].get('avg_per_chunk_ms', 0)}ms (平摊)")
    print(f"  LanceDB 磁盘: {disk_bytes / 1024:.1f} KB")

    return {
        "baseline_id": baseline_id,
        "config": config_snapshot,
        "summary": summary,
        "result_path": out_path,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True, help="基线标签，如 v1_minilm_chunk500_top5")
    parser.add_argument("--notes", default="", help="备注")
    parser.add_argument("--search-runs", type=int, help="覆盖默认搜索轮数")
    parser.add_argument("--insert-doc-sizes", nargs="+", type=int, help="覆盖默认插入规模")
    parser.add_argument("--no-cleanup", action="store_true", help="跑完不清理合成数据（用于查看效果）")
    args = parser.parse_args()

    run_full_baseline(
        label=args.label,
        notes=args.notes,
        search_runs=args.search_runs,
        insert_doc_sizes=args.insert_doc_sizes,
        cleanup=not args.no_cleanup,
    )


if __name__ == "__main__":
    main()
