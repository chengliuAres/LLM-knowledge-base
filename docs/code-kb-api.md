# Code Knowledge Base API 参考

> 基础路径: `http://server:8000`

---

## POST /api/code/scan

增量扫描目录, 建立代码索引 (基于 mtime 跳过未变化文件)。

**请求:**
```json
{
    "repo_name": "ghmail",
    "repo_path": "/Users/admin/MailProject/ghmail",
    "project_type": "",
    "languages": [],
    "skip_dirs": [],
    "skip_extensions": []
}
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| repo_name | str | ✅ | - | 仓库名称 (唯一标识) |
| repo_path | str | ✅ | - | 本地目录绝对路径 |
| project_type | str | ❌ | "" | **自动检测** — 空字符串根据目录标志文件自动判断 (Podfile→ios, build.gradle→android, pubspec.yaml→flutter 等)。也可手动指定: ios/macos/android/flutter/rn/kmp/generic |
| languages | str[] | ❌ | [] | 空数组=自动扫描所有支持的语言 (13种: objc/swift/java/kotlin/dart/cpp/python/ruby/javascript/typescript/go/rust/shell) |
| skip_dirs | str[] | ❌ | [] | 额外跳过的目录 (已内置通用跳过规则) |
| skip_extensions | str[] | ❌ | [] | 额外跳过的文件扩展名 |

**响应:**
```json
{
    "status": "ok",
    "repo_name": "ghmail",
    "total_files": 820,
    "total_chunks": 3400,
    "by_language": {"objc": 2800, "swift": 600},
    "by_chunk_type": {"interface": 900, "implementation": 1200, "class": 300, "function": 500, "file": 500},
    "elapsed_seconds": 12.5,
    "incremental": {
        "added": 120,
        "updated": 5,
        "deleted": 2,
        "skipped": 693
    },
    "steps": [...]
}
```

**错误:**
- 400: 目录不存在或无权限
- 409: 同仓库正在扫描中
- 422: 参数校验失败 (如 repo_name 为空)

---

## POST /api/code/search

混合搜索代码 (向量 + 关键词)。

**请求:**
```json
{
    "query": "markRead",
    "mode": "hybrid",
    "top_k": 10,
    "filters": {
        "repo_name": "ghmail",
        "language": "objc",
        "chunk_type": null,
        "file_path": null,
        "symbol_name": null
    }
}
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| query | str | ✅ | - | 搜索内容 |
| mode | str | ❌ | hybrid | hybrid/vector/keyword |
| top_k | int | ❌ | 10 | 返回数量 |
| filters.repo_name | str | ❌ | null | 仓库过滤 |
| filters.project_type | str | ❌ | null | 项目类型过滤 |
| filters.language | str | ❌ | null | 语言过滤 |
| filters.chunk_type | str | ❌ | null | 代码块类型过滤 |
| filters.file_path | str | ❌ | null | 路径前缀匹配 |
| filters.symbol_name | str | ❌ | null | 符号名精确匹配 |

**响应:**
```json
{
    "query": "markRead",
    "mode": "hybrid",
    "results": [
        {
            "id": "ghmail_GHList/GHMailListCellModel.m_markRead_0",
            "repo_name": "ghmail",
            "project_type": "ios",
            "file_path": "GHList/GHMailListCellModel.m",
            "language": "objc",
            "chunk_type": "implementation",
            "symbol_name": "markRead",
            "content": "- (void)markRead:(BOOL)readed {\n    ...",
            "line_start": 125,
            "line_end": 138,
            "score": 0.87,
            "match_reason": "关键词匹配: markRead",
            "parent_symbol_id": "ghmail_GHList/GHMailListCellModel.m_GHMailListCellModel__0",
            "metadata": {...}
        }
    ],
    "steps": [...]
}
```

---

## POST /api/code/chat

RAG 代码问答 (需配置 LLM)。

