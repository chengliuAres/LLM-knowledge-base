#!/usr/bin/env python3
"""test_e2e_kb_api.py — kb_api.py 端到端验证

跑通 5 个子命令，断言：
- repos 返回 1+ 仓库
- search 返回 1+ 结果
- trace 返回 1+ matched_symbols
- file 不存在的路径返回 error（协议层正确）
- chat 跳过（依赖 LLM 配置）

失败计数 > 0 时 exit 1，便于 CI 集成。
"""

import subprocess
import sys
from pathlib import Path

KB_API = Path(__file__).parent.parent / "export" / "skill" / "scripts" / "kb_api.py"
MCP_URL = "http://localhost:8000/mcp/"


def run(*args):
    """执行 kb_api.py 子命令，返回 (returncode, stdout)。"""
    cmd = ["python3", str(KB_API), "--url", MCP_URL, *args]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return result.returncode, result.stdout, result.stderr


def assert_contains(label, data, *keys):
    """递归检查 data 中至少存在一个 key 路径。"""
    if not isinstance(data, dict):
        print(f"  ❌ {label}: 顶层不是 dict（type={type(data).__name__}）")
        return False
    ok = all(k in data for k in keys)
    if not ok:
        missing = [k for k in keys if k not in data]
        print(f"  ❌ {label}: 缺少字段 {missing}")
    return ok


results = []  # [(label, passed, info)]


# === 1. repos ===
print("\n[1/5] repos")
rc, out, err = run("repos")
try:
    import json
    data = json.loads(out)
    result = data.get("result", data)
    repos = result.get("repos", [])
    if repos:
        print(f"  ✅ 找到 {len(repos)} 个仓库: {[r['name'] for r in repos]}")
        results.append(("repos", True, f"{len(repos)} repos"))
    else:
        print(f"  ❌ 仓库列表为空: {data}")
        results.append(("repos", False, "empty list"))
except Exception as e:
    print(f"  ❌ 解析失败: {e}\n{out[:200]}")
    results.append(("repos", False, str(e)))


# === 2. search ===
print("\n[2/5] search --query '邮件发送'")
rc, out, err = run("search", "--query", "邮件发送", "--top_k", "3")
try:
    data = json.loads(out)
    result = data.get("result", data)
    items = result.get("results", [])
    if items:
        print(f"  ✅ 找到 {len(items)} 条结果, top1: {items[0]['file_path']}")
        results.append(("search", True, f"{len(items)} hits"))
    else:
        print(f"  ❌ 搜索结果为空: {data}")
        results.append(("search", False, "empty"))
except Exception as e:
    print(f"  ❌ 解析失败: {e}\n{out[:200]}")
    results.append(("search", False, str(e)))


# === 3. trace ===
print("\n[3/5] trace --symbol 'sendMail'")
rc, out, err = run("trace", "--symbol", "sendMail", "--direction", "both", "--depth", "1")
try:
    data = json.loads(out)
    result = data.get("result", data)
    symbols = result.get("matched_symbols", [])
    if symbols:
        print(f"  ✅ 找到 {len(symbols)} 个 sendMail 相关符号, top1: {symbols[0]['symbol']}")
        results.append(("trace", True, f"{len(symbols)} symbols"))
    else:
        print(f"  ❌ 调用链为空: {data}")
        results.append(("trace", False, "empty"))
except Exception as e:
    print(f"  ❌ 解析失败: {e}\n{out[:200]}")
    results.append(("trace", False, str(e)))


# === 4. file (按 file_name 唯一命中) ===
# v2.1 改造：原 --path 已废弃，改用 --name 传裸文件名
# 选 mailflutter 仓的 login_page.dart（真实存在且唯一命中）
print("\n[4/5] file --name login_page.dart（v2.1: 唯一命中）")
rc, out, err = run("file", "--repo", "ghmail", "--name", "login_page.dart")
try:
    data = json.loads(out)
    result = data.get("result", data)
    if "content" in result and "file_path" in result:
        # 唯一命中分支
        print(f"  ✅ 唯一命中: {result['file_path']}, {result['total_chunks']} chunks, truncated={result['truncated']}")
        results.append(("file", True, f"unique: {result['file_path']}"))
    elif "candidates" in result:
        # 多匹配分支
        cands = result["candidates"]
        print(f"  ✅ 多匹配返回 candidates: {len(cands)} 个（{cands[0]['file_path']} 等）")
        results.append(("file", True, f"multi-match: {len(cands)} candidates"))
    else:
        print(f"  ❌ 既无 content 也无 candidates: {data}")
        results.append(("file", False, "no content/candidates"))
except Exception as e:
    print(f"  ❌ 解析失败: {e}\n{out[:200]}")
    results.append(("file", False, str(e)))


# === 5. trace hierarchy (P2 新增) — 全量 re-scan 后必须有 inherit 关系 ===
print("\n[5/5] trace --direction hierarchy（P2 继承链追踪）")
# 用真实有继承的符号测（ghmail 仓 473 个 inherit）
rc, out, err = run("trace", "--symbol", "AccountMocker", "--direction", "hierarchy", "--depth", "2")
try:
    data = json.loads(out)
    result = data.get("result", data)
    if result.get("direction") == "hierarchy":
        traces = result.get("traces", [])
        if traces:
            trace = traces[0]
            parents = trace.get("parents", [])
            children = trace.get("children", [])
            chain_nodes = trace.get("chain", {}).get("nodes", [])
            print(f"  ✅ hierarchy 返回: parents={len(parents)}, children={len(children)}, chain_nodes={len(chain_nodes)}")
            if len(chain_nodes) >= 2:  # 至少起始 + 1 个关联
                results.append(("hierarchy", True, f"parents={len(parents)}, children={len(children)}"))
            else:
                print(f"  ❌ chain nodes 太少: {chain_nodes}")
                results.append(("hierarchy", False, "chain too short"))
        else:
            print(f"  ❌ traces 为空: {data}")
            results.append(("hierarchy", False, "empty traces"))
    else:
        print(f"  ❌ direction 不是 hierarchy: {data}")
        results.append(("hierarchy", False, "wrong direction"))
