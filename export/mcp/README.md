# MCP Server — 代码知识库 AI 工具

> 这是 `email-wiki-demo` 代码知识库的 MCP（Model Context Protocol）服务端。
> 暴露 5 个 tools 给 AI 工具调用。

## 文件清单

| 文件 | 角色 |
|------|------|
| `code_mcp_v2.py` | MCP Server 主体（官方 mcp SDK + Streamable HTTP） |
| `requirements.txt` | MCP Server 最小依赖（mcp SDK + FastAPI + sse-starlette） |
| `start_mcp_server.py` | 一键启动脚本（**占位**，等待 P0 实施时实现独立启动模式） |

## 暴露的 Tools

| Tool | 用途 | 参数 |
|------|------|------|
| `code_search` | 混合搜索（向量+关键词+符号） | `query` (必传) / `repo_name` / `top_k` |
| `code_chat` | RAG 代码问答 | `question` (必传) / `repo_name` |
| `code_list_repos` | 列出已索引仓库 | 无 |
| `code_file_context` | 获取文件上下文 | `repo_name` / `file_name` / `line_start` / `line_end`（v2.1 改造：原 `file_path` 入口已废弃）|
| `code_trace` | 调用链追踪 | `symbol` (必传) / `direction` / `depth` / `repo_name` |

## 启动方式

### 方式 A：随 email-wiki-demo 后端启动（当前）

```bash
cd backend
source venv/bin/activate
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000

# MCP 端点：http://<host>:8000/mcp
```

### 方式 B：独立启动（**未来** — 等待 P0 实施）

```bash
# 启动脚本（占位）
python3 start_mcp_server.py --host 0.0.0.0 --port 8000
```

## 端点信息

- **URL**: `http://<your-host>:8000/mcp`
- **协议**: Streamable HTTP (mcp SDK v1.12.4+)
- **传输模式**: stateless_http + json_response
- **认证**: 当前无（内网部署）

## 接入 AI 工具

```bash
# Claude Code
claude mcp add code-kb http://<your-host>:8000/mcp

# Cursor / CodeMaker / OpenCode
# 在配置文件中加：
# {
#   "mcpServers": {
#     "code-kb": {
#       "url": "http://<your-host>:8000/mcp",
#       "transport": "streamable_http"
#     }
#   }
# }
```

## 兜底模式（SKILL.md / 模式 B）

MCP 不可用时，AI 可用 Python 脚本调用（见 `../skill/scripts/kb_api.py` 占位文件）：

```bash
# 等待 P0.1 实施后可用
python3 ../skill/scripts/kb_api.py search --query "邮件发送" --top_k 5
```

## 详细说明

- 升级计划：`../../docs/code-kb-upgrade-plan.md`
- 对标报告：`../../docs/调研/mm-code-search-对标报告-20260611.md`
