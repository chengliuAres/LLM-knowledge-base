# MCP SDK 迁移 + 前端 MCP 接入 Tab 设计

> 日期：2026-06-11 | 状态：设计完成

## 1. 背景与调研结论

### 1.1 现状核对

| 功能 | 是否存在 | 实现方式 |
|------|----------|----------|
| 自动定期刷新索引 | ✅ 存在 | `git_watchdog.py` daemon 线程，60s 轮询 `git status --porcelain`，5s debounce |
| 增量刷新 | ✅ 存在 | `code_config.py:compute_incremental()`，mtime 对比四类差异（added/updated/deleted/skipped） |
| MCP 传输 | ⚠️ 手写 | `code_mcp.py` 手动实现 JSON-RPC 2.0 over SSE，未使用官方 `mcp` SDK |
| MCP chat 流式 | ❌ 不支持 | `code_mcp.py:152` 硬编码 `stream=False` |
| 前端 MCP 说明 | ❌ 无 | 无 MCP 接入介绍页面 |

### 1.2 不需修改的部分
- **自动刷新**（git_watchdog.py）— 已完善，无需改动
- **增量刷新**（compute_incremental）— 已完善，无需改动
- **REST API**（code_routes.py）— 已完善，无需改动

## 2. 后端改造：MCP SDK 迁移

### 2.1 方案选择

**推荐：迁移到官方 `mcp` Python SDK，使用 Streamable HTTP transport**

| 对比维度 | 当前（手写 SSE JSON-RPC） | 迁移后（mcp SDK） |
|----------|--------------------------|-------------------|
| 传输协议 | SSE（GET + POST 双端点） | Streamable HTTP（单端点 `/mcp`） |
| 会话管理 | 手动 `_sessions: dict[str, Queue]` | SDK 内置 SessionManager |
| 协议兼容 | 自实现，可能有边角 bug | 官方维护，与 Claude/Cursor 完全兼容 |
| 流式响应 | 不支持 | SDK 原生支持 streaming |
| 维护成本 | 349 行手写协议代码 | ~150 行工具注册代码 |
| 依赖 | `sse-starlette` | `mcp>=1.0.0` |

### 2.2 实现要点

**依赖变更**：
```diff
# requirements.txt
+ mcp>=1.0.0
  sse-starlette>=3.0.0  # 保留（REST API 其他 SSE 端点仍使用）
```

**新文件 `code_mcp_v2.py`**（替代 `code_mcp.py`）：
- 使用 `mcp.server.FastMCP` 创建 server 实例
- 5 个 tool 通过 `@server.tool()` 装饰器注册
- `code_chat` 支持流式：通过 SDK 的 streaming response 逐 chunk 返回
- 使用 `streamable_http` transport

**`main.py` 变更**：
- mount 方式改为 `app.mount("/mcp", mcp_app)`（SDK 提供 ASGI app）
- 或使用 `mcp_app = server.streamable_http_app()` 然后 mount

**向后兼容**：
- 旧端点 `/mcp/sse` 和 `/mcp/message` 在过渡期保留（加 deprecation 日志）
- 新端点 `/mcp` 作为主入口
- 确认 MCP 协议版本升级到 `2025-03-26`

### 2.3 code_chat 流式支持

当前 REST API `/api/code/chat` 已支持流式（`code_routes.py` SSE StreamingResponse），MCP 端需要对齐：

- `code_chat` tool 调用 `llm_client.chat(messages, stream=True)`
- 通过 SDK 的 tool response streaming 机制逐 chunk 返回
- 若 SDK 版本暂不支持 tool 级流式，则回退为非流式 + 标注 `(streaming 暂未支持)`

### 2.4 向后兼容策略

**Phase 1**（本次）：
- 新建 `code_mcp_v2.py`，使用 mcp SDK
- `main.py` 同时挂载新旧两套 MCP 端点
- 旧端点 `/mcp/sse` 保留但日志提示 "deprecated, use /mcp"