except Exception as e:
    print(f"  ❌ 解析失败: {e}\nout={out[:300]}")
    results.append(("hierarchy", False, str(e)))


# === 5. chat 实跑（SKIP_CHAT=1 时跳过，否则要求 LLM 真正可用）===
print("\n[5/5] chat 实跑（SKIP_CHAT=1 跳过，否则必须 LLM 真可用）")
import os
if os.environ.get("SKIP_CHAT") == "1":
    print("  ⏭️  SKIP_CHAT=1，跳过（手动跳过，非测试通过）")
    results.append(("chat", True, "skipped via SKIP_CHAT=1"))
else:
    rc, out, err = run("chat", "--question", "邮件发送怎么工作")
    try:
        data = json.loads(out)
        # 协议层返回了 dict（含 result 或 error），说明 MCP 协议工作正常
        if "error" in data or "result" in data:
            result = data.get("result", {})
            if "answer" in result:
                # LLM 配置成功
                print(f"  ✅ LLM 可用，answer 长度 {len(result['answer'])} 字符")
                results.append(("chat", True, f"LLM ok, answer={len(result['answer'])} chars"))
            else:
                # 协议 OK 但 LLM 不可用 → 这种不算"通过"，是配置缺失
                err_msg = result.get("error") or data.get("error")
                print(f"  ❌ 协议 OK 但 LLM 不可用: {err_msg[:80]}")
                print(f"     提示：设置 SKIP_CHAT=1 跳过，或配置 LLM_API_KEY 让 LLM 真可用")
                results.append(("chat", False, f"LLM unavailable: {err_msg[:40]}"))
        else:
            print(f"  ❌ 缺 error 和 result: {data}")
            results.append(("chat", False, "missing error/result"))
    except Exception as e:
        print(f"  ❌ 解析失败: {e}\nout={out[:200]}\nerr={err[:200]}")
        results.append(("chat", False, str(e)))


# === 6. MCP 端点健康检查（直接 JSON-RPC 2.0 打 /mcp/）===
# 不走 kb_api.py 包装，直接验证 Streamable HTTP 端点本身活着
# - initialize 握手 → 拿 serverInfo
# - tools/list → 拿工具列表，断言 5 个核心 tool 都在
print("\n[6/6] MCP 端点健康检查（直接 JSON-RPC POST /mcp/）")
import urllib.request
import urllib.error


def mcp_post_rpc(method, params=None):
    """直接 POST JSON-RPC 2.0 到 /mcp/，返回 (status, parsed_dict_or_None, err_str)。"""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or {}
    }
    req = urllib.request.Request(
        MCP_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2024-11-05",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body), ""
    except urllib.error.HTTPError as e:
        return e.code, None, f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return 0, None, f"连接失败: {e.reason}"
    except Exception as e:
        return 0, None, f"{type(e).__name__}: {e}"


# 1) initialize
rc, data, err = mcp_post_rpc("initialize", {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {"name": "test_e2e_kb_api", "version": "1.0.0"},
})
if rc != 200 or data is None or "error" in data:
    print(f"  ❌ initialize 失败: rc={rc}, err={err}, data={data}")
    results.append(("mcp_initialize", False, f"rc={rc}, {err or (data or {}).get('error')}"))
else:
    server_name = (data.get("result", {}).get("serverInfo", {}) or {}).get("name", "?")
    print(f"  ✅ initialize OK: server={server_name}")
    results.append(("mcp_initialize", True, f"server={server_name}"))

    # 2) tools/list
    rc2, data2, err2 = mcp_post_rpc("tools/list", {})
    if rc2 != 200 or data2 is None or "error" in data2:
        print(f"  ❌ tools/list 失败: rc={rc2}, err={err2}, data={data2}")
        results.append(("mcp_tools_list", False, f"rc={rc2}, {err2 or (data2 or {}).get('error')}"))
    else:
        tools = (data2.get("result", {}) or {}).get("tools", [])
        tool_names = [t.get("name") for t in tools]
        print(f"  ✅ tools/list OK: {len(tools)} 工具: {tool_names}")
        expected = {"code_search", "code_chat", "code_trace", "code_file_context", "code_list_repos"}
        missing = expected - set(tool_names)
        if missing:
            print(f"  ❌ 缺核心工具: {missing}")
            results.append(("mcp_tools_list", False, f"missing: {missing}"))
        else:
            results.append(("mcp_tools_list", True, f"{len(tools)} tools"))


# === 汇总 ===
print("\n" + "=" * 50)
print("汇总：")
passed = sum(1 for _, ok, _ in results if ok)
total = len(results)
for label, ok, info in results:
    icon = "✅" if ok else "❌"
    print(f"  {icon} {label}: {info}")
print(f"\n通过：{passed}/{total}")

sys.exit(0 if passed == total else 1)