**请求:**
```json
{
    "question": "邮件列表的 markRead 方法是怎么实现的？",
    "top_k": 5,
    "filters": {"repo_name": "ghmail"},
    "stream": false
}
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| question | str | ✅ | - | 问题 |
| top_k | int | ❌ | 5 | 检索数量 |
| filters | object | ❌ | {} | 同 search 的 filters |
| stream | bool | ❌ | false | 是否流式输出 |

**响应 (非流式):**
```json
{
    "question": "...",
    "answer": "markRead 方法在 GHMailListCellModel.m 中实现...",
    "sources": [...],
    "steps": [...]
}
```

**响应 (流式 SSE):**
```
data: {"type": "steps", "data": [...]}
data: {"type": "content", "data": "markRead"}
data: {"type": "content", "data": " 方法..."}
data: {"type": "sources", "data": [...]}
data: [DONE]
```

**错误:**
- 503: LLM 未配置

---

## GET /api/code/repos

获取已索引的仓库列表。

**响应:**
```json
{
    "repos": [
        {
            "name": "ghmail",
            "project_type": "ios",
            "repo_path": "/Users/admin/MailProject/ghmail",
            "total_files": 820,
            "total_chunks": 3400,
            "languages": ["objc", "swift"],
            "last_scanned": "2026-06-05T10:30:00"
        }
    ]
}
```

---

## GET /api/code/stats

获取索引统计信息。

**响应:**
```json
{
    "total_repos": 3,
    "total_chunks": 12000,
    "by_repo": {"ghmail": 3400, "macmail": 5600, "MailAndroidG": 3000},
    "by_language": {"objc": 4000, "swift": 3000, "java": 2500, "kotlin": 1500, "dart": 1000},
    "by_project_type": {"ios": 3400, "macos": 5600, "android": 3000}
}
```

---

## DELETE /api/code/repos/{name}

删除指定仓库的索引数据。

**路径参数:**
- `name`: 仓库名称

**响应:**
```json
{
    "status": "ok",
    "deleted_chunks": 3400,
    "repo_name": "ghmail"
}
```

**错误:**
- 404: 仓库不存在

---

## POST /api/code/repos/{name}/refresh

全量刷新仓库索引 (幂等, 先清空旧数据再重新扫描)。

**路径参数:**
- `name`: 仓库名称

**响应:** 同 `/api/code/scan`

**错误:**
- 404: 仓库不存在

---

## POST /api/code/trace

追踪符号的调用链 — 快速理清跨文件业务逻辑。先混搜定位符号入口，再通过 `code_relations` 表做 BFS 多跳追踪。

**请求:**
```json
{
    "symbol": "processPayment",
    "repo_name": "ghmail",
    "direction": "both",
    "depth": 2
}
```

**参数:**
| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| symbol | string | ✅ | - | 符号名或搜索查询 |
| repo_name | string | ❌ | "" | 仓库名过滤 |
| direction | string | ❌ | "both" | callers(谁调我) / callees(我调谁) / both |
| depth | int | ❌ | 2 | 追踪跳数 1-3 |

**响应:**
```json
{
    "query": "processPayment",
    "depth": 2,
    "direction": "both",
    "matched_symbols": [
        {"symbol": "PaymentService", "file_path": "PaymentService.m", "line_start": 8, "chunk_type": "implementation"}
    ],
    "traces": [
        {
            "entry_symbol": "PaymentService",
            "entry_file": "PaymentService.m",
            "direct_callers": [{"symbol": "OrderVC", "file": "OrderVC.m", "line": 45}],
            "direct_callees": [
                {"symbol": "validateOrder:", "line": 11},
                {"symbol": "sendRequest:completion:", "line": 12}
            ],
            "chain": {
                "nodes": [{"symbol": "...", "file": "...", "chunk_id": "..."}],
                "edges": [{"from": "PaymentService", "to": "validateOrder:", "line": 11, "relation": "calls"}]
            }
        }
    ],
    "steps": [...]
}
```

**状态码:**
- 200: 成功
- 400: symbol 为空

---

## POST /api/code/fts/migrate-chinese

对已有 FTS5 索引进行中文分词迁移 (jieba 分词重建)。

新索引写入时已自动分词，此端点用于迁移历史数据。

**请求:**
```json
{
    "repo_name": "ghmail"
}
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| repo_name | str | ❌ | "" | 仓库名 (空字符串=迁移所有仓库) |

