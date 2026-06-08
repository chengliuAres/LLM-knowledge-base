# Code Knowledge Base 开发进度

> 分支: `code_knowledge_base`
> 创建: 2026-06-05

## 里程碑

| # | 里程碑 | 状态 | 说明 |
|---|--------|------|------|
| M1 | 代码解析器 | ✅ 已完成 | tree-sitter AST 解析 + 混合分块 + 增量扫描 + 13种语言支持 + 自动工程类型检测 |
| M2 | 存储层 | ✅ 已完成 | LanceDB + SQLite FTS 双写 + FTS5 中文分词 |
| M3 | 搜索层 | ✅ 已完成 | 混合搜索 + RRF 融合排序 + 中文查询关键词加权 + 相似度阈值 |
| M4 | REST API | ✅ 已完成 | 8 个接口 (含 FTS5 中文迁移) + step_tracker |
| M5 | MCP Server | ✅ 已完成 | 4 个 tools + SSE 传输 |
| M6 | 前端 | ✅ 已完成 | 代码知识库 tab |
| M7 | 集成测试 | ✅ 已完成 | 全链路自测验证 + Chrome 实测 |
| M8 | Embedding 模型升级 | ✅ 已完成 | bge-m3 (1024-dim, 8192-token) |

## 详细任务

### M1: 代码解析器

| # | 任务 | 文件 | 状态 | 备注 |
|---|------|------|------|------|
| 1.1 | 安装 tree-sitter-language-pack | requirements.txt | ✅ | v0.9.1 |
| 1.2 | 实现目录扫描器 | code_parser.py | ✅ | 递归遍历 + 跳过规则 |
| 1.3 | 实现 tree-sitter AST 解析 | code_parser.py | ✅ | 支持 objc/swift/java/kotlin/dart/cpp |
| 1.4 | 实现混合分块策略 | code_parser.py | ✅ | 短文件整文件/长文件按函数/超长二次切 |
| 1.5 | 实现 .h/.m 配对逻辑 | code_parser.py | ✅ | paired_file 互相引用 |
| 1.6 | 实现降级策略 | code_parser.py | ✅ | AST 失败降级为整文件 chunk |
| 1.7 | 实现增量扫描逻辑 | code_config.py | ✅ | 基于 mtime 对比, 跳过未变化文件 |

### M2: 存储层

| # | 任务 | 文件 | 状态 | 备注 |
|---|------|------|------|------|
| 2.1 | 实现 LanceDB code_chunks 表 | code_db.py | ✅ | 独立数据库目录, id 含 parent_class |
| 2.2 | 实现 SQLite FTS5 code_fts 表 | code_db.py | ✅ | 全文检索 |
| 2.3 | 实现双写逻辑 | code_db.py | ✅ | insert 同时写两个库 |
| 2.4 | 实现双删逻辑 | code_db.py | ✅ | delete 同时删两个库 |
| 2.5 | 实现仓库配置管理 | code_config.py | ✅ | code_repos.json 读写 |
| 2.6 | 实现扫描并发控制 | code_config.py | ✅ | 同仓库加锁, 409 |

### M3: 搜索层

| # | 任务 | 文件 | 状态 | 备注 |
|---|------|------|------|------|
| 3.1 | 实现向量搜索 | code_search.py | ✅ | LanceDB cosine |
| 3.2 | 实现关键词搜索 | code_search.py | ✅ | SQLite FTS5 MATCH |
| 3.3 | 实现结构化过滤 | code_search.py | ✅ | repo/language/type/path/symbol |
| 3.4 | 实现 RRF 融合排序 | code_search.py | ✅ | k=60, 每路各自 top_k, 融合后取 top_k |
| 3.5 | 实现搜索结果 match_reason | code_search.py | ✅ | 标注匹配原因 |

### M4: REST API

| # | 任务 | 文件 | 状态 | 备注 |
|---|------|------|------|------|
| 4.1 | POST /api/code/scan | code_routes.py | ✅ | 含 step_tracker |
| 4.2 | POST /api/code/search | code_routes.py | ✅ | 含 step_tracker |
| 4.3 | POST /api/code/chat | code_routes.py | ✅ | RAG + 流式 |
| 4.4 | GET /api/code/repos | code_routes.py | ✅ | |
| 4.5 | GET /api/code/stats | code_routes.py | ✅ | |
| 4.6 | DELETE /api/code/repos/{name} | code_routes.py | ✅ | |
| 4.7 | POST /api/code/repos/{name}/refresh | code_routes.py | ✅ | 幂等 |
| 4.8 | 注册路由到 main.py | main.py | ✅ | |

