# Code Knowledge Base 设计文档

> 分支: `code_knowledge_base`
> 创建: 2026-06-05
> 状态: 设计完成，待实现

## 1. 概述

在现有文档/邮件知识库基础上，新增代码知识库子系统。支持多仓库、多语言的代码语义搜索和 RAG 问答，并通过 MCP 协议对外暴露 AI 工具能力。

### 目标仓库

| 项目 | 路径 | 类型 | 语言 | 文件数 | 代码行 |
|------|------|------|------|--------|--------|
| ghmail | /Users/admin/MailProject/ghmail | iOS (自动检测) | ObjC/Swift/C++/Python/Ruby/Dart/Kotlin | 950 | 112K |
| macmail | /Users/admin/MailProject/macmail | macOS | Swift/ObjC++/C++ | 2,350 | 248K |
| MailAndroidG | /Users/admin/MailProject/MailAndroidG | Android | Java/Kotlin | ~4,000+ | 713K |
| mailflutter | /Users/admin/MailProject/ghmail/mailflutter | Flutter | Dart | 197 | - |
| rnbase-for-native | /Users/admin/MailProject/ghmail/rnbase-for-native | RN | JS/TS | 5 | 极少 |
| mmsharedkmp | /Users/admin/MailProject/ghmail/mmsharedkmp | KMP | Kotlin | 71 | - |

**合计: ~7,500+ 文件, ~1.1M 行代码, 13 种语言, 6 个仓库**

> **工程类型自动检测**：`project_type` 改为可选参数，留空时系统根据目录标志文件自动判断（Podfile→iOS, build.gradle→Android, pubspec.yaml→Flutter 等）。
> 
> **语言支持**：从 6 种扩至 13 种（新增 Python, Ruby, JavaScript, TypeScript, Go, Rust, Shell）。混合工程（如 iOS 含 Python 脚本 + Ruby CocoaPods + Flutter 模块）自动识别所有语言。

### 核心能力

- 指定本地目录路径，自动扫描索引代码
- 混合分块: AST 解析 + 按函数/类/文件智能切分
- 语义搜索 + 关键词搜索 + 结构化过滤
- **FTS5 中文分词**：jieba 分词解决 unicode61 无法切分中文的问题
- RAG 代码问答 (需配置 LLM)
- MCP 协议暴露 AI 工具 (Hermes/Claude 可直接调用)

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (Tab 切换)                    │
│   [文档知识库]  [邮件知识库]  [代码知识库]                  │
└──────┬──────────────┬──────────────┬────────────────────┘
       │              │              │
