# MCP SDK 迁移 + MCP 接入 Tab 实现计划

> **For agentic workers:** 使用 superpowers:subagent-driven-development (推荐) 或 superpowers:executing-plans 逐任务实现。步骤使用 checkbox (`- [ ]`) 追踪。

**Goal:** 将 MCP 传输从手写 SSE JSON-RPC 迁移到官方 mcp SDK (Streamable HTTP)，新增 MCP chat 流式支持，新增前端 MCP 接入说明 Tab。

**Architecture:** 新建 `code_mcp_v2.py` 使用 `mcp.server.fastmcp.FastMCP` + `streamable_http_app()` 挂载到 FastAPI。新旧端点共存（`/mcp` 新 + `/mcp/sse` 旧保留带 deprecation）。前端新增三子标签页 tab (接入指南/客户端配置/使用示例)。

**Tech Stack:** Python mcp SDK v1.x, FastAPI lifespan, vanilla JS tab 页面, Tailwind 暗色主题

---

### Task 1: 更新 requirements.txt

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: 添加 mcp SDK 依赖**

```diff
  sse-starlette>=3.0.0
+ mcp>=1.10.0
```

**说明**: `sse-starlette` 保留（REST API 的 scan 进度 SSE 可能仍在使用）。

- [ ] **Step 2: 安装新依赖**

```bash
cd backend && source venv/bin/activate && pip install "mcp>=1.10.0"
```

- [ ] **Step 3: 确认导入成功**

```bash
cd backend && source venv/bin/activate && python3 -c "from mcp.server.fastmcp import FastMCP; print('OK')"
```

Expected: 输出 `OK`，无 ImportError。

- [ ] **Step 4: Commit**

```bash
git add backend/requirements.txt
git commit -m "chore: 添加 mcp SDK 依赖"
```

---

### Task 2: 创建 code_mcp_v2.py (MCP SDK 实现)

**Files:**
- Create: `backend/code_mcp_v2.py`

- [ ] **Step 1: 创建新文件，定义 MCP server 实例**

```python
"""MCP Server v2 — 代码知识库 AI 工具 (官方 mcp SDK, Streamable HTTP)

基于 mcp SDK v1.x, 使用 FastMCP + streamable_http_app 挂载到 FastAPI。

暴露 5 个 tools:
- code_search: 搜索代码库
- code_chat: RAG 代码问答 (非流式, stream=False)
- code_list_repos: 列出已索引仓库
- code_file_context: 获取文件上下文
- code_trace: 调用链追踪
"""

from mcp.server.fastmcp import FastMCP

# 创建 MCP server（stateless + json_response）
mcp = FastMCP("CodeKB", stateless_http=True, json_response=True)
# 设置 endpoint 路径为 /，这样 Mount("/mcp") 后客户端连 http://host/mcp
mcp.settings.streamable_http_path = "/"
```

- [ ] **Step 2: 注册 code_search tool**

```python
@mcp.tool()
async def code_search(
    query: str,
    repo: str = "",
    language: str = "",
    symbol: str = "",
    mode: str = "hybrid",
    top_k: int = 10,
) -> str:
    """搜索代码库，支持语义搜索和关键词搜索"""
    import json
    from code_search import search_code

    result = search_code(
        query=query.strip(),
        mode=mode,
        top_k=min(max(top_k, 1), 100),
        repo_name=repo or None,
        language=language or None,
        symbol_name=symbol or None,
    )
    # 精简返回（去掉 vector/metadata 大字段）
    for r in result["results"]:
        r.pop("vector", None)
        r.pop("metadata", None)
    return json.dumps({
        "results": result["results"],
        "mode": result["mode"],
        "count": len(result["results"]),
    }, ensure_ascii=False, indent=2)
```

- [ ] **Step 3: 注册 code_chat tool**

