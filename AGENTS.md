# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## 项目概述

基于 LanceDB + sentence-transformers 的本地文档知识库 Demo，支持文档上传、邮件导入、代码索引、向量搜索和 RAG 问答。支持 MCP 协议对外暴露 AI 工具能力。这是一个 email-wiki 技术验证项目，演示 Karpathy LLM-wiki 方案在邮件/代码场景的核心链路。

### 项目文档

| 文档 | 说明 |
|------|------|
| `技术设计文档.md` | 代码向量搜索能力评估 — 覆盖搜索架构、混搜策略、调用链追踪、翻译层设计、能力边界与已知限制。新增代码搜索功能或修改搜索策略前**必读**。 |

## 启动与运行

```bash
# 一键启动（自动创建 venv 并安装依赖）
./start.sh

# 一键停止
./stop.sh

# 手动启动
cd backend
source venv/bin/activate
python3 -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
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

> **注意**：`llm_client.py` 优先读取环境变量，`LLM_PROVIDER` 未设置时默认走 xiaomi（小米 MiMo）。API Key 配置在 `backend/.env` 中。

## 架构要点

### 数据流

```
文档上传 → parser.py（分块）→ embedder.py（768维向量）→ db.py（LanceDB）
邮件导入 → email_db.py（SQLite）→ email_parser.py（转换分块）→ embedder.py → db.py
代码扫描 → code_parser.py（tree-sitter AST 分块 + 调用关系提取）→ code_embedder.py → code_db.py（LanceDB + SQLite FTS5 + code_relations）
用户查询 → embedder.py（查询向量化）→ db.py/code_db.py（向量搜索）→ llm_client.py（RAG）
调用链追踪 → code_search.py（混搜定位符号）→ code_db.py（trace_chain BFS 多跳追踪）
MCP 调用 → code_mcp_v2.py（MCP tools, Streamable HTTP）→ code_search.py / llm_client.py
继承链追踪 → code_mcp_v2.py(direction=hierarchy) → code_db.py(trace_hierarchy BFS)
```

### 关键设计决策

- **Embedding 模型**：文档用 `BAAI/bge-base-zh-v1.5`（768维），代码用 `BAAI/bge-small-en-v1.5`（384维），启动时单例预加载，模型存储在项目 `models/` 目录
- **LanceDB 元数据**：metadata 字段以 JSON 字符串存储（非原生 JSON），读写时需手动 `json.dumps/loads`
- **相似度计算**：LanceDB 使用余弦距离（cosine），通过 `(1 - distance + 1) / 2` 转换为 `[0,1]` 相似度分数，低于 0.3 的结果被过滤
- **搜索能力边界**：`/api/search` 和 `/api/chat` 走向量搜索（LanceDB）；`/api/emails/search` 走 SQL `LIKE`（仅搜 SQLite 原始邮件，不走向量）
- **步骤追踪**：`StepTracker` 贯穿搜索/问答/导入全链路，每步耗时透传前端展示
- **前端**：Hash SPA 路由 + 懒加载 tab HTML 片段（10 个独立 tab），Tailwind 本地运行时（vendor/js/tailwindcss.js）+ 暗色主题 CSS 变量，无构建步骤，FastAPI 直接 serve

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
| `data/code_skip_rules.json` | 代码扫描跳过规则配置 |
| `data/code_agent_config.json` | Agent 配置（bot_name/system_prompt） |
| `data/metrics.db` | 性能指标数据库（step 级耗时记录 + 基线快照） |
| `data/translation_cache.json` | 翻译缓存（中文→英文代码关键词） |
| `data/logs/` | 应用日志目录（app.log，TimedRotatingFileHandler） |
| `uploads/` | 用户上传的原始文件 |

### 各模块职责

**核心模块：**
- `main.py`：FastAPI 路由入口，协调各模块
- `parser.py`：PDF/TXT/MD/DOCX 解析 → 按段落分块（≤500字符）
- `embedder.py`：sentence-transformers 单例封装，`embed_text` / `embed_batch`
- `db.py`：LanceDB CRUD，`id` 字段格式为 `{filename}_{chunk_index}`
- `email_db.py`：SQLite 邮件库操作 + 自动生成 50 封示例邮件
- `email_parser.py`：邮件 dict → LanceDB 兼容的 chunk 列表（file_type=`.eml`）
- `llm_client.py`：OpenAI 兼容客户端，支持流式/非流式，`build_rag_prompt` 构造提示词
- `step_tracker.py`：轻量执行步骤记录器（`Step` dataclass）

**代码知识库模块：**
- `code_parser.py`：tree-sitter AST 解析 + 混合分块 + 调用关系提取
- `code_embedder.py`：代码专用 Embedding 模型封装（BAAI/bge-small-en-v1.5）
- `code_db.py`：LanceDB + SQLite FTS5 双存储 + 调用关系表 `code_relations`
- `code_search.py`：混合搜索 + RRF 融合排序 + `trace_code` 调用链追踪
- `code_routes.py`：代码知识库 REST API 路由
- `code_mcp_v2.py`：MCP server + tools（Streamable HTTP, mcp SDK v1.12.4）
- `code_config.py`：扫描配置管理（code_repos.json）
- `code_skip_rules.py`：可配置排除规则（skip_dirs/skip_exts）

**工具模块：**
- `text_utils.py`：中文文本处理（jieba 分词 + FTS5 查询适配）
- `query_translator.py`：中文查询 → 英文代码关键词翻译（本地词典 > 缓存 > API > LLM）
- `translation_cache.py`：翻译缓存层，持久化缓存翻译结果
- `match_reasons.py`：搜索结果归因，解释每条结果为什么被匹配上

### 代码搜索准确率策略（⚠️ 2026-06-10 实验结论）

**四路混搜架构**：`code_search.py` 的 `search_code(hybrid)` 走四路召回 + RRF 扁平融合排序。

**中文 query → 英文代码的核心策略**：翻译层是唯一正确桥梁，不是跨语言 embedding。

| 路径 | 模型/方法 | 输入 | 角色 | 权重 | 实际效果 |
|------|-----------|------|------|------|------|
| A 向量 | `bge-small-en` (384维) 每词分别embed | 翻译后的英文关键词 | 语义模糊召回 | 1.0 | 同语言英文→英文代码，配合翻译层使用 |
| B 英文FTS5 | SQLite FTS5 + jieba 分词 | 翻译后的英文关键词 | 精确匹配代码标识符 | 1.0 | 英文关键词直接命中 |
| C 中文FTS5 | SQLite FTS5 + jieba 分词 | 中文原 query | 中文 content 搜索 | 0.3 | 弱信号，搜注释/文档 |
| D 符号名LIKE | `symbol_name LIKE '%kw%'` | 翻译后的英文关键词 / 英文query驼峰拆词 | 精确命中 | 1.5 | **最可靠的路**，兜底FTS5驼峰拆分盲区 |

**翻译层降级链**：`query_translator.py` 词典（贪心最长匹配 → jieba分词逐词匹配）→ 缓存 → MyMemory API → LLM → 原 query 回退

**关键设计决策（实验验证）**：

| 决策 | 结论 | 证据 |
|------|------|------|
| 跨语言 embedding（e5/bge-m3）代替翻译层 | ❌ 不行 | 实测 e5：中文 query → 纯英文 OC 代码召回接近随机，跨语言桥训练于平行语料非代码 |
| 词典是第一道防线 | ✅ 必须 | `"读信"→read/mail/message` 符号路直接命中 `ReadCell.m`；缺词典降级到 MyMemory 则译成 `letter/reading` 翻车 |
| embedding 前剥离注释/中文字面量 | ✅ 有益 | 代码中嵌入的中文（注释、NSString）会误导 bge 模型，剥离后向量路不再偏到中文噪声 |
| MyMemory 翻译不写入缓存/词典 | ✅ 已修复 | MyMemory 直译（"读信"→letter）置信度低且脱离代码命名习惯，写缓存会永久污染 |
| 向量阈值 0.0→0.5 | ✅ 已修复 | score = (1+余弦相似度)/2，0.5=正交分界，砍掉「最近邻但无关」的噪声 |
| 文档侧保持 `bge-base-zh-v1.5` | ✅ 不动 | 同语言中文→中文，换多语言模型会降低中文单项质量 |

**词典维护**：`TERM_MAP` 在 `query_translator.py:45`，按业务场景分组。新增中文词条时加英文词根（类名/方法名词根优先，如 `read` 而非 `reading`）。翻译时先用贪心最长匹配（解决 jieba 拆碎词典词的问题，如"我的"被拆成"我"+"的"），再降级到 jieba 分词逐词匹配。

**运维模块：**
- `logging_setup.py`：日志系统 SSOT（唯一初始化入口，幂等）
- `log_routes.py`：日志对外 API（tail 拉最近 N 行 + export zip 下载）
- `metrics_db.py`：性能指标数据库（SQLite 存储 step 级耗时记录与基线快照）
- `lancedb_inspect.py`：LanceDB 内省工具（schema/count/fragments/versions 只读探查）

## API 接口

### 文档与邮件

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/upload` | 上传文档（PDF/TXT/MD/DOCX） |
| POST | `/api/search` | 向量搜索，返回结果 + 执行步骤 |
| POST | `/api/chat` | RAG 问答，支持 `stream: true` |
| POST | `/api/emails/import` | 从 SQLite 邮件库导入到 LanceDB |
| GET | `/api/documents` | 文档列表（按文件名聚合） |
| GET | `/api/documents/{filename}/open` | 用系统默认应用打开文档 |
| GET | `/api/documents/{filename}/show-in-finder` | 在 Finder 中显示文档 |
| GET | `/api/emails` | 邮件列表 |
| GET | `/api/emails/search` | 关键词搜索邮件 |
| DELETE | `/api/documents/{filename}` | 删除文档及其所有 chunks |
| GET | `/api/stats` | 文档库 + 邮件库统计 |

