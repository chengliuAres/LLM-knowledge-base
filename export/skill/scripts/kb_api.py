#!/usr/bin/env python3
"""kb_api.py — email-wiki-demo 代码知识库 Python 兜底 CLI

零依赖 Streamable HTTP 客户端，Python 3.9+ 即可运行。
适用场景：MCP 工具不可用时，AI Agent 用 CLI 兜底继续工作。

MCP 协议要点（实测得到）：
- 后端是 stateless_http=True + json_response=True 的 FastMCP
- 不需要持久化 Mcp-Session-Id（stateless 不校验）
- 响应是 application/json（不是 SSE stream）
- tool 返回值是嵌套 JSON 字符串（content[0].text / structuredContent.result）

5 个子命令对应 5 个 tool:
  search  → code_search
  chat    → code_chat
  trace   → code_trace
  file    → code_file_context
  repos   → code_list_repos

用法：
  python3 kb_api.py search --query "邮件发送" --top_k 5
  python3 kb_api.py chat --question "sendMail 如何工作"
  python3 kb_api.py trace --symbol sendMail --direction both --depth 2
  python3 kb_api.py file --repo ghmail --name "login_page.dart"
  python3 kb_api.py repos

环境变量：
  KB_MCP_URL — MCP 端点 URL，默认 http://localhost:8000/mcp/
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.error
import urllib.request
import socket

DEFAULT_URL = "http://localhost:8000/mcp/"
# 默认 30s（search/trace/file/repos 等快操作）
TIMEOUT_SEC = 30
# chat 单独 120s（LLM 推理常 30-60s）
CHAT_TIMEOUT_SEC = 120
CLIENT_NAME = "kb_api_cli"
CLIENT_VERSION = "1.0.0"
PROTOCOL_VERSION = "2024-11-05"


def _mcp_call(url: str, method: str, params: dict, _id: int, timeout: int = TIMEOUT_SEC) -> dict:
    """发送 JSON-RPC 2.0 请求到 MCP server."""
    payload = {
        "jsonrpc": "2.0",
        "id": _id,
        "method": method,
        "params": params,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason}", "body": e.read().decode("utf-8", errors="replace")}
    except socket.timeout:
        return {"error": f"连接超时（>{timeout}s）— chat 推理慢可设置 KB_CHAT_TIMEOUT 环境变量或用 MCP 模式"}
    except urllib.error.URLError as e:
        if isinstance(e.reason, socket.timeout):
            return {"error": f"连接超时（>{timeout}s）— chat 推理慢可设置 KB_CHAT_TIMEOUT 环境变量或用 MCP 模式"}
        return {"error": f"连接失败: {e.reason}"}
    except json.JSONDecodeError as e:
        return {"error": f"响应非 JSON: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"未知错误: {type(e).__name__}: {e}"}


def _ensure_init(url: str) -> bool:
    """握手 initialize。stateless_http 模式下不强制要求，但发一次保证协议对齐。"""
    resp = _mcp_call(
        url,
        "initialize",
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
        },
        _id=0,
    )
    return "result" in resp


def _call_tool(url: str, tool_name: str, arguments: dict, timeout: int = TIMEOUT_SEC) -> dict:
    """调用 MCP tool，提取嵌套的 result JSON 字符串。"""
    resp = _mcp_call(
        url,
        "tools/call",
        {"name": tool_name, "arguments": arguments},
        _id=1,
        timeout=timeout,
    )
    if "error" in resp:
        return resp
    if "error" in resp.get("result", {}):
        return resp["result"]
    # result.content[0].text 是嵌套 JSON 字符串
    content = resp.get("result", {}).get("content", [])
    if content and isinstance(content, list) and "text" in content[0]:
        try:
            return {"result": json.loads(content[0]["text"])}
        except json.JSONDecodeError:
            return {"raw_text": content[0]["text"]}
    return resp.get("result", resp)


def _print_json(data: dict, pretty: bool = True) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2 if pretty else None))


# === 子命令实现 ===

def cmd_search(args, url):
    """code_search: query / repo / language / symbol / mode / top_k"""
    arguments = {
        "query": args.query,
        "top_k": args.top_k,
        "mode": args.mode,
    }
    if args.repo:
        arguments["repo"] = args.repo
    if args.language:
        arguments["language"] = args.language
    if args.symbol:
        arguments["symbol"] = args.symbol
    result = _call_tool(url, "code_search", arguments)
    _print_json(result)


def cmd_chat(args, url):
    """code_chat: question / repo / language（chat 单独 120s 超时，LLM 推理慢）"""
    arguments = {"question": args.question}
    if args.repo:
        arguments["repo"] = args.repo
    if args.language:
        arguments["language"] = args.language
    # chat 用 120s（KB_CHAT_TIMEOUT 环境变量可覆盖）
    chat_timeout = int(os.environ.get("KB_CHAT_TIMEOUT", CHAT_TIMEOUT_SEC))
    result = _call_tool(url, "code_chat", arguments, timeout=chat_timeout)
    _print_json(result)


def cmd_trace(args, url):
    """code_trace: symbol / repo / direction / depth"""
    arguments = {
        "symbol": args.symbol,
        "direction": args.direction,
        "depth": args.depth,
    }
    if args.repo:
        arguments["repo"] = args.repo
    result = _call_tool(url, "code_trace", arguments)
    _print_json(result)


def cmd_file(args, url):
    """code_file_context: repo / file_name / line_start / line_end (v2.1 改造)"""
    arguments = {
        "repo": args.repo,
        "file_name": args.name,
    }
    if args.line_start:
        arguments["line_start"] = args.line_start
    if args.line_end:
        arguments["line_end"] = args.line_end
    result = _call_tool(url, "code_file_context", arguments)
    _print_json(result)


def cmd_repos(args, url):
    """code_list_repos: 无参数"""
    result = _call_tool(url, "code_list_repos", {})
    _print_json(result)


def main():
    parser = argparse.ArgumentParser(
        description="email-wiki-demo 代码知识库 Python 兜底 CLI（MCP 不可用时使用）",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("KB_MCP_URL", DEFAULT_URL),
        help=f"MCP 端点 URL（默认 {DEFAULT_URL}，可用 KB_MCP_URL 环境变量覆盖）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # search
    p_search = sub.add_parser("search", help="搜索代码库")
    p_search.add_argument("--query", "-q", required=True, help="搜索关键词")
    p_search.add_argument("--repo", "-r", default="", help="限定仓库名")
    p_search.add_argument("--language", "-l", default="", help="限定语言")
    p_search.add_argument("--symbol", "-s", default="", help="限定符号名")
    p_search.add_argument("--mode", default="hybrid", choices=["hybrid", "vector", "symbol", "fts"],
                          help="搜索模式（默认 hybrid）")
    p_search.add_argument("--top_k", type=int, default=10, help="返回前 N 条（默认 10）")
    p_search.set_defaults(func=cmd_search)

    # chat
    p_chat = sub.add_parser("chat", help="RAG 代码问答")
    p_chat.add_argument("--question", required=True, help="问题")
    p_chat.add_argument("--repo", default="", help="限定仓库名")
    p_chat.add_argument("--language", default="", help="限定语言")
    p_chat.set_defaults(func=cmd_chat)

    # trace
    p_trace = sub.add_parser("trace", help="调用链追踪")
    p_trace.add_argument("--symbol", required=True, help="符号名")
    p_trace.add_argument("--repo", default="", help="限定仓库名")
    p_trace.add_argument("--direction", default="both", choices=["callers", "callees", "both", "hierarchy"],
                         help="追踪方向（默认 both；hierarchy = 类继承链）")
    p_trace.add_argument("--depth", type=int, default=2, help="追踪深度 1-3（callers/callees）；hierarchy 1-5（默认 2）")
    p_trace.set_defaults(func=cmd_trace)

    # file
    p_file = sub.add_parser("file", help="读取文件内容（按 file_name）")
    p_file.add_argument("--repo", required=True, help="仓库名")
    p_file.add_argument("--name", required=True, help="文件名（如 login_page.dart）")
    p_file.add_argument("--line_start", type=int, default=0, help="起始行（上下文裁剪）")
    p_file.add_argument("--line_end", type=int, default=0, help="结束行（上下文裁剪）")
    p_file.set_defaults(func=cmd_file)

    # repos
    p_repos = sub.add_parser("repos", help="列出已索引仓库")
    p_repos.set_defaults(func=cmd_repos)

    args = parser.parse_args()
    url = args.url

    # 握手（stateless_http 不强制，但保证协议对齐）
    if not _ensure_init(url):
        print(f"❌ initialize 失败: {url}", file=sys.stderr)
        sys.exit(1)

    # 执行子命令
    args.func(args, url)


if __name__ == "__main__":
    main()