```python
@mcp.tool()
async def code_chat(
    question: str,
    repo: str = "",
    language: str = "",
) -> str:
    """基于代码知识库的 RAG 问答"""
    import json
    from code_search import search_code
    from llm_client import get_llm_client

    client = get_llm_client()
    if not client:
        return json.dumps({"error": "LLM 未配置，无法进行问答"}, ensure_ascii=False)

    search_result = search_code(
        query=question,
        mode="hybrid",
        top_k=5,
        repo_name=repo or None,
        language=language or None,
    )

    sources = search_result["results"]
    if not sources:
        return json.dumps({"answer": "未找到相关代码片段", "sources": []}, ensure_ascii=False)

    context_parts = []
    for i, s in enumerate(sources, 1):
        ctx = f"[{i}] {s['file_path']}:{s['line_start']}-{s['line_end']} ({s['symbol_name']})\n```\n{s['content']}\n```"
        context_parts.append(ctx)

    context = "\n\n".join(context_parts)
    messages = [
        {"role": "system", "content": "你是代码助手，基于检索到的代码片段回答问题。回答时引用具体的文件路径和行号。"},
        {"role": "user", "content": f"代码片段:\n{context}\n\n问题: {question}"},
    ]

    answer = await client.chat(messages, stream=False)

    return json.dumps({
        "answer": answer,
        "sources": [{"file_path": s["file_path"], "symbol_name": s["symbol_name"],
                     "line_start": s["line_start"], "line_end": s["line_end"]} for s in sources],
    }, ensure_ascii=False, indent=2)
```

- [ ] **Step 4: 注册 code_list_repos tool**

```python
@mcp.tool()
async def code_list_repos() -> str:
    """列出已索引的代码仓库"""
    import json
    from code_config import list_repos
    return json.dumps({"repos": list_repos()}, ensure_ascii=False, indent=2)
```

- [ ] **Step 5: 注册 code_file_context tool**

```python
@mcp.tool()
async def code_file_context(
    repo: str,
    file_path: str,
    line_start: int = 0,
    line_end: int = 0,
) -> str:
    """获取某个文件的上下文内容"""
    import json
    from code_db import get_chunks_by_file

    chunks = get_chunks_by_file(repo, file_path)
    if not chunks:
        return json.dumps({"error": f"文件不存在: {repo}/{file_path}"}, ensure_ascii=False)

    content = "\n".join(c["content"] for c in chunks)

    if line_start > 0 and line_end > 0:
        lines = content.split("\n")
        start = max(0, line_start - 11)
        end = min(len(lines), line_end + 10)
        content = "\n".join(lines[start:end])

    truncated = len(content) > 5000
    if truncated:
        content = content[:5000]

    return json.dumps({
        "repo": repo,
        "file_path": file_path,
        "content": content,
        "total_chunks": len(chunks),
        "truncated": truncated,
    }, ensure_ascii=False, indent=2)
```

- [ ] **Step 6: 注册 code_trace tool**

```python
@mcp.tool()
async def code_trace(
    symbol: str,
    repo: str = "",
    direction: str = "both",
    depth: int = 2,
) -> str:
    """追踪符号的调用链：谁调用了它 / 它调用了谁"""
    import json
    from code_search import trace_code

    result = trace_code(
        symbol_name=symbol,
        repo_name=repo or "",
        direction=direction,
        depth=min(max(depth, 1), 3),
    )
    result.pop("steps", None)
    return json.dumps(result, ensure_ascii=False, indent=2)
```

- [ ] **Step 7: 自测导入无误**

```bash
cd backend && source venv/bin/activate && python3 -c "from code_mcp_v2 import mcp; print('Server name:', mcp.name)"
```

Expected: `Server name: CodeKB`

- [ ] **Step 8: Commit**

```bash
git add backend/code_mcp_v2.py
git commit -m "feat: 新建 MCP v2 server (mcp SDK + Streamable HTTP)"
```

---

### Task 3: 修改 main.py 挂载新 MCP 端点

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: 在 lifespan 中添加 MCP session manager 生命周期**