### M5: MCP Server

| # | 任务 | 文件 | 状态 | 备注 |
|---|------|------|------|------|
| 5.1 | 安装 mcp SDK | requirements.txt | ✅ | 手动实现(兼容3.9), 用 sse-starlette |
| 5.2 | 实现 MCP server 框架 | code_mcp.py | ✅ | JSON-RPC 2.0 over SSE |
| 5.3 | 实现 code_search tool | code_mcp.py | ✅ | |
| 5.4 | 实现 code_chat tool | code_mcp.py | ✅ | |
| 5.5 | 实现 code_list_repos tool | code_mcp.py | ✅ | |
| 5.6 | 实现 code_file_context tool | code_mcp.py | ✅ | 支持 line_start/line_end, 5000 字符限制 |
| 5.7 | 实现 token 认证 | code_mcp.py | ⬜ | 暂跳过 (可选功能) |
| 5.8 | 注册 MCP 端点到 main.py | main.py | ✅ | /mcp/sse, /mcp/message |

### M6: 前端

| # | 任务 | 文件 | 状态 | 备注 |
|---|------|------|------|------|
| 6.1 | 新增代码知识库 tab | index.html | ✅ | |
| 6.2 | 左列: 仓库管理 + 过滤器 | index.html | ✅ | |
| 6.3 | 中列: 搜索结果 + 问答 | index.html | ✅ | |
| 6.4 | 右列: 执行流程 | index.html | ✅ | 复用 StepTracker |
| 6.5 | 代码语法高亮 | index.html | ⬜ | 暂用 monospace, 后续可加 highlight.js |
| 6.6 | LLM 未配置状态判断 | index.html | ⬜ | 后续优化 |

### M7: 集成测试

| # | 任务 | 状态 | 备注 |
|---|------|------|------|
| 7.1 | 扫描 iOS 仓库 (ghmail) | ✅ | ObjC+Swift+Cpp, 1000 chunks |
| 7.2 | Chrome 实测搜索验证 | ✅ | "登录" 关键词返回 2 条精准，混合模式 10 条相关 |
| 7.3 | 搜索 + RAG 问答全链路 | ✅ | API 端点全部验证通过 |
| 7.4 | MCP 远程连接测试 | ✅ | SSE 连接正常, endpoint 事件正确 |
| 7.5 | 前端功能验证 | ✅ | 代码知识库 tab 可访问 |

### M8: 搜索优化 + 模型升级 (2026-06-08)

| # | 任务 | 文件 | 状态 | 备注 |
|---|------|------|------|------|
| 8.1 | 新增中文分词工具模块 | text_utils.py | ✅ | jieba 分词 + FTS5 查询适配 |
| 8.2 | FTS5 写入时分词 | code_db.py | ✅ | segment_for_fts() |
| 8.3 | FTS5 搜索时分词查询 | code_db.py | ✅ | segment_query_for_match() |
| 8.4 | FTS5 中文迁移端点 | code_db.py + code_routes.py | ✅ | POST /api/code/fts/migrate-chinese |
| 8.5 | 相似度阈值 + 中文关键词加权 | code_search.py | ✅ | MIN_VECTOR_SIMILARITY=0.3, 1.8x boost |
| 8.6 | 扩展语言支持 (6→13种) | code_parser.py | ✅ | Python/Ruby/JS/TS/Go/Rust/Shell |
| 8.7 | 自动检测工程类型 | code_parser.py | ✅ | auto_detect_project_type() |
| 8.8 | project_type 改为可选 | code_routes.py | ✅ | 空白自动检测 |
| 8.9 | Embedding 模型升级 | embedder.py | ✅ | bge-m3: 1024-dim, 8192-token |
| 8.10 | LanceDB 维度自动迁移 | db.py + code_db.py | ✅ | 维度不匹配自动备份+重建 |
| 8.11 | 查询使用 bge 前缀 | 多处 | ✅ | embed_query() 替代 embed_text() 用于搜索 |

## 变更记录

| 日期 | 内容 |
|------|------|
| 2026-06-05 | 设计完成, 创建进度文档 |
| 2026-06-08 | 设计细化: metadata 语义/RRF 细节/scan 增量/chunk id/MCP 参数/top_k 限流/parent_symbol_id |
| 2026-06-08 | M8: Embedding 模型升级 bge-m3 + FTS5 jieba 中文分词 + 自动工程类型检测 + 语言扩展 6→13 |
