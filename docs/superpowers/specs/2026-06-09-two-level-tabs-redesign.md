# 两级 Tab 重构设计文档

日期：2026-06-09
状态：已确认

## 目标

将当前 6 个平级 tab 的单文件前端重构为两级 tab 结构，分为「文档知识管理」和「代码知识库管理」两大模块。同步升级深色主题，拆分前端为多文件 SPA。

## 当前状态

- 单文件 `frontend/index.html`（2579 行）
- 6 个平级 tab：文档管理、邮件导入、智能问答、看板、LanceDB 内部、代码知识库
- 浅色主题（白底灰字），Tailwind CDN
- 后端：`main.py`（文档 API）+ `code_routes.py`（代码 API），已分离

## 设计决策

### 1. 导航结构：左侧 Sidebar

选择 Sidebar 方案（方案 B），理由：
- 信息层级最清晰，所有功能一目了然
- 扩展性最强（加功能只需 sidebar 加一行）
- 适合开发者工具的信息密度

结构：

```
┌─────────────────────────────────────────────┐
│ 📚 Email Wiki                    v2.0       │
├──────────┬──────────────────────────────────┤
│          │                                  │
│ 文档知识管理                    内容区       │
│  ├ 文档管理                                  │
│  ├ 邮件导入                                  │
│  ├ 智能问答                                  │
│  ├ 看板                                      │
│  └ LanceDB 内部                              │
│ ──────────────────                           │
│ 代码知识库                                   │
│  ├ 仓库扫描                                  │
│  ├ 代码搜索                                  │
│  ├ 代码问答                                  │
│  ├ 看板                                      │
│  └ LanceDB 内部                              │
│          │                                  │
└──────────┴──────────────────────────────────┘
```

### 2. 文件结构：SPA 多文件

```
frontend/
  index.html              ← 导航壳 + 公共样式 + 路由
  css/
    theme.css             ← 深色主题设计令牌
  js/
    router.js             ← Sidebar 切换 + 页面 fetch 加载
    shared.js             ← 公共工具函数
  tabs/
    doc-upload.html        ← 文档管理
    doc-email.html         ← 邮件导入
    doc-chat.html          ← 文档智能问答
    doc-dashboard.html     ← 文档看板
    doc-lancedb.html       ← 文档 LanceDB 内部
    code-repos.html        ← 仓库扫描+管理
    code-search.html       ← 代码搜索
    code-chat.html         ← 代码问答
    code-dashboard.html    ← 代码看板
    code-lancedb.html      ← 代码 LanceDB 内部
```

路由：URL hash 实现（`#doc/upload`, `#code/repos`），支持收藏和刷新。

### 3. 设计系统：深色 Slate 主题

基于 ui-ux-pro-max 推荐的 Data-Dense Dashboard 风格：

| 令牌 | 色值 | 用途 |
|------|------|------|
| `--color-primary` | `#1E293B` | 卡片/面板背景 |
| `--color-background` | `#0F172A` | 页面背景 |
| `--color-foreground` | `#F8FAFC` | 主文本 |
| `--color-accent` | `#22C55E` | 强调色/CTA |
| `--color-muted` | `#64748B` | 次要文本 |
| `--color-border` | `#334155` | 边框/分隔线 |
| `--color-destructive` | `#EF4444` | 危险操作 |

字体：Fira Sans（正文） + Fira Code（代码/数据）
效果：hover tooltips、row highlighting、smooth filter animations（150-300ms）

### 4. 看板设计

**文档知识管理看板**（现有，保留）：
- 概览卡片：文档数、邮件数、线程数、向量块数
- 性能指标：LanceDB 磁盘、搜索耗时、文件插入、chunk 插入
- 图表：耗时趋势（按天）、Step 耗时拆解
- 数据存储目录

**代码知识库看板**（新增）：
- 概览卡片：仓库数、代码块数、语言数、Chunk 类型数
- 语言分布标签云（代码特有）
- 仓库明细表（代码特有）
- Chunk 类型分布（代码特有）
- 性能指标：Code LanceDB 磁盘、代码搜索耗时、仓库扫描耗时、代码问答耗时
- 图表：耗时趋势（搜索/问答/扫描/追踪）、Step 耗时拆解
- 数据存储目录：code_lancedb/、code_index.db、code_repos.json、code_skip_rules.json

### 5. LanceDB 内部 Tab

两个独立的 LanceDB 内部 tab，各自指向不同数据库：

| | 文档 LanceDB | 代码 LanceDB |
|---|---|---|
| 数据库路径 | `data/lancedb/` | `data/code_lancedb/` |
| API 端点 | `/api/lancedb/inspect`（现有） | `/api/code/lancedb/inspect`（新建） |
| Embedding 模型 | `BAAI/bge-base-zh-v1.5` (768d) | `BAAI/bge-small-en-v1.5` (384d) |
| 表字段 | id, filename, chunk_index, content, vector, file_type, uploaded_at, metadata | id, repo_name, file_path, language, chunk_type, symbol_name, content, vector, ... |
| 原理演示 | 存入（段落分块+embedding）、搜索（向量+余弦+阈值） | 存入（tree-sitter AST+embedding）、搜索（查询翻译+三路搜索+RRF） |

**硬约束**：原理演示必须从实际模块读取模型信息和参数，禁止硬编码。

### 6. 后端改造

改动范围小，三处：

1. **`lancedb_inspect.py` 参数化**
   - 给 `inspect_overview()`, `list_rows()`, `demo_insert()`, `demo_search()` 加 `db_type` 参数
   - `db_type="doc"` → 连 `data/lancedb/`，用 `embedder.py`
   - `db_type="code"` → 连 `data/code_lancedb/`，用 `code_embedder.py`

2. **`code_routes.py` 新增端点**
   - `GET /api/code/lancedb/inspect` → 代码 LanceDB 表概览
   - `GET /api/code/lancedb/rows` → 代码 LanceDB 数据浏览
   - `POST /api/code/lancedb/demo/insert` → 代码存入演示（tree-sitter AST 分块流程）
   - `POST /api/code/lancedb/demo/search` → 代码搜索演示（查询翻译+三路搜索+RRF）

3. **`/api/stats` 支持按 db_type 分别查询**
   - 新增 `GET /api/stats?db_type=doc` 和 `GET /api/stats?db_type=code`
   - 向后兼容：不传参数返回全部（现有行为）

### 7. 迁移顺序

```
Phase 1: 导航壳 + 路由 + 深色主题基础设施
Phase 2: 逐个迁移文档知识管理的 5 个 tab
Phase 3: 逐个迁移代码知识库的 5 个 tab
Phase 4: 后端改造（inspect 参数化 + code demo 端点 + stats 拆分）
Phase 5: 深色主题细节打磨 + 响应式 + 交互动效
```

每个 Phase 结束 git commit。

## 约束

- 保持 FastAPI 直接 serve 静态文件的方式，不引入构建工具
- 保持 Tailwind CDN，不引入 npm/webpack
- 每个 tab 文件独立可读，HTML 片段由 router.js fetch 注入
- 原理演示数据必须来自真实模型和数据，禁止造假
- Embedding 模型信息从 `embedder.py` 和 `code_embedder.py` 动态读取
