# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
代码扫描 → code_parser.py（tree-sitter AST 分块）→ embedder.py → code_db.py（LanceDB + SQLite FTS）
用户查询 → embedder.py（查询向量化）→ db.py/code_db.py（向量搜索）→ llm_client.py（RAG）
MCP 调用 → code_mcp.py（MCP tools）→ code_search.py / llm_client.py
```

### 关键设计决策

- **Embedding 模型**：本地 `paraphrase-multilingual-MiniLM-L12-v2`（384维，多语言），启动时单例预加载，首次启动会下载模型（~90MB）
- **LanceDB 元数据**：metadata 字段以 JSON 字符串存储（非原生 JSON），读写时需手动 `json.dumps/loads`
- **相似度计算**：LanceDB 使用余弦距离（cosine），通过 `(1 - distance + 1) / 2` 转换为 `[0,1]` 相似度分数，低于 0.3 的结果被过滤
- **搜索能力边界**：`/api/search` 和 `/api/chat` 走向量搜索（LanceDB）；`/api/emails/search` 走 SQL `LIKE`（仅搜 SQLite 原始邮件，不走向量）
- **步骤追踪**：`StepTracker` 贯穿搜索/问答/导入全链路，每步耗时透传前端展示
- **前端**：单文件 `frontend/index.html`（Tailwind CDN），无构建步骤，FastAPI 直接 serve

### LanceDB 表结构（`documents` 表）

```
id            : str   — "{filename}_{chunk_index}"，主键
filename      : str   — 文件名（邮件为 "email_{id}.eml"）
chunk_index   : int   — 当前文件第 N 个分块
content       : str   — 文本内容
vector        : [float; 384]
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
| `data/code_index.db` | 代码 SQLite FTS5 全文索引 |
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
- `code_parser.py`：tree-sitter AST 解析 + 混合分块（代码知识库）
- `code_db.py`：LanceDB + SQLite FTS5 双存储（代码知识库）
- `code_search.py`：混合搜索 + RRF 融合排序（代码知识库）
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

### MCP 端点

| 端点 | 说明 |
|------|------|
| `/mcp/sse` | MCP SSE 传输端点，暴露 code_search/code_chat/code_list_repos/code_file_context 四个 tools |