### 性能监控

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/performance/trend` | 性能趋势数据 |
| GET | `/api/performance/breakdown` | 性能分析 breakdown |
| GET | `/api/performance/baselines` | 性能基线快照 |

### LanceDB 检查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/lancedb/inspect` | 文档 LanceDB schema/统计 |
| GET | `/api/lancedb/rows` | 文档 LanceDB 行数据 |
| POST | `/api/lancedb/demo/insert` | 演示插入数据 |
| POST | `/api/lancedb/demo/search` | 演示搜索数据 |

### 日志系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/logs/tail` | 拉最近 N 行日志 |
| GET | `/api/logs/export` | zip 下载日志文件 |

### 用户

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/user/home` | 用户 home 目录路径 |

### 代码知识库 API（`code_routes.py`）

**扫描与搜索：**

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/code/scan` | 扫描目录，建立代码索引 |
| GET | `/api/code/scan/{scan_id}/sse` | 扫描进度 SSE 流 |
| POST | `/api/code/scan/{scan_id}/cancel` | 取消扫描 |
| POST | `/api/code/search` | 混合搜索（向量+关键词） |
| POST | `/api/code/chat` | RAG 代码问答，支持流式 |
| POST | `/api/code/trace` | 调用链追踪（symbol/direction/depth） |
| GET | `/api/code/browse` | 浏览代码文件 |

