"""代码搜索质量测试

验证中文查询能否高分命中预期代码符号。
测试用例基于 ghmail 项目（邮箱大师 iOS 客户端）的实际代码索引。

用法:
    cd backend
    source venv/bin/activate
    python3 test_code_search_quality.py          # 全部测试
    python3 test_code_search_quality.py 读信      # 单个测试
    python3 test_code_search_quality.py --baseline  # 记录基线（改代码前跑一次）
"""

import sys
import json
import os
from datetime import datetime

# ── 测试用例定义 ──────────────────────────────────────────────────

TEST_CASES = [
    {
        "query": "读信",
        "expected_symbols": ["GHRead", "RCRead"],
        "description": "读信模块 — 邮箱核心功能之一，包含 GHReadViewController/RCReadVC 等",
    },
    {
        "query": "邮件列表",
        "expected_symbols": ["GHList", "GHMailListCell"],
        "description": "邮件列表模块 — 列表展示、cell 渲染等",
    },
    {
        "query": "我的页面",
        "expected_symbols": ["GHMineViewController", "GHMineViewModel"],
        "description": "我的页面 — 个人中心/设置页",
    },
    {
        "query": "大师号",
        "expected_symbols": ["GHMasterLoginVC", "GHMaster"],
        "description": "大师号 — 大师号登录/管理相关",
    },
]


def run_search(query: str, mode: str = "hybrid", top_k: int = 20) -> dict:
    """调用 search_code 执行搜索"""
    from code_search import search_code
    return search_code(query=query, mode=mode, top_k=top_k)


def evaluate_result(result: dict, expected_symbols: list[str], top_k: int = 10) -> dict:
    """评估搜索结果质量

    指标:
    - hit_count: top_k 中命中预期符号前缀的数量
    - hit_details: 命中的具体符号名和排名
    - miss_details: 未命中的预期符号
    - best_rank: 最早命中预期符号的排名（越小越好）
    - top1_symbol: 排名第1的符号名
    """
    results = result.get("results", [])[:top_k]
    hit_details = []
    miss_details = []

    for expected in expected_symbols:
        found = False
        for rank, r in enumerate(results, start=1):
            symbol = r.get("symbol_name", "")
            if expected in symbol:
                hit_details.append({
                    "expected": expected,
                    "matched_symbol": symbol,
                    "rank": rank,
                    "score": r.get("score", 0),
                    "rrf_score": r.get("rrf_score", 0),
                    "file_path": r.get("file_path", ""),
                    "match_reason": r.get("match_reason", ""),
                })
                found = True
                break
        if not found:
            miss_details.append(expected)

    best_rank = min((h["rank"] for h in hit_details), default=0)
    top1_symbol = results[0].get("symbol_name", "") if results else ""

    return {
        "hit_count": len(hit_details),
        "expected_count": len(expected_symbols),
        "best_rank": best_rank,
        "top1_symbol": top1_symbol,
        "hit_details": hit_details,
        "miss_details": miss_details,
    }


