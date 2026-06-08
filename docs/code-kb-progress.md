# Code Knowledge Base 开发进度

> 分支: `code_knowledge_base`
> 创建: 2026-06-05

## 里程碑

| # | 里程碑 | 状态 | 说明 |
|---|--------|------|------|
| M1 | 代码解析器 | ✅ 已完成 | tree-sitter AST 解析 + 混合分块 + 增量扫描 |
| M2 | 存储层 | ✅ 已完成 | LanceDB + SQLite FTS 双写 |
| M3 | 搜索层 | ✅ 已完成 | 混合搜索 + RRF 融合排序 |
| M4 | REST API | ✅ 已完成 | 7 个接口 + step_tracker |
| M5 | MCP Server | ⬜ 待开始 | 4 个 tools + SSE 传输 |
| M6 | 前端 | ⬜ 待开始 | 代码知识库 tab |
| M7 | 集成测试 | ⬜ 待开始 | 全链路自测验证 |

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
| 5.1 | 安装 mcp SDK | requirements.txt | ⬜ | |
| 5.2 | 实现 MCP server 框架 | code_mcp.py | ⬜ | SSE transport |
| 5.3 | 实现 code_search tool | code_mcp.py | ⬜ | |
| 5.4 | 实现 code_chat tool | code_mcp.py | ⬜ | |
| 5.5 | 实现 code_list_repos tool | code_mcp.py | ⬜ | |
| 5.6 | 实现 code_file_context tool | code_mcp.py | ⬜ | 支持 line_start/line_end, 5000 字符限制 |
| 5.7 | 实现 token 认证 | code_mcp.py | ⬜ | MCP_AUTH_TOKEN |
| 5.8 | 注册 MCP 端点到 main.py | main.py | ⬜ | /mcp/sse |

### M6: 前端

| # | 任务 | 文件 | 状态 | 备注 |
|---|------|------|------|------|
| 6.1 | 新增代码知识库 tab | index.html | ⬜ | |
| 6.2 | 左列: 仓库管理 + 过滤器 | index.html | ⬜ | |
| 6.3 | 中列: 搜索结果 + 问答 | index.html | ⬜ | |
| 6.4 | 右列: 执行流程 | index.html | ⬜ | 复用 StepTracker |
| 6.5 | 代码语法高亮 | index.html | ⬜ | highlight.js CDN |
| 6.6 | LLM 未配置状态判断 | index.html | ⬜ | 灰掉问答按钮 |

### M7: 集成测试

| # | 任务 | 状态 | 备注 |
|---|------|------|------|
| 7.1 | 扫描 iOS 仓库 (ghmail) | ⬜ | 验证 ObjC 解析 |
| 7.2 | 扫描 macOS 仓库 (macmail) | ⬜ | 验证 Swift/ObjC++ 解析 |
| 7.3 | 扫描 Android 仓库 | ⬜ | 验证 Java/Kotlin 解析 |
| 7.4 | 搜索 + RAG 问答全链路 | ⬜ | |
| 7.5 | MCP 远程连接测试 | ⬜ | |
| 7.6 | 前端功能验证 | ⬜ | |

## 变更记录

| 日期 | 内容 |
|------|------|
| 2026-06-05 | 设计完成, 创建进度文档 |
| 2026-06-08 | 设计细化: metadata 语义/RRF 细节/scan 增量/chunk id/MCP 参数/top_k 限流/parent_symbol_id |