**仓库管理：**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/code/repos` | 已索引的仓库列表 |
| GET | `/api/code/languages` | 解析器支持的语言列表 |
| DELETE | `/api/code/repos` | 删除所有仓库索引 |
| DELETE | `/api/code/repos/{name}` | 删除指定仓库索引 |
| POST | `/api/code/repos/{name}/refresh` | 全量刷新仓库（幂等） |

**扫描配置：**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/code/skip-rules` | 获取跳过规则 |
| PUT | `/api/code/skip-rules` | 更新跳过规则 |
| POST | `/api/code/skip-rules/reset` | 重置为默认规则 |
| POST | `/api/code/skip-rules/preview` | 预览规则效果 |
| POST | `/api/code/skip-rules/open-finder` | 在 Finder 中打开规则文件 |
| GET | `/api/code/gitignore-dirs` | 获取 gitignore 中的目录列表 |

**Agent 配置：**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/code/agent-config` | 获取 agent 配置（bot_name/system_prompt） |
| PUT | `/api/code/agent-config` | 更新 agent 配置 |
| POST | `/api/code/agent-config/reset` | 重置为默认配置 |

**LanceDB 检查：**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/code/stats` | 代码索引统计信息 |
| GET | `/api/code/dashboard` | 代码仪表盘数据 |
| GET | `/api/code/lancedb/inspect` | 代码 LanceDB schema/统计 |
| GET | `/api/code/lancedb/rows` | 代码 LanceDB 行数据 |
| POST | `/api/code/lancedb/demo/insert` | 演示插入代码数据 |
| POST | `/api/code/lancedb/demo/search` | 演示搜索代码数据 |
| POST | `/api/code/fts/migrate-chinese` | 中文分词迁移 |

**工具：**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/code/resolve-path` | 解析路径（相对→绝对） |
| POST | `/api/code/open-in-finder` | 在 Finder 中打开路径 |

### MCP 端点

| 端点 | 说明 |
|------|------|
| `/mcp/` | MCP Streamable HTTP 端点，暴露 code_search / code_chat / code_list_repos / code_file_context / code_trace 五个 tools（v2.0 起替换 `/mcp/sse` 旧端点） |

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

## 项目文件说明

### TODO.md — 待解决问题追踪

**作用**：记录项目中已知但尚未修复的问题（性能瓶颈、UI 卡顿、待优化项等），按类别分组，每条包含现象、实测数据、可疑根因、优化方案和优先级。

**何时更新**：
- 发现新的性能问题或体验 bug 但当前不修时，追加到对应分类
- 问题修复后，从 TODO.md 中删除对应条目（可移入 CHANGELOG.md 记录）

**何时读取**：
- 开始新功能开发前，检查是否有相关待办需要顺手解决
- 做性能优化专项时，作为问题清单

### REGRESSION_TEST.md — 回归测试文档

**作用**：记录项目的回归测试用例，覆盖服务启动、API 巡检、代码搜索、前端功能等测试点，每个测试点包含测试方法和预期结果。

**何时更新**：
- 新增 API 端点后，补充对应的测试用例
- 发现新的测试场景或边界条件时

**何时读取**：
- 重大改动前，确认测试覆盖范围
- 提交 PR 前，跑一遍回归测试确认无破坏性变更