┌──────▼──────────────▼──────────────▼────────────────────┐
│              FastAPI (main.py)                            │
│  /api/upload  /api/search  /api/chat                     │
│  /api/code/*                              ← 新增路由模块  │
│  /mcp/sse                                ← MCP 端点      │
└──────┬──────────────┬──────────────┬────────────────────┘
       │              │              │
  ┌────▼────┐   ┌────▼────┐   ┌────▼────────┐
  │ LanceDB │   │ LanceDB │   │ LanceDB     │
  │documents│   │emails.db│   │code_chunks  │ (独立)
  └─────────┘   └─────────┘   ├────────────┤
                               │ SQLite FTS │
                               │ code_index │
                               └────────────┘
```

### 设计原则

- 代码知识库作为**独立子系统**, 有自己的 LanceDB 表 + SQLite FTS
- **Embedding 模型**: BAAI/bge-m3（1024 维，8192-token 上下文，中英文+代码混合训练）
- **中文分词**: jieba 分词解决 FTS5 unicode61 无法切分中文的问题（写入时分词，查询时分词+短语匹配）
- 复用现有 step_tracker
- 新增独立路由模块 `code_routes.py`, 不污染现有 main.py
- 前端加一个 tab, 代码知识库有自己的搜索/问答界面

---

## 3. 代码解析与分块

### 3.1 技术选型

使用 **tree-sitter-language-pack** (305 语言, pip install 即用, 预编译 wheel)。

```python
from tree_sitter_language_pack import get_language, get_parser
parser = get_parser('objc')    # Objective-C
parser = get_parser('swift')   # Swift
parser = get_parser('java')    # Java
parser = get_parser('kotlin')  # Kotlin
parser = get_parser('dart')    # Dart
parser = get_parser('cpp')     # C++ / ObjC++ (.mm)
```

### 3.2 新增文件

`backend/code_parser.py`

### 3.3 处理流程

```
输入: 本地目录路径
  │
  ▼
1. 目录扫描
   - 递归遍历, 按扩展名过滤
   - 跳过: .git/ node_modules/ venv/ __pycache__/ build/ dist/ 等
   - 支持的语言→扩展名映射表 (可配置)
  │
  ▼
2. AST 解析 (tree-sitter-language-pack)
   - 根据文件扩展名选择 parser
   - 提取: 函数(function)、类(class)、方法(method)、协议(protocol)、category
   - 每个节点提取: name、签名、docstring、body、行号范围
  │
  ▼
3. 混合分块策略
   ├── 短文件 (<500字符) → 整文件一个 chunk
   ├── 长文件有结构 → 按函数/类拆分
   │   每个 chunk = 签名 + docstring + 实现
   └── 超长函数 (>1000字符) → 按 500 字符二次切分
  │
  ▼
4. 输出 chunk 列表
```

### 3.4 Chunk 结构

```python
{
    "id": "{repo}_{filepath}_{parent_class}_{symbol}_{index}",  // parent_class 无值时用 "_"
    "repo_name": "ghmail",
    "project_type": "ios",
    "file_path": "GHList/GHMailListCellModel.h",
    "file_name": "GHMailListCellModel.h",
    "language": "objc",
    "chunk_type": "interface",
    "symbol_name": "GHMailListCellModel",
    "content": "@interface GHMailListCellModel : NSObject\n...",
    "line_start": 35,
    "line_end": 142,
    "vector": [float; 384],
    "metadata": {
        // === 通用 (所有语言必填) ===
        "parent_class": "NSObject",
        "file_size_bytes": 6522,
        "repo_path": "/Users/admin/MailProject/ghmail",

        // === 按语言选填 (只填当前语言相关字段, 不相关的不写) ===
        // ObjC: protocols, categories, is_header, paired_file
        // Java/Kotlin: package, is_interface, is_abstract, annotations
        // Dart: is_mixin, is_extension, widgets_used
        // 通用: imports_count, imports

        // 示例 (ObjC):
        "protocols": ["GHMailListCellModelDelegate"],
        "categories": [],
        "is_header": true,
        "paired_file": "GHMailListCellModel.m",
        "imports_count": 19,
        "imports": ["Foundation.h", "GHEntity/MailAbstract2.h"]
    }
}
```

### 3.5 chunk_type 类型表

| chunk_type | ObjC | Swift | Java/Kotlin | Dart |
|------------|------|-------|-------------|------|
| `interface` | @interface (.h) | - | interface/abstract class | - |
| `implementation` | @implementation (.m) | - | - | - |
| `class` | - | class | class | class |
| `protocol` | @protocol | protocol | - | - |
| `category` | @interface (Cat) | - | - | - |
| `object` | - | - | object | - |
| `companion` | - | - | companion object | - |
| `function` | 独立函数 | func | 顶层函数 | 顶层函数 |
| `mixin` | - | - | - | mixin |
| `extension` | - | extension | - | extension |
| `file` | 兜底 | 兜底 | 兜底 | 兜底 |

### 3.6 .h/.m 配对策略

- .h 和 .m 分别作为独立 chunk (搜索场景不同: .h 搜 API 签名, .m 搜实现逻辑)
- metadata 里互相引用 `paired_file`, 前端可展示"查看实现/查看声明"跳转

### 3.7 各项目跳过规则

| 项目 | 跳过目录 | 跳过扩展名 |
|------|---------|-----------|
| iOS | .xcassets, .xcframework, .lproj, lottie, third | .png, .json, .strings |
| macOS | Assets.xcassets, Resource, third_party, Pods, .xcodeproj, .xcworkspace | .png, .json, .strings, .storyboard, .xib |
| Android | build, .gradle, buildSrc, keystore, gradleScripts | .xml (layout), .pro |
| Flutter | .ios, .android, build | .png, .json (assets) |
| RN | node_modules, build | - |
| KMP | build, .gradle, ohosApp | .ets |

### 3.8 降级策略

tree-sitter 解析失败时, 降级为整文件 chunk, 记录 warning 到 metadata:
```python
metadata["parse_warning"] = "tree-sitter parse failed, fallback to file chunk"
```

---

### 3.9 增量扫描策略

scan 接口基于文件 `mtime` 实现增量更新:

1. 扫描时遍历目录, 获取每个文件的 `os.path.getmtime()`
2. 与 `code_repos.json` 中记录的上次 mtime 对比:
   - **新增文件** (不在记录中): 全量解析 + 写入
   - **已修改文件** (mtime 变化): 删除旧 chunks + 重新解析写入
   - **未变化文件** (mtime 一致): 跳过
   - **已删除文件** (在记录中但不存在): 删除对应 chunks
3. 扫描完成后更新 `code_repos.json` 中的 mtime 记录

> refresh 接口忽略 mtime, 直接清空该仓库全量重建。

---

## 4. 存储层设计

### 4.1 双存储架构

```
┌──────────────┐       ┌──────────────────┐
│   LanceDB    │       │     SQLite       │
│  向量检索     │       │  关键词+结构化    │
│              │       │                  │
│ code_chunks  │       │ code_fts (FTS5)  │
│  - vector    │       │  - content       │
│  - metadata  │       │  - symbol_name   │
│  - file_path │       │  - file_path     │
│  - language  │       │  - language      │
│  - ...       │       │  - repo_name     │
└──────┬───────┘       └────────┬─────────┘
       │                        │
       └──────┬─────────────────┘
              │
       ┌──────▼───────┐
       │ 搜索合并层    │
       │  - 向量结果   │
       │  - 关键词结果 │
       │  - RRF 排序   │
       └──────────────┘
```

### 4.2 LanceDB 表结构 (code_chunks)

| 字段 | 类型 | 说明 |
|------|------|------|
| id | str | 主键 `{repo}_{file}_{parent_class}_{symbol}_{idx}` (parent_class 无值时用 `_`) |
| repo_name | str | 仓库名 |
| project_type | str | 自动检测（ios/android/flutter/rn/kmp/macos/generic） |
| file_path | str | 相对路径 |
| file_name | str | 文件名 |
| language | str | objc/swift/java/kotlin/dart/cpp/python/ruby/javascript/typescript/go/rust/shell/yaml/json |
| chunk_type | str | interface/class/function/... |
| symbol_name | str | 函数/类名 |
| content | str | 代码文本 |
| line_start | int | 起始行 |
| line_end | int | 结束行 |
| vector | float[1024] | embedding 向量 (BAAI/bge-m3, 1024-dim, 8192-token 上下文) |
| metadata | str | JSON (imports, annotations 等) |

### 4.3 SQLite FTS5 表结构 (code_fts)

```sql
CREATE VIRTUAL TABLE code_fts USING fts5(
    chunk_id,           -- 关联 LanceDB 的 id
    content,            -- 代码原文 (全文检索)
    symbol_name,        -- 符号名 (精确搜索)
    file_path,          -- 文件路径 (路径搜索)
    language,           -- 语言过滤
    repo_name           -- 仓库过滤
);
```

### 4.4 为什么不只用 LanceDB

- 代码搜索场景, 关键词精确匹配比语义搜索更常用 (搜 `GHMailListCellModel` 这种符号名)
- LanceDB 的 where 过滤是精确匹配, 不支持模糊/前缀搜索
- SQLite FTS5 支持前缀搜索 `GHMail*`、短语搜索、布尔组合
- 两者互补: 向量搜语义, FTS 搜精确

### 4.5 数据一致性

- LanceDB 和 SQLite 用同一个 `chunk_id` 关联
- 写入时双写, 删除时双删
- 重建索引时先清空两个库再全量写入

### 4.6 存储路径

```
data/
  code_lancedb/        # LanceDB 向量库 (独立目录)
  code_index.db        # SQLite FTS + 元数据索引
  code_repos.json      # 已索引仓库的配置和状态
```

---

## 5. 搜索层设计

### 5.1 三种搜索模式

```
用户查询: "GHMailListCellModel 的 markRead 方法"
         │
    ┌────┼────────────────┐
    │    │                │
    ▼    ▼                ▼
  向量搜索  关键词搜索    结构化过滤
 (LanceDB)  (SQLite FTS)  (metadata)
    │    │                │
    └────┼────────────────┘
         │
         ▼
    RRF 融合排序
         │
         ▼
    返回 Top-K 结果
```

| 模式 | 用途 | 实现 |
|------|------|------|
| 语义 (vector) | "这个功能是怎么实现的" | query → embedder → LanceDB cosine |
| 关键词 (keyword) | 搜符号名/方法名/路径 | query → SQLite FTS5 MATCH |
| 混合 (hybrid, 默认) | 综合搜索 | 两路并行 + RRF 融合 |

### 5.2 RRF (Reciprocal Rank Fusion)

公式: `score = 1/(k + rank)`, k=60

详细规则:
- **向量搜索 rank**: 按 LanceDB cosine distance 升序排列后的序号 (1-based), distance 越小 rank 越小
- **关键词搜索 rank**: 按 SQLite FTS5 BM25 分数降序排列后的序号 (1-based)
- **top_k 语义**: 每路各自返回 top_k 个结果, 融合后取最终 top_k 个
- **融合逻辑**: 同一 chunk_id 两路都命中则 RRF 分数相加; 仅单路命中的 chunk 保留该路分数
- **最终排序**: 按融合分数降序, 取前 top_k 个返回

### 5.3 结构化过滤

所有搜索类型都支持以下过滤参数:

**top_k 限制**: 1 ≤ top_k ≤ 100, 超出范围返回 400。

| 参数 | 类型 | 说明 | 示例 |
|------|------|------|------|
| repo_name | str | 仓库过滤 | `ghmail` |
| project_type | str | 项目类型 | `ios` |
| language | str | 语言过滤 | `objc` |
| chunk_type | str | 代码块类型 | `class` |
| file_path | str | 路径前缀匹配 | `GHProtocol/` |
| symbol_name | str | 符号名精确匹配 | `GHMailListCellModel` |

### 5.4 搜索结果结构

```python
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
    "parent_symbol_id": "ghmail_GHList/GHMailListCellModel.m_GHMailListCellModel__0",  // 所在类/协议的 chunk id, 用于前端跳转
    "metadata": {
        "parent_class": "GHMailListCellModel",
        "paired_file": "GHMailListCellModel.h"
    }
}
```

### 5.5 RAG 问答

- 和现有 chat 接口逻辑一致: 搜索 → 拼 context → LLM 生成回答
- system prompt 适配代码场景:
  - "你是代码助手, 基于检索到的代码片段回答问题"
  - "回答时引用具体的文件路径和行号"
  - "如果代码片段不足以回答, 明确告知"
- LLM 未配置时, chat 接口返回 503

---

## 6. API 接口设计

新增独立路由模块 `backend/code_routes.py`, 注册到 main.py。

### 6.1 REST API

| 方法 | 路径 | 说明 | 需要 LLM |
|------|------|------|----------|
| POST | /api/code/scan | 增量扫描目录 (基于 mtime 跳过未变化文件) | ❌ |
| POST | /api/code/search | 混合搜索 (向量+关键词) | ❌ |
| POST | /api/code/chat | RAG 代码问答 | ✅ |
| GET | /api/code/repos | 已索引的仓库列表 | ❌ |
| GET | /api/code/stats | 索引统计信息 | ❌ |
| DELETE | /api/code/repos/{name} | 删除仓库索引 | ❌ |
| POST | /api/code/repos/{name}/refresh | 全量刷新仓库 (先清空旧数据再全量重建, 幂等) | ❌ |

### 6.2 接口详情

详见 `docs/code-kb-api.md`

---

## 7. MCP 协议设计

### 7.1 架构

MCP server 内嵌到 FastAPI 服务, 使用 HTTP+SSE 传输。

```
┌──────────────────────────────────────┐
│  FastAPI 服务 (服务器)                │
│  ├── REST API (/api/code/*)         │
│  ├── MCP Server (/mcp/sse)          │
│  └── 静态文件 (前端)                 │
└──────────────┬───────────────────────┘
               │ HTTP/SSE
    ┌──────────┼──────────┐
    │          │          │
┌───▼───┐ ┌───▼───┐ ┌───▼───┐
│Hermes │ │Claude │ │浏览器 │
│MCP    │ │Desktop│ │ REST  │
└───────┘ └───────┘ └───────┘
```

### 7.2 MCP Tools

| Tool | 说明 | 输入 | 输出 |
|------|------|------|------|
| code_search | 搜索代码库 | query, repo?, language?, symbol?, mode?, top_k? | 搜索结果列表 |
| code_chat | RAG 代码问答 | question, repo?, language? | LLM 回答 + 引用 |
| code_list_repos | 列出已索引仓库 | 无 | 仓库列表 |
| code_file_context | 获取文件上下文 | repo, file_path, line_start?, line_end? | 文件内容 (无行号参数时返回完整文件, 最大 5000 字符; 有行号参数时返回指定范围 + 前后各 10 行上下文) |

### 7.3 认证

MCP 端点支持可选的 token 认证:

```
# .env
MCP_AUTH_TOKEN=your-secret-token   # 留空则不鉴权
```

请求时通过 header 传递:
```
Authorization: Bearer <token>
```

### 7.4 本地 Hermes 配置

```yaml
# ~/.hermes/config.yaml
mcp:
  servers:
    code-kb:
      url: http://server-ip:8000/mcp/sse
      headers:
        Authorization: "Bearer your-secret-token"
```

---

## 8. 前端设计

### 8.1 页面结构

三列布局, 复用现有风格, 新增 "代码知识库" tab。

```
┌──────────────────────────────────────────────────────────┐
│  [文档知识库]  [邮件知识库]  [代码知识库]  ← tab 切换      │
├──────────────────────────────────────────────────────────┤
│  ┌─────────────┐ ┌──────────────────┐ ┌──────────────┐  │
│  │  左列        │ │  中列             │ │  右列         │  │
│  │ 仓库管理     │ │ 搜索结果          │ │ 执行流程      │  │
│  │  - 仓库列表  │ │  - 代码片段       │ │  - 步骤追踪   │  │
│  │  - 扫描新    │ │  - 语法高亮       │ │  - 耗时统计   │  │
│  │    仓库     │ │  - 匹配原因       │ │  - 折叠展开   │  │
│  │  - 统计     │ │                  │ │              │  │
│  │             │ │ ──────────────── │ │              │  │
│  │ ────────── │ │ 问答区            │ │              │  │
│  │ 过滤器      │ │  - 输入框         │ │              │  │
│  │  - 仓库     │ │  - 流式回答       │ │              │  │
│  │  - 语言     │ │  - 引用源         │ │              │  │
│  │  - 类型     │ │                  │ │              │  │
│  └─────────────┘ └──────────────────┘ └──────────────┘  │
└──────────────────────────────────────────────────────────┘
```

### 8.2 左列 - 仓库管理

- 仓库列表卡片: 名称、类型图标、语言标签、文件数、chunk 数、上次扫描时间
- "扫描新仓库"按钮: 弹出表单 (repo_name, repo_path, project_type, 语言选择, 跳过规则)
- 统计摘要: 总仓库数、总 chunk 数、语言分布标签+数量

### 8.3 中列 - 搜索结果 + 问答

- 搜索框 + 模式切换 (语义/关键词/混合)
- 结果卡片:
  - 文件路径 (可点击展开上下文)
  - 语言标签 + chunk_type 标签
  - 代码片段 (语法高亮, 匹配行高亮)
  - 匹配原因 ("语义相似" / "关键词匹配: markRead")
  - 分数
- 问答区域:
  - 输入框 + 发送按钮
  - 流式回答 (markdown 渲染)
  - 引用源列表 (可跳转到搜索结果)

### 8.4 右列 - 执行流程

- 复用现有 StepTracker 组件
- 每步折叠展开, 显示耗时、详情

### 8.5 LLM 未配置时

- 搜索功能正常
- 问答按钮灰掉, hover 提示 "请先配置 LLM"

---

## 9. 错误处理与边界情况

### 9.1 错误处理

| 场景 | 处理方式 |
|------|---------|
| 目录不存在/无权限 | scan 接口返回 400, 提示具体路径和权限问题 |
| 不支持的语言/扩展名 | 跳过该文件, 统计到 skipped_files, 不中断扫描 |
| tree-sitter 解析失败 | 降级为整文件 chunk, 记录 warning 到 metadata |
| 单文件过大 (>100KB) | 跳过, 记录到 skipped_files |
| LanceDB/SQLite 写入失败 | 回滚本次扫描的所有数据, 返回错误 |
| Embedding 模型未加载 | 首次请求时自动加载, 返回 loading 提示 |
| LLM 未配置 | chat 接口返回 503, 提示配置 LLM |
| MCP 连接断开 | SSE 自动重连, 无需特殊处理 |
| 同仓库并发扫描 | 第二次请求返回 409, 提示 "正在扫描中" |
| MCP code_file_context 大文件 | 限制最大返回 5000 字符, 超出截断并提示 |

### 9.2 边界情况

- 重复扫描同一仓库 (scan): 增量模式, 基于 mtime 跳过未变化文件, 新增/修改的文件重新解析写入
- 全量刷新 (refresh): 先清空该仓库的旧数据, 再全量重建 (幂等)
- 仓库路径变更: 视为新仓库, 旧数据保留 (用户手动删除旧的)
- 空仓库/无可索引文件: 返回 200 但 chunks=0, 提示无内容
- .h/.m 配对缺失: 单独存在也正常索引, paired_file 字段为空

---

## 10. 部署方案

### 10.1 服务器部署

```bash
# 1. 克隆项目
git clone <repo> && cd email-wiki-demo

# 2. 创建虚拟环境
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. 配置环境变量
cp backend/.env.example backend/.env
# 编辑 .env, 配置 LLM_API_KEY 等

# 4. 启动服务
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
```

### 10.2 本地 MCP 连接

在 Hermes config.yaml 中添加:
```yaml
mcp:
  servers:
    code-kb:
      url: http://server-ip:8000/mcp/sse
      headers:
        Authorization: "Bearer your-secret-token"
```

### 10.3 性能预估

| 指标 | 预估值 |
|------|--------|
| 扫描 6 个仓库 ~7500 文件 | 3-5 分钟 |
| Embedding 模型首次加载 | ~10 秒 |
| 单次搜索延迟 | < 200ms |
| 内存占用 (模型) | ~500MB |
| 内存占用 (数据) | ~100MB |

---

## 11. 新增文件清单

| 文件 | 职责 |
|------|------|
| `backend/code_parser.py` | tree-sitter AST 解析 + 混合分块 |
| `backend/code_db.py` | LanceDB + SQLite FTS 存储层 |
| `backend/code_search.py` | 混合搜索 + RRF 融合排序 |
| `backend/code_routes.py` | REST API 路由 |
| `backend/code_mcp_v2.py` | MCP server + tools（Streamable HTTP, mcp SDK v1.12.4，v2.0 起替换 v1 SSE） |
| `backend/code_config.py` | 扫描配置管理 (code_repos.json) |
| `frontend/index.html` | 前端新增代码知识库 tab |

### 依赖新增

```
# requirements.txt 新增
tree-sitter-language-pack>=1.8.0
mcp>=1.0.0
```