**Phase 2**（后续）：
- 确认所有客户端迁移后，删除 `code_mcp.py` 和旧端点

## 3. 前端改造：MCP 接入 Tab

### 3.1 路由注册

在 `frontend/js/router.js` 的 Routes 对象中新增：

```javascript
"code/mcp": { file: "tabs/code-mcp.html", title: "MCP 接入", init: "initCodeMcp" },
```

### 3.2 侧边栏位置

`frontend/index.html` 侧边栏「代码知识库」分组末尾（代码 LanceDB 下方）新增：

```html
<a class="sidebar-item" data-route="code/mcp" href="#code/mcp">🔌 <span>MCP 接入</span></a>
```

### 3.3 Tab 内容结构

`frontend/tabs/code-mcp.html` — 三子标签页切换（纯 CSS 显示/隐藏，150ms fade）：

| 子标签 | 内容 |
|--------|------|
| **接入指南**（默认） | MCP 协议简介、服务连接信息卡片（地址/端点/协议版本）、5 个可用工具列表（带彩色左边框 + 描述） |
| **客户端配置** | Claude Code CLI / Cursor / Claude Desktop / VS Code Cline 四种配置方法，每个配代码块 + 一键复制按钮 |
| **使用示例** | 4 个典型场景卡片（搜索代码/代码问答/调用链追踪/浏览文件），每个含 query → 预期结果 |

### 3.4 交互细节

- **一键复制**：代码块右上角 📋 按钮，点击后 → ✓ 已复制（2s 恢复），底部 toast "已复制到剪贴板"（3s 自动消失）
- **子标签切换**：无页面跳转，CSS `display` 切换 + `opacity` 过渡 150ms
- **Hover tooltip**：工具名称 hover 显示完整描述
- **颜色系统**：复用现有暗色主题变量，工具列表用彩色左边框区分（绿/蓝/黄/紫/粉）
- **Toast 组件**：简化的 JS toast 函数，复用项目已有的 toast 模式

### 3.5 需 bump `__TAB_VERSION`

**必须**：新增 tab HTML 后，`frontend/index.html` 中 `__TAB_VERSION` 从 `15` → `16`。

## 4. 文件变更清单

| 操作 | 文件 | 说明 |
|------|------|------|
| **新增** | `backend/code_mcp_v2.py` | 基于 mcp SDK 的新 MCP server |
| **修改** | `backend/main.py` | 挂载新 MCP 端点，保留旧端点 |
| **修改** | `backend/requirements.txt` | 添加 `mcp>=1.0.0` |
| **新增** | `frontend/tabs/code-mcp.html` | MCP 接入 tab 页面 |
| **修改** | `frontend/js/router.js` | 注册 `code/mcp` 路由 |
| **修改** | `frontend/index.html` | 侧边栏新增 MCP 接入入口 + bump `__TAB_VERSION` |
| **保留** | `backend/code_mcp.py` | 旧 MCP 实现保留（deprecation 日志），Phase 2 删除 |

## 5. 风险与取舍

| 风险 | 应对 |
|------|------|
| mcp SDK 版本不稳定（<1.0） | 锁定具体版本，旧端点保留做 fallback |
| Streamable HTTP 与旧客户端不兼容 | 双端点共存，渐进迁移 |
| mcp SDK 不支持 tool 级流式 | 回退为非流式，标注说明 |
| 打包机 IP 变化 | Tab 页面动态展示当前 host（从浏览器 `location.host` 读取） |

## 6. 不做的事

- ❌ 不添加认证（用户明确说暂不需要）
- ❌ 不修改 git_watchdog.py（自动刷新已完善）
- ❌ 不修改 code_config.py（增量刷新已完善）
- ❌ 不修改 REST API 端点
- ❌ 不删除旧 code_mcp.py（Phase 2 再做）