**响应:**
```json
{
    "status": "ok",
    "total": 1000,
    "updated": 45
}
```

---

## MCP Tools

### code_search

搜索代码库, 支持语义搜索和关键词搜索。

**输入:**
```json
{
    "query": "邮件列表刷新逻辑",
    "repo": "ghmail",
    "language": "objc",
    "symbol": null,
    "mode": "hybrid",
    "top_k": 10
}
```

### code_chat

基于代码知识库的 RAG 问答。

**输入:**
```json
{
    "question": "markRead 方法是怎么实现的？",
    "repo": "ghmail",
    "language": "objc"
}
```

### code_list_repos

列出已索引的代码仓库。无输入参数。

### code_file_context

获取某个文件的上下文 (可指定行号范围)。

**输入:**
```json
{
    "repo": "ghmail",
    "file_path": "GHList/GHMailListCellModel.m",
    "line_start": 100,   // 可选, 起始行
    "line_end": 150      // 可选, 结束行
}
```

**输出:**
- 无行号参数: 文件完整内容 + 元数据 (最大 5000 字符, 超出截断)
- 有行号参数: 指定范围 + 前后各 10 行上下文 + 元数据

### code_trace

追踪符号的调用链 — 谁调用了它 / 它调用了谁 / **类继承层级**（v2.0 新增 hierarchy）。用于快速理清跨文件业务逻辑链路。

**输入:**
```json
{
    "symbol": "processPayment",    // 符号名或搜索查询
    "repo": "ghmail",              // 可选, 仓库名过滤
    "direction": "both",           // callers / callees / both / hierarchy (v2.0 新增)
    "depth": 2                     // 追踪跳数 1-3（hierarchy 1-5；默认 2）
}
```

**direction=hierarchy 输出（v2.0 新增）:**
```json
{
  "symbol": "AccountMocker",
  "direction": "hierarchy",
  "matched_symbols": [{"symbol": "AccountMocker", "file_path": "...", "chunk_type": "class_or_protocol"}],
  "traces": [{
    "chain": {"nodes": [...], "edges": [...]},  // BFS 完整图
    "parents": [{"symbol": "BaseMockHandler", "via": "AccountMocker", "line": 1}],
    "children": [{"symbol": "MailTagGroupMocker", "via": "BaseMockHandler", "line": 1}]
  }]
}
```

**relation_type 说明**：调用图和继承图共用 `code_relations` 表，通过 `relation_type` 字段区分（`'call'` / `'inherit'`）。6 种语言 + Java/TypeScript implements 全部覆盖（`code_parser._extract_inherits`）。

**典型使用场景 (Agent 多跳推理):**
```
Agent: code_trace("PaymentService", direction="callees", depth=2)

**输出:**
```json
{
    "symbol": "processPayment",
    "direction": "both",
    "depth": 2,
    "direct_callers": [{"symbol": "OrderVC", "file": "OrderVC.m", "line": 45}],
    "direct_callees": [
        {"symbol": "validateOrder:", "line": 11},
        {"symbol": "sendRequest:completion:", "line": 12}
    ],
    "chain": {
        "nodes": [{"symbol": "...", "file": "...", "chunk_id": "..."}],
        "edges": [{"from": "PaymentService", "to": "validateOrder:", "line": 11, "relation": "calls"}]
    }
}
```

**典型使用场景 (Agent 多跳推理):**
```
Agent: code_trace("PaymentService", direction="callees", depth=2)
  → PaymentService → validateOrder: → refundOrder: → reverseOrder:
  → PaymentService → sendRequest:completion: → handleResponse:
Agent 输出: "支付流程从 PaymentService 进入，先校验订单 (validateOrder:)，
           如需退款走 refundOrder: → reverseOrder:，
           正常支付走 sendRequest:completion: → handleResponse: 回调处理结果。"
```