将 `main.py` 的 lifespan 函数（第 44-60 行）修改为：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期：启动时配置日志 + 初始化邮件 DB + 启动 git watchdog + MCP session manager；关闭时停止。"""
    configure_logging()
    log.info("服务启动")
    init_db()
    init_sample_data()

    # 启动 git watchdog 后台线程（git 仓库变更自动触发增量扫描）
    from git_watchdog import start_watchdog, stop_watchdog
    start_watchdog()

    # 启动 MCP v2 session manager
    from code_mcp_v2 import mcp as mcp_v2
    async with mcp_v2.session_manager.run():
        log.info("服务启动完成")
        yield

    # 关闭时停止 watchdog（让线程在 daemon 退前能干净退出）
    stop_watchdog()
```

- [ ] **Step 2: 挂载新 MCP 端点**

在 `main.py` 第 63-66 行（`app = FastAPI(...)` 之后，`app.include_router(code_router)` 之前）修改为：

```python
app = FastAPI(title="文档知识库", version="2.0.0", lifespan=lifespan)
app.include_router(code_router)
app.include_router(mcp_router)  # 旧 MCP (SSE), 保留兼容
app.include_router(log_router)

# 挂载新 MCP v2 (Streamable HTTP) — 客户端连 http://host/mcp
from code_mcp_v2 import mcp as mcp_v2
app.mount("/mcp", app=mcp_v2.streamable_http_app())
```

**注意**: `app.mount` 必须放在 `app.include_router` 之后，因为 Starlette 的 mount 优先级高于 router。

- [ ] **Step 3: 在旧 code_mcp.py 添加 deprecation 日志**

在 `backend/code_mcp.py` 第 25 行（`router = APIRouter(tags=["mcp"])`）之后添加：

```python
# Deprecation 警告：新 MCP 端点已迁移到 /mcp (code_mcp_v2.py)，旧端点计划在 Phase 2 移除
import warnings
warnings.warn("code_mcp (SSE) is deprecated, use code_mcp_v2 (Streamable HTTP) at /mcp", DeprecationWarning, stacklevel=2)
```

- [ ] **Step 4: 自测 FastAPI 启动成功**

```bash
cd backend && source venv/bin/activate && python3 -c "
from main import app
print('Routes:')
for r in app.routes:
    print(f'  {getattr(r, \"path\", r)}')
"
```

Expected: 应该看到 `/mcp` mount 和 `/mcp/sse`、`/mcp/message` 端点共存。

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/code_mcp.py
git commit -m "feat: 挂载 MCP v2 (Streamable HTTP) + 旧端点保留兼容"
```

---

### Task 4: 创建 MCP 接入 Tab 页面

**Files:**
- Create: `frontend/tabs/code-mcp.html`

- [ ] **Step 1: 创建 code-mcp.html**

新建 `frontend/tabs/code-mcp.html`，内容如下（完整代码）：

```html
<!-- MCP 接入 Tab — 接入指南 / 客户端配置 / 使用示例 -->
<div class="p-5 space-y-5">
  <!-- 页头 -->
  <h2 class="text-lg font-semibold text-white">🔌 MCP 接入</h2>
  <p class="text-sm" style="color: var(--color-muted);">MCP (Model Context Protocol) 是 AI 助手与外部工具之间的开放标准协议。连接后，Claude Code、Cursor 等 AI 工具可以直接搜索代码、追踪调用链、进行 RAG 问答。</p>

  <!-- 子标签切换（接入指南 / 客户端配置 / 使用示例） -->
  <div class="flex gap-2 border-b pb-3" style="border-color: var(--color-border);">
    <button class="mcp-subtab-btn active px-3 py-1.5 rounded text-sm font-medium transition-colors" data-mcp-tab="guide"
      style="background: var(--color-accent); color: var(--color-on-primary);" onclick="switchMcpTab('guide')">📖 接入指南</button>
    <button class="mcp-subtab-btn px-3 py-1.5 rounded text-sm font-medium transition-colors" data-mcp-tab="config"
      style="color: var(--color-muted);" onclick="switchMcpTab('config')">⚙️ 客户端配置</button>
    <button class="mcp-subtab-btn px-3 py-1.5 rounded text-sm font-medium transition-colors" data-mcp-tab="examples"
      style="color: var(--color-muted);" onclick="switchMcpTab('examples')">💡 使用示例</button>
  </div>

  <!-- 内容区 -->
  <div id="mcp-tab-guide" class="mcp-tab-content space-y-4">
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <!-- 左：服务连接信息 -->
      <div>
        <h3 class="text-sm font-semibold text-white mb-3">📡 服务连接信息</h3>
        <div class="rounded-lg p-4 space-y-3 text-sm font-mono" style="background: var(--color-surface);">
          <div class="flex justify-between items-center">
            <span style="color: var(--color-muted);">服务地址</span>
            <span class="font-semibold" style="color: var(--color-accent);" id="mcp-server-url">—</span>
          </div>
          <div class="flex justify-between items-center">
            <span style="color: var(--color-muted);">MCP 端点</span>
            <span class="font-semibold" style="color: var(--color-accent);">/mcp</span>
          </div>
          <div class="flex justify-between items-center">
            <span style="color: var(--color-muted);">传输协议</span>
            <span class="font-semibold" style="color: var(--color-accent);">Streamable HTTP</span>
          </div>
          <div class="flex justify-between items-center">
            <span style="color: var(--color-muted);">新端点</span>
            <span class="font-semibold" style="color: var(--color-accent);">/mcp (官方 SDK)</span>
          </div>
          <div class="flex justify-between items-center">
            <span style="color: var(--color-muted);">旧端点 (兼容)</span>
            <span class="font-semibold" style="color: var(--color-muted);">/mcp/sse</span>
          </div>
        </div>
      </div>

      <!-- 右：可用工具列表 -->
      <div>
        <h3 class="text-sm font-semibold text-white mb-3">🛠️ 可用工具（5个）</h3>
        <div class="space-y-2 text-sm">
          <div class="rounded p-3" style="background: var(--color-surface); border-left: 3px solid #22C55E;" title="混合搜索（向量+关键词+符号），支持中文查询自动翻译">
            <span class="font-semibold" style="color: #22C55E;">code_search</span>
            <span style="color: var(--color-muted);"> — 混合搜索代码，支持中文查询</span>
          </div>
          <div class="rounded p-3" style="background: var(--color-surface); border-left: 3px solid #3B82F6;" title="基于搜索到的代码片段 + LLM 生成回答">
            <span class="font-semibold" style="color: #3B82F6;">code_chat</span>
            <span style="color: var(--color-muted);"> — RAG 代码问答</span>
          </div>
          <div class="rounded p-3" style="background: var(--color-surface); border-left: 3px solid #F59E0B;" title="BFS 多跳追踪，方向可选 callers/callees/both，深度 1-3">
            <span class="font-semibold" style="color: #F59E0B;">code_trace</span>
            <span style="color: var(--color-muted);"> — 调用链追踪 (callers/callees)</span>
          </div>
          <div class="rounded p-3" style="background: var(--color-surface); border-left: 3px solid #8B5CF6;" title="获取文件完整内容，可选行号范围">
            <span class="font-semibold" style="color: #8B5CF6;">code_file_context</span>
            <span style="color: var(--color-muted);"> — 获取文件内容</span>
          </div>
          <div class="rounded p-3" style="background: var(--color-surface); border-left: 3px solid #EC4899;" title="列出所有已索引的代码仓库及其统计信息">
            <span class="font-semibold" style="color: #EC4899;">code_list_repos</span>
            <span style="color: var(--color-muted);"> — 列出已索引仓库</span>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div id="mcp-tab-config" class="mcp-tab-content hidden space-y-4">
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <!-- Claude Code CLI -->
      <div>
        <h3 class="text-sm font-semibold text-white mb-2">Claude Code (CLI)</h3>
        <div class="rounded-lg p-3 font-mono text-sm relative" style="background: var(--color-surface);">
          <button class="absolute top-2 right-2 text-xs px-2 py-1 rounded transition-colors"
            style="background: var(--color-secondary); color: var(--color-foreground); border: 1px solid var(--color-border);"
            onclick="copyMcpCode(this, 'claude mcp add code-kb REPLACE_URL/mcp')">📋 复制</button>
          <code style="color: var(--color-accent); display: block; padding-top: 8px;">claude mcp add code-kb <span class="mcp-url-placeholder">http://打包机IP:8000</span>/mcp</code>
        </div>
      </div>

      <!-- Cursor -->
      <div>
        <h3 class="text-sm font-semibold text-white mb-2">Cursor IDE</h3>
        <div class="rounded-lg p-3 font-mono text-sm relative" style="background: var(--color-surface);">
          <button class="absolute top-2 right-2 text-xs px-2 py-1 rounded transition-colors"
            style="background: var(--color-secondary); color: var(--color-foreground); border: 1px solid var(--color-border);"
            onclick="copyMcpCode(this, '{\n  \"mcpServers\": {\n    \"code-kb\": {\n      \"url\": \"REPLACE_URL/mcp\"\n    }\n  }\n}')">📋 复制</button>
          <code style="color: var(--color-foreground); display: block; padding-top: 8px; white-space: pre;">{
  "mcpServers": {
    "code-kb": {
      "url": "<span class="mcp-url-placeholder">http://打包机IP:8000</span>/mcp"
    }
  }
}</code>
        </div>
      </div>

      <!-- Claude Desktop -->
      <div>
        <h3 class="text-sm font-semibold text-white mb-2">Claude Desktop</h3>
        <div class="rounded-lg p-3 font-mono text-sm relative" style="background: var(--color-surface);">
          <button class="absolute top-2 right-2 text-xs px-2 py-1 rounded transition-colors"
            style="background: var(--color-secondary); color: var(--color-foreground); border: 1px solid var(--color-border);"
            onclick="copyMcpCode(this, '{\n  \"mcpServers\": {\n    \"code-kb\": {\n      \"command\": \"npx\",\n      \"args\": [\n        \"-y\", \"@anthropic-ai/mcp-client\",\n        \"REPLACE_URL/mcp\"\n      ]\n    }\n  }\n}')">📋 复制</button>
          <code style="color: var(--color-foreground); display: block; padding-top: 8px; white-space: pre;">{
  "mcpServers": {
    "code-kb": {
      "command": "npx",
      "args": [
        "-y", "@anthropic-ai/mcp-client",
        "<span class="mcp-url-placeholder">http://打包机IP:8000</span>/mcp"
      ]
    }
  }
}</code>
        </div>
      </div>

      <!-- VS Code / Cline -->
      <div>
        <h3 class="text-sm font-semibold text-white mb-2">VS Code / Cline</h3>
        <div class="rounded-lg p-3 font-mono text-sm relative" style="background: var(--color-surface);">
          <button class="absolute top-2 right-2 text-xs px-2 py-1 rounded transition-colors"
            style="background: var(--color-secondary); color: var(--color-foreground); border: 1px solid var(--color-border);"
            onclick="copyMcpCode(this, '{\n  \"mcpServers\": {\n    \"code-kb\": {\n      \"url\": \"REPLACE_URL/mcp\",\n      \"transport\": \"streamable-http\"\n    }\n  }\n}')">📋 复制</button>
          <code style="color: var(--color-foreground); display: block; padding-top: 8px; white-space: pre;">{
  "mcpServers": {
    "code-kb": {
      "url": "<span class="mcp-url-placeholder">http://打包机IP:8000</span>/mcp",
      "transport": "streamable-http"
    }
  }
}</code>
        </div>
      </div>
    </div>
  </div>

  <div id="mcp-tab-examples" class="mcp-tab-content hidden space-y-4">
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-3">
      <div class="rounded-lg p-4 text-sm" style="background: var(--color-surface); border-left: 3px solid #22C55E;">
        <div class="font-semibold mb-1" style="color: #22C55E;">🔍 搜索代码</div>
        <div class="mb-2" style="color: var(--color-muted);">"搜索邮件发送相关的代码"</div>
        <div class="rounded p-2 text-xs font-mono" style="background: var(--color-background); color: var(--color-muted);">
          → code_search(query="邮件发送", repo="mailflutter")<br>
          → 返回 SendMailPage, MailService 等结果
        </div>
      </div>
      <div class="rounded-lg p-4 text-sm" style="background: var(--color-surface); border-left: 3px solid #3B82F6;">
        <div class="font-semibold mb-1" style="color: #3B82F6;">💬 代码问答</div>
        <div class="mb-2" style="color: var(--color-muted);">"这段邮件发送逻辑是怎么工作的？"</div>
        <div class="rounded p-2 text-xs font-mono" style="background: var(--color-background); color: var(--color-muted);">
          → code_chat(question="...", repo="mailflutter")<br>
          → RAG 检索 → LLM 解释，返回来源引用
        </div>
      </div>
      <div class="rounded-lg p-4 text-sm" style="background: var(--color-surface); border-left: 3px solid #F59E0B;">
        <div class="font-semibold mb-1" style="color: #F59E0B;">🔗 调用链追踪</div>
        <div class="mb-2" style="color: var(--color-muted);">"谁调用了 sendMail？它又调用了谁？"</div>
        <div class="rounded p-2 text-xs font-mono" style="background: var(--color-background); color: var(--color-muted);">
          → code_trace(symbol="sendMail", direction="both")<br>
          → BFS 多跳，返回调用图 + 被调用图
        </div>
      </div>
      <div class="rounded-lg p-4 text-sm" style="background: var(--color-surface); border-left: 3px solid #8B5CF6;">
        <div class="font-semibold mb-1" style="color: #8B5CF6;">📄 浏览文件</div>
        <div class="mb-2" style="color: var(--color-muted);">"帮我看下 MailService.dart 的代码"</div>
        <div class="rounded p-2 text-xs font-mono" style="background: var(--color-background); color: var(--color-muted);">
          → code_file_context(repo="mailflutter", file_path="...")<br>
          → 返回文件完整内容
        </div>
      </div>
    </div>
  </div>

  <!-- Toast -->
  <div id="mcp-toast" class="fixed bottom-6 right-6 px-4 py-2 rounded-lg text-sm font-medium transition-all duration-300 opacity-0 pointer-events-none"
    style="background: var(--color-accent); color: var(--color-on-primary); z-index: 9999;"></div>
</div>

<script>
(function () {
  // 从当前页面 URL 读取 host 用作展示
  const urlPlaceholders = document.querySelectorAll('.mcp-url-placeholder');
  urlPlaceholders.forEach(el => {
    el.textContent = location.protocol + '//' + location.host;
  });

  const urlEl = document.getElementById('mcp-server-url');
  if (urlEl) {
    urlEl.textContent = location.protocol + '//' + location.host;
  }
})();
</script>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/tabs/code-mcp.html
git commit -m "feat: 新增 MCP 接入 Tab 页面"
```

---

### Task 5: 注册 MCP 路由 + 添加切换逻辑

**Files:**
- Modify: `frontend/js/router.js`
- Modify: `frontend/tabs/code-mcp.html` (追加 JS 逻辑)
- Create: `frontend/tabs/code-mcp.js` (独立 JS 文件)

- [ ] **Step 1: router.js 注册路由**

在 `frontend/js/router.js` 的 Routes 对象（第 23 行之后）添加：

```javascript
"code/mcp":       { file: "tabs/code-mcp.html",    title: "MCP 接入",    init: "initCodeMcp" },
```

- [ ] **Step 2: 创建独立 JS 文件处理 MCP Tab 逻辑**

创建 `frontend/js/code-mcp.js`：

```javascript
/**
 * MCP 接入 Tab 交互逻辑：
 * - 子标签切换 (接入指南/客户端配置/使用示例)
 * - 一键复制代码
 */

function switchMcpTab(tabId) {
  // 更新按钮状态
  document.querySelectorAll('.mcp-subtab-btn').forEach(btn => {
    const isActive = btn.dataset.mcpTab === tabId;
    btn.classList.toggle('active', isActive);
    btn.style.background = isActive ? 'var(--color-accent)' : '';
    btn.style.color = isActive ? 'var(--color-on-primary)' : 'var(--color-muted)';
  });

  // 切换内容区
  document.querySelectorAll('.mcp-tab-content').forEach(content => {
    content.classList.toggle('hidden', content.id !== 'mcp-tab-' + tabId);
  });
}

function copyMcpCode(btn, codeText) {
  // 替换 URL 占位符
  const url = location.protocol + '//' + location.host;
  const text = codeText.replace('REPLACE_URL', url);

  navigator.clipboard.writeText(text).then(() => {
    // 按钮反馈
    const origText = btn.textContent;
    btn.textContent = '✓ 已复制';
    btn.style.color = 'var(--color-accent)';
    setTimeout(() => {
      btn.textContent = origText;
      btn.style.color = '';
    }, 2000);

    // Toast 提示
    showMcpToast('已复制到剪贴板');
  }).catch(() => {
    showMcpToast('复制失败，请手动复制');
  });
}

function showMcpToast(msg) {
  const toast = document.getElementById('mcp-toast');
  if (!toast) return;
  toast.textContent = msg;
  toast.classList.remove('opacity-0');
  toast.classList.add('opacity-100');
  setTimeout(() => {
    toast.classList.remove('opacity-100');
    toast.classList.add('opacity-0');
  }, 3000);
}

window.initCodeMcp = function () {
  // Tab 切换按钮事件已通过 onclick 内联绑定，无需额外初始化
  // 更新 URL 占位符
  const urlPlaceholders = document.querySelectorAll('.mcp-url-placeholder');
  const serverUrl = location.protocol + '//' + location.host;
  urlPlaceholders.forEach(el => { el.textContent = serverUrl; });

  const urlEl = document.getElementById('mcp-server-url');
  if (urlEl) { urlEl.textContent = serverUrl; }
};
```

- [ ] **Step 3: 更新 code-mcp.html 引用外部 JS**

在 `frontend/tabs/code-mcp.html` 底部 `<script>` 标签中，把初始化逻辑替换为引用：

```html
<script>
(function () {
  const serverUrl = location.protocol + '//' + location.host;
  document.querySelectorAll('.mcp-url-placeholder').forEach(el => {
    el.textContent = serverUrl;
  });
  const urlEl = document.getElementById('mcp-server-url');
  if (urlEl) urlEl.textContent = serverUrl;
})();
</script>
```

- [ ] **Step 4: 在 index.html 引入 code-mcp.js**

在 `frontend/index.html` 第 298 行（`glossary-tooltip.js` 之后）添加：

```html
<script src="js/code-mcp.js?v=1"></script>
```

- [ ] **Step 5: Commit**

```bash
git add frontend/js/router.js frontend/js/code-mcp.js frontend/tabs/code-mcp.html frontend/index.html
git commit -m "feat: 注册 MCP 路由 + 脚本 + index.html 引用"
```

---

### Task 6: 侧边栏新增 MCP 接入入口 + bump __TAB_VERSION

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: 侧边栏新增入口**

在 `frontend/index.html` 第 49 行（代码 LanceDB 条目）之后插入新条目：

```html
<a class="sidebar-item" data-route="code/mcp"     href="#code/mcp">🔌 <span>MCP 接入</span></a>
```

- [ ] **Step 2: bump __TAB_VERSION**

`frontend/index.html` 第 308 行：

```diff
- window.__TAB_VERSION = '15';
+ window.__TAB_VERSION = '16';
```

并追加 bump 注释：

```javascript
// bump 13: 新增 MCP 接入 Tab（code-mcp.html），需重新 fetch tab HTML
```

- [ ] **Step 3: Commit**

```bash
git add frontend/index.html
git commit -m "feat: 侧边栏新增 MCP 接入入口, bump __TAB_VERSION=16"
```

---

### Task 7: 回归验证

- [ ] **Step 1: 确认 Python 导入无误**

```bash
cd backend && source venv/bin/activate && python3 -c "
from code_mcp_v2 import mcp
from main import app
print('Server:', mcp.name)
print('Routes:', len(app.routes))
"
```

Expected: `Server: CodeKB`，Routes 数量合理。

- [ ] **Step 2: 启动服务确认无 crash**

```bash
cd backend && source venv/bin/activate && timeout 5 python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 2>&1 || true
```

Expected: 看到 "服务启动完成" 日志，无 traceback。

- [ ] **Step 3: 检查前端 HTML 语法**

检查 `code-mcp.html` 和 `code-mcp.js` 无明显的 JS 语法错误。

- [ ] **Step 4: 检查侧边栏新增条目在 index.html 中的位置**

确认新条目在「代码知识库」分组内，代码 LanceDB 下方。

- [ ] **Step 5: Commit**

```bash
# 如有修改则 commit，否则跳过
```

---

## 验证清单

| # | 检查项 | 方法 |
|---|--------|------|
| 1 | `mcp` 包安装成功 | `pip show mcp` |
| 2 | `code_mcp_v2.py` 可导入 | `python3 -c "from code_mcp_v2 import mcp"` |
| 3 | 新端点 `/mcp` 挂载成功 | 检查 main.py routes |
| 4 | 旧端点 `/mcp/sse` 仍可访问 | 检查 main.py 仍有 `include_router(mcp_router)` |
| 5 | `__TAB_VERSION` = 16 | `grep __TAB_VERSION frontend/index.html` |
| 6 | 侧边栏有 🔌 MCP 接入 | `grep "MCP 接入" frontend/index.html` |
| 7 | Routes 有 code/mcp | `grep "code/mcp" frontend/js/router.js` |
| 8 | 服务启动无 crash | `uvicorn main:app` 启动看日志 |
