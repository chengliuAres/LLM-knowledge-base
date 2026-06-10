# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## 项目概述

基于 LanceDB + sentence-transformers 的本地文档知识库 Demo，支持文档上传、邮件导入、代码索引、向量搜索和 RAG 问答。支持 MCP 协议对外暴露 AI 工具能力。这是一个 email-wiki 技术验证项目，演示 Karpathy LLM-wiki 方案在邮件/代码场景的核心链路。

## 启动与运行

```bash
# 一键启动（自动创建 venv 并安装依赖）
./start.sh

# 手动启动
cd backend
source venv/bin/activate
python3 main.py
# 访问: http://localhost:8000
```

## 环境配置

在 `backend/.env` 中配置 LLM（可选，问答功能需要）：

```bash
LLM_PROVIDER=openai        # openai / ollama / xiaomi（默认）
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-3.5-turbo
```

> **注意**：`llm_client.py` 中硬编码了小米 MiMo 的 API Key 作为默认值，`LLM_PROVIDER` 未设置时默认走 xiaomi。

## 架构要点

### 数据流

```
文档上传 → parser.py（分块）→ embedder.py（384维向量）→ db.py（LanceDB）
邮件导入 → email_db.py（SQLite）→ email_parser.py（转换分块）→ embedder.py → db.py
代码扫描 → code_parser.py（tree-sitter AST 分块 + 调用关系提取）→ code_embedder.py → code_db.py（LanceDB + SQLite FTS5 + code_relations）
用户查询 → embedder.py（查询向量化）→ db.py/code_db.py（向量搜索）→ llm_client.py（RAG）
调用链追踪 → code_search.py（混搜定位符号）→ code_db.py（trace_chain BFS 多跳追踪）
MCP 调用 → code_mcp.py（MCP tools）→ code_search.py / llm_client.py
```

### 关键设计决策

- **Embedding 模型**：文档用 `BAAI/bge-base-zh-v1.5`（768维），代码用 `BAAI/bge-small-en-v1.5`（384维），启动时单例预加载，模型存储在项目 `models/` 目录
- **LanceDB 元数据**：metadata 字段以 JSON 字符串存储（非原生 JSON），读写时需手动 `json.dumps/loads`
- **相似度计算**：LanceDB 使用余弦距离（cosine），通过 `(1 - distance + 1) / 2` 转换为 `[0,1]` 相似度分数，低于 0.3 的结果被过滤
- **搜索能力边界**：`/api/search` 和 `/api/chat` 走向量搜索（LanceDB）；`/api/emails/search` 走 SQL `LIKE`（仅搜 SQLite 原始邮件，不走向量）
- **步骤追踪**：`StepTracker` 贯穿搜索/问答/导入全链路，每步耗时透传前端展示
- **前端**：Hash SPA 路由 + 懒加载 tab HTML 片段（10 个独立 tab），Tailwind CDN + 暗色主题 CSS 变量，无构建步骤，FastAPI 直接 serve

### LanceDB 表结构（`documents` 表）

```
id            : str   — "{filename}_{chunk_index}"，主键
filename      : str   — 文件名（邮件为 "email_{id}.eml"）
chunk_index   : int   — 当前文件第 N 个分块
content       : str   — 文本内容
vector        : [float; 768]
file_type     : str   — ".pdf" / ".md" / ".txt" / ".docx" / ".eml"
uploaded_at   : str   — ISO 格式时间戳
metadata      : str   — JSON 字符串（邮件含 email_id/thread_id/subject/sender 等；普通文档为 "{}"）
```

### 分块策略（两套，差异注意）

| 模块 | 策略 | Overlap |
|------|------|---------|
| `parser.py` | 按双换行段落合并 ≤500字符，超长段落按句号/问号/感叹号切 | 50字符 |
| `email_parser.py` | 同样按段落合并 ≤500字符 | **无 overlap** |

### 邮件示例数据结构

`email_db.py` 的 `init_sample_data()` 在 SQLite 为空时自动生成 50 封模拟邮件：
- `thread_id = "thread_{i//3}"`：每 3 封邮件共享一个线程，共约 17 个线程
- 8 个模拟发件人，文件夹分布：INBOX（多）/ Sent / Drafts
- SQLite `emails` 表建了 `idx_thread`、`idx_sender`、`idx_received` 三个索引

### 数据存储

| 路径 | 内容 |
|------|------|
| `data/lancedb/` | 向量数据库（文档 chunks + 邮件 chunks） |
| `data/emails.db` | SQLite 邮件数据库（示例邮件） |
| `data/code_lancedb/` | 代码向量数据库（独立目录） |
| `data/code_index.db` | 代码 SQLite FTS5 全文索引 + 调用关系表（`code_relations`） |
| `data/code_repos.json` | 已索引仓库的配置和状态 |
| `uploads/` | 用户上传的原始文件 |

### 各模块职责