def print_report(query: str, evaluation: dict, result: dict, verbose: bool = False):
    """打印测试报告"""
    hit = evaluation["hit_count"]
    total = evaluation["expected_count"]
    best = evaluation["best_rank"]
    top1 = evaluation["top1_symbol"]
    translation = result.get("translation", {})
    translated_kw = translation.get("translated", [])

    # 通过/失败判定：至少命中一半预期符号，且最佳排名 <= 10
    passed = hit >= max(1, total // 2) and best <= 10
    status = "✅ PASS" if passed else "❌ FAIL"

    print(f"\n{'='*60}")
    print(f"查询: \"{query}\" → 翻译: {translated_kw}")
    print(f"状态: {status}  命中: {hit}/{total}  最佳排名: #{best if best else '未命中'}")
    print(f"Top1: {top1}")
    print(f"{'─'*60}")

    for h in evaluation["hit_details"]:
        print(f"  ✅ #{h['rank']} {h['matched_symbol']} (score={h['score']:.4f}, rrf={h['rrf_score']:.4f}) → {h['file_path'][:60]}")
        if verbose:
            print(f"     match_reason: {h['match_reason']}")

    for m in evaluation["miss_details"]:
        print(f"  ❌ 未命中: {m}")

    if verbose:
        print(f"\n  Top 10 结果:")
        for i, r in enumerate(result.get("results", [])[:10], start=1):
            symbol = r.get("symbol_name", "")
            score = r.get("score", 0)
            rrf = r.get("rrf_score", 0)
            source = r.get("source", "")
            reason = r.get("match_reason", "")
            boost = r.get("match_boost", 1.0)
            boost_str = f" 🔥{boost}x" if boost > 1.0 else ""
            print(f"    #{i} {symbol[:35]:35s} score={score:.4f} rrf={rrf:.4f} [{source}]{boost_str} {reason}")


def save_baseline(results: list[dict], filepath: str = "data/search_quality_baseline.json"):
    """保存基线结果"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    baseline = {
        "timestamp": datetime.now().isoformat(),
        "results": results,
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(baseline, f, ensure_ascii=False, indent=2)
    print(f"\n基线已保存到 {filepath}")


def load_baseline(filepath: str = "data/search_quality_baseline.json") -> dict:
    """加载基线结果"""
    if not os.path.exists(filepath):
        return {}
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)


def compare_with_baseline(current: list[dict], baseline: dict):
    """与基线对比"""
    if not baseline:
        print("\n⚠️ 无基线数据，跳过对比")
        return

    baseline_results = {r["query"]: r for r in baseline.get("results", [])}
    print(f"\n{'='*60}")
    print(f"📊 与基线对比 (基线时间: {baseline.get('timestamp', 'unknown')})")
    print(f"{'='*60}")

    for cur in current:
        query = cur["query"]
        base = baseline_results.get(query)
        if not base:
            print(f"  {query}: 无基线数据")
            continue

        cur_hit = cur["hit_count"]
        base_hit = base["hit_count"]
        cur_rank = cur["best_rank"]
        base_rank = base["best_rank"]

        hit_diff = cur_hit - base_hit
        rank_diff = (base_rank or 999) - (cur_rank or 999)  # 正数=改善

        hit_icon = "📈" if hit_diff > 0 else ("📉" if hit_diff < 0 else "➡️")
        rank_icon = "📈" if rank_diff > 0 else ("📉" if rank_diff < 0 else "➡️")

        print(f"  {query}: 命中 {base_hit}→{cur_hit} {hit_icon}  排名 #{base_rank or '未命中'}→#{cur_rank or '未命中'} {rank_icon}")


def main():
    # 解析参数
    args = sys.argv[1:]
    is_baseline = "--baseline" in args
    is_verbose = "--verbose" in args or "-v" in args
    filter_query = None
    for arg in args:
        if not arg.startswith("-") and arg not in ("baseline", "verbose"):
            filter_query = arg

    # 选择测试用例
    cases = TEST_CASES
    if filter_query:
        cases = [c for c in cases if filter_query in c["query"]]
        if not cases:
            print(f"未找到包含 \"{filter_query}\" 的测试用例")
            print(f"可用: {', '.join(c['query'] for c in TEST_CASES)}")
            sys.exit(1)

    print(f"🧪 代码搜索质量测试")
    print(f"测试用例: {len(cases)} 个")
    if filter_query:
        print(f"过滤: \"{filter_query}\"")
    print()

    # 执行测试
    all_results = []
    pass_count = 0

    for case in cases:
        result = run_search(case["query"], mode="hybrid", top_k=20)
        evaluation = evaluate_result(result, case["expected_symbols"], top_k=10)

        # 判定
        hit = evaluation["hit_count"]
        total = evaluation["expected_count"]
        best = evaluation["best_rank"]
        passed = hit >= max(1, total // 2) and best <= 10
        if passed:
            pass_count += 1

        print_report(case["query"], evaluation, result, verbose=is_verbose)

        all_results.append({
            "query": case["query"],
            "expected_symbols": case["expected_symbols"],
            "hit_count": hit,
            "expected_count": total,
            "best_rank": best,
            "top1_symbol": evaluation["top1_symbol"],
            "hit_details": evaluation["hit_details"],
            "miss_details": evaluation["miss_details"],
        })

    # 汇总
    print(f"\n{'='*60}")
    print(f"📊 汇总: {pass_count}/{len(cases)} 通过")
    for r in all_results:
        status = "✅" if r["hit_count"] >= max(1, r["expected_count"] // 2) and r["best_rank"] <= 10 else "❌"
        print(f"  {status} \"{r['query']}\": 命中 {r['hit_count']}/{r['expected_count']}, 最佳排名 #{r['best_rank'] or '未命中'}")

    # 基线对比
    if is_baseline:
        save_baseline(all_results)
    else:
        baseline = load_baseline()
        if baseline:
            compare_with_baseline(all_results, baseline)

    # 返回码
    sys.exit(0 if pass_count == len(cases) else 1)


if __name__ == "__main__":
    main()
