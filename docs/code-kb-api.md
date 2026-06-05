# Code Knowledge Base API 参考

> 基础路径: `http://server:8000`

---

## POST /api/code/scan

扫描目录, 建立代码索引。

**请求:**
```json
{
    "repo_name": "ghmail",
    "repo_path": "/Users/admin/MailProject/ghmail",
    "project_type": "ios",
    "languages": ["objc", "swift"],
    "skip_dirs": [".xcassets", ".xcframework", "lottie", "third"],
    "skip_extensions": [".png", ".json", ".strings"]
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| repo_name | str | ✅ | 仓库名称 (唯一标识) |
| repo_path | str | ✅ | 本地目录绝对路径 |
| project_type | str | ✅ | ios/android/flutter/rn/kmp/macos |
| languages | str[] | ✅ | 语言列表 |
| skip_dirs | str[] | ❌ | 跳过的目录名 (默认见设计文档) |
| skip_extensions | str[] | ❌ | 跳过的文件扩展名 |

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
    "steps": [...]
}
```

**错误:**
- 400: 目录不存在或无权限
- 409: 同仓库正在扫描中

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

获取某个文件的完整上下文。

**输入:**
```json
{
    "repo": "ghmail",
    "file_path": "GHList/GHMailListCellModel.m"
}
```

**输出:** 文件完整内容 + 元数据 (最大 5000 字符, 超出截断)。