- `main.py`：FastAPI 路由入口，协调各模块
- `parser.py`：PDF/TXT/MD/DOCX 解析 → 按段落分块（≤500字符）
- `embedder.py`：sentence-transformers 单例封装，`embed_text` / `embed_batch`
- `db.py`：LanceDB CRUD，`id` 字段格式为 `{filename}_{chunk_index}`
- `email_db.py`：SQLite 邮件库操作 + 自动生成 50 封示例邮件
- `email_parser.py`：邮件 dict → LanceDB 兼容的 chunk 列表（file_type=`.eml`）
- `llm_client.py`：OpenAI 兼容客户端，支持流式/非流式，`build_rag_prompt` 构造提示词
- `step_tracker.py`：轻量执行步骤记录器（`Step` dataclass）
- `code_parser.py`：tree-sitter AST 解析 + 混合分块 + 调用关系提取（代码知识库）
- `code_db.py`：LanceDB + SQLite FTS5 双存储 + 调用关系表 `code_relations`（代码知识库）
- `code_search.py`：混合搜索 + RRF 融合排序 + `trace_code` 调用链追踪（代码知识库）
- `code_routes.py`：代码知识库 REST API 路由
- `code_mcp.py`：MCP server + tools（SSE 传输）
- `code_config.py`：扫描配置管理（code_repos.json）

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/upload` | 上传文档（PDF/TXT/MD/DOCX） |
| POST | `/api/search` | 向量搜索，返回结果 + 执行步骤 |
| POST | `/api/chat` | RAG 问答，支持 `stream: true` |
| POST | `/api/emails/import` | 从 SQLite 邮件库导入到 LanceDB |
| GET | `/api/documents` | 文档列表（按文件名聚合） |
| GET | `/api/emails` | 邮件列表 |
| GET | `/api/emails/search` | 关键词搜索邮件 |
| DELETE | `/api/documents/{filename}` | 删除文档及其所有 chunks |
| GET | `/api/stats` | 文档库 + 邮件库统计 |

### 代码知识库 API（`code_routes.py`）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/code/scan` | 扫描目录，建立代码索引 |
| POST | `/api/code/search` | 混合搜索（向量+关键词） |
| POST | `/api/code/chat` | RAG 代码问答，支持流式 |
| GET | `/api/code/repos` | 已索引的仓库列表 |
| GET | `/api/code/stats` | 代码索引统计信息 |
| DELETE | `/api/code/repos/{name}` | 删除仓库索引 |
| POST | `/api/code/repos/{name}/refresh` | 全量刷新仓库（幂等） |
| POST | `/api/code/trace` | 调用链追踪（symbol/direction/depth） |

### MCP 端点

| 端点 | 说明 |
|------|------|
| `/mcp/sse` | MCP SSE 传输端点，暴露 code_search / code_chat / code_list_repos / code_file_context / code_trace 五个 tools |

## 前端开发规范

### Tab HTML 修改必须 bump `__TAB_VERSION`

**位置**：`frontend/index.html:220` 附近的 `window.__TAB_VERSION = 'N';`

**触发场景**：任何对 `frontend/tabs/*.html` 文件的修改（新增/删除/重命名 DOM 元素、改 JS、改 CSS 引用）。

**为什么必做**：
- `frontend/js/router.js:71` 用 `?v=__TAB_VERSION` 作为 cache-busting query 拉 tab HTML
- router 在 `_cache[key]` 命中时**不会重新 fetch**（只在新 URL `?v=` 变化时才会重新走 fetch 分支）
- 不 bump 会导致：开发时改了 tab 文件，浏览器看到的还是上次 fetch 的旧 DOM，**修改不生效**（用户报"代码改完没反应"）

**正确做法**：
1. 改完 `tabs/*.html` 后，**同步**把 `frontend/index.html` 的 `__TAB_VERSION` 数字 +1
2. 在 commit message 中说明 bump（如 `fix(xxx): 改 Y 后 bump __TAB_VERSION=6`）
3. 提醒用户浏览器**硬刷新**（Cmd+Shift+R）或 console 跑 `window.reloadCurrentTab()`

**反面教材**：2026-06-10 glossary 功能 commit 后没 bump，柳哥访问 code/dashboard tab 时图例容器加载不出来，调试 5 分钟才发现是 cache 问题。

### 全局资源引入位置

| 类型 | 引入位置 | 顺序要求 |
|------|----------|----------|
| CSS | `frontend/index.html:14-16` 区域（`theme.css` 之后） | 自身 CSS 在被引用的 CSS 之后 |
| JS | `frontend/index.html:212-217` 区域（`router.js` 之后） | 自身 JS 在依赖的 JS 之后 |
| 共享 JS 函数 | 优先在 `frontend/js/shared.js`；不污染则放模块自带的 `js/` | — |

修改全局 JS 暴露的 `window.*` API 时，记得同步检查 4 个面板 + shared.js 的使用点。
