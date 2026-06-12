#!/usr/bin/env python3
"""kb_rest.py — email-wiki-demo 代码知识库 REST API 客户端

零依赖（仅标准库 urllib），直连后端 REST API，不走 MCP 协议。
适用场景：AI Agent 想用 Bash 调用后端搜索/问答/调用链能力。

环境变量：
  CODE_KB_URL — 后端服务地址（默认 http://localhost:8000）

用法：
  python3 kb_rest.py repos
  python3 kb_rest.py search --query "邮件发送" --top_k 5
  python3 kb_rest.py search --query "sendMail" --repo ghmail
  python3 kb_rest.py trace --symbol sendMail --direction both --depth 2
  python3 kb_rest.py chat --question "sendMail 如何工作"
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

# 默认服务地址（可用环境变量覆盖）
DEFAULT_URL = "http://localhost:8000"
TIMEOUT_SEC = 30          # search/trace/repos 默认超时
CHAT_TIMEOUT_SEC = 120    # chat 涉及 LLM 推理，给宽点

ENV_KEY = "CODE_KB_URL"


def _base_url() -> str:
    """从环境变量读取服务地址，去掉尾部 /"""
    return os.environ.get(ENV_KEY, DEFAULT_URL).rstrip("/")


def _request(method: str, path: str, payload: dict | None = None, timeout: int = TIMEOUT_SEC) -> dict:
    """发送 HTTP 请求到后端，返回 JSON 响应"""
    url = f"{_base_url()}{path}"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    else:
        data = None

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        # 后端返回的 JSON 错误体（FastAPI HTTPException）
        try:
            err_body = json.loads(e.read().decode("utf-8"))
            return {"error": err_body.get("detail", str(e)), "status": e.code}
        except Exception:
            return {"error": str(e), "status": e.code}
    except urllib.error.URLError as e:
        return {"error": f"无法连接 {url}: {e.reason}"}
    except json.JSONDecodeError as e:
        return {"error": f"响应不是合法 JSON: {e}"}
    except TimeoutError:
        return {"error": f"请求超时（{timeout}s）: {url}"}


def cmd_repos(args) -> int:
    """列出已索引的代码仓库"""
    result = _request("GET", "/api/code/repos")
    if "error" in result and "repos" not in result:
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    repos = result.get("repos", [])
    if not repos:
        print("（暂无已索引仓库）")
        return 0

    print(f"已索引仓库（共 {len(repos)} 个）：")
    for r in repos:
        name = r.get("name", "?")
        chunks = r.get("total_chunks", r.get("chunk_count", "?"))
        path = r.get("path", "")
        print(f"  • {name}  ({chunks} chunks)  {path}")
    return 0


def cmd_search(args) -> int:
    """混合搜索代码"""
    filters = {}
    if args.repo:
        filters["repo_name"] = args.repo
    if args.language:
        filters["language"] = args.language
    if args.symbol:
        filters["symbol_name"] = args.symbol

    payload = {
        "query": args.query,
        "mode": args.mode,
        "top_k": args.top_k,
        "filters": filters,
    }
    result = _request("POST", "/api/code/search", payload)
    return _print_results(result, top_k=args.top_k)


def cmd_chat(args) -> int:
    """RAG 代码问答"""
    filters = {}
    if args.repo:
        filters["repo_name"] = args.repo
    if args.language:
        filters["language"] = args.language

    payload = {
        "question": args.question,
        "top_k": args.top_k,
        "filters": filters,
        "stream": False,
    }
    result = _request("POST", "/api/code/chat", payload, timeout=CHAT_TIMEOUT_SEC)

    if "error" in result and "answer" not in result:
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    print("=" * 60)
    print(f"Q: {result.get('question', args.question)}")
    print("=" * 60)
    print(result.get("answer", "（无回答）"))
    print()
    sources = result.get("sources", [])
    if sources:
        print(f"参考来源（共 {len(sources)} 条）：")
        for i, s in enumerate(sources, 1):
            file_path = s.get("file_path", "?")
            symbol = s.get("symbol_name", "?")
            line_start = s.get("line_start", "?")
            line_end = s.get("line_end", "?")
            print(f"  [{i}] {file_path}:{line_start}-{line_end}  ({symbol})")
    return 0


def cmd_trace(args) -> int:
    """调用链追踪"""
    payload = {
        "symbol": args.symbol,
        "repo_name": args.repo or "",
        "direction": args.direction,
        "depth": args.depth,
    }
    result = _request("POST", "/api/code/trace", payload)
    return _print_results(result, top_k=None)


def _print_results(result: dict, top_k: int | None) -> int:
    """通用结果打印：search/trace 共用"""
    if "error" in result and "results" not in result and "traces" not in result:
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    # search 的结果
    if "results" in result:
        results = result.get("results", [])
        print(f"查询: {result.get('query', '')}")
        print(f"模式: {result.get('mode', '')}  命中: {len(results)}")
        print()
        if not results:
            print("（无结果）")
            return 0
        for i, r in enumerate(results, 1):
            file_path = r.get("file_path", "?")
            symbol = r.get("symbol_name", "?")
            line_start = r.get("line_start", "?")
            line_end = r.get("line_end", "?")
            score = r.get("score", 0)
            reason = r.get("match_reason", "")
            content = r.get("content", "")
            print(f"[{i}] {file_path}:{line_start}-{line_end}  ({symbol})  score={score:.4f}")
            if reason:
                print(f"    匹配原因: {reason}")
            # 截断预览
            preview = content[:200].replace("\n", "\n    ")
            print(f"    {preview}{'...' if len(content) > 200 else ''}")
            print()
        return 0

    # trace 的结果
    if "traces" in result:
        traces = result.get("traces", [])
        matched = result.get("matched_symbols", [])
        print(f"符号: {result.get('query', '')}")
        print(f"方向: {result.get('direction', '')}  深度: {result.get('depth', '')}")
        print(f"匹配符号: {len(matched)}  追踪链: {len(traces)}")
        print()
        if not traces:
            print("（无调用链数据）")
            return 0
        for t in traces:
            entry = t.get("entry_symbol", "?")
            entry_file = t.get("entry_file", "?")
            print(f"━━ {entry} ({entry_file}) ━━")
            chain = t.get("chain", {})
            nodes = chain.get("nodes", [])
            edges = chain.get("edges", [])
            if nodes:
                print(f"  节点 ({len(nodes)}):")
                for n in nodes[:20]:  # 最多展示 20 个
                    symbol = n.get('symbol', '?')
                    # trace 返回的 node 字段是 'file'，matched_symbols 是 'file_path'
                    file_path = n.get('file', n.get('file_path', '?'))
                    line_start = n.get('line_start', '')
                    suffix = f":{line_start}" if line_start else ""
                    print(f"    • {symbol}  @ {file_path}{suffix}")
                if len(nodes) > 20:
                    print(f"    ... 还有 {len(nodes) - 20} 个")
            if edges:
                print(f"  边 ({len(edges)}):")
                for e in edges[:20]:
                    print(f"    {e.get('from', '?')} → {e.get('to', '?')}")
                if len(edges) > 20:
                    print(f"    ... 还有 {len(edges) - 20} 条")
            print()
        return 0

    # 兜底：原样输出
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="email-wiki-demo 代码知识库 REST 客户端（零依赖）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
环境变量:
  {ENV_KEY}    后端服务地址，默认 {DEFAULT_URL}
               示例: export {ENV_KEY}=http://192.168.1.100:8000
""",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # repos
    p_repos = sub.add_parser("repos", help="列出已索引的代码仓库")
    p_repos.set_defaults(func=cmd_repos)

    # search
    p_search = sub.add_parser("search", help="混合搜索代码（向量+关键词+符号）")
    p_search.add_argument("--query", "-q", required=True, help="搜索关键词")
    p_search.add_argument("--top_k", "-k", type=int, default=10, help="返回数量（默认 10）")
    p_search.add_argument("--mode", default="hybrid", choices=["hybrid", "vector", "keyword"], help="搜索模式")
    p_search.add_argument("--repo", help="限定仓库名")
    p_search.add_argument("--language", help="限定语言（objc/swift/java/kotlin/dart/...）")
    p_search.add_argument("--symbol", help="限定符号名（精确匹配）")
    p_search.set_defaults(func=cmd_search)

    # chat
    p_chat = sub.add_parser("chat", help="RAG 代码问答（基于 LLM）")
    p_chat.add_argument("--question", required=True, help="问题")
    p_chat.add_argument("--top_k", type=int, default=5, help="检索条数（默认 5）")
    p_chat.add_argument("--repo", help="限定仓库名")
    p_chat.add_argument("--language", help="限定语言")
    p_chat.set_defaults(func=cmd_chat)

    # trace
    p_trace = sub.add_parser("trace", help="调用链追踪（谁调用了它 / 它调用了谁）")
    p_trace.add_argument("--symbol", required=True, help="符号名")
    p_trace.add_argument("--repo", help="限定仓库名")
    p_trace.add_argument("--direction", default="both", choices=["callers", "callees", "both", "hierarchy"], help="追踪方向")
    p_trace.add_argument("--depth", type=int, default=2, help="追踪深度（1-3）")
    p_trace.set_defaults(func=cmd_trace)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
