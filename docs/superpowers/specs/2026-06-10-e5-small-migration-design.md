# e5-small 跨语言模型替换 + 向量路中文原文

> 日期：2026-06-10 | 状态：待实现 | 模型选择：方案 A（翻译层保留，向量路改中文）

## 背景

代码搜索当前用 `BAAI/bge-small-en-v1.5`（纯英文，384维），中文 query 必须先翻译成英文才能 embed。翻译出错 → 向量路 + 符号路两路一起偏，零阈值放大噪声。

根因调研结论：搜"读信"时词典缺词 → MyMemory 降级直译 `letter/reading` → 命中不了 `ReadViewController`/`ReadCell`（词根 `read`）。

## 目标

| 指标 | 改前 | 改后 |
|------|------|------|
| 代码 embedding 模型 | bge-small-en（纯英文） | multilingual-e5-small（94语言） |
| 向量路输入 | 翻译后英文关键词 | 中文原文 |
| 翻译层角色 | 向量路+符号路双用 | 仅服务符号路（LIKE 精确匹配） |
| 向量召回阈值 | 0.0（不过滤） | 0.5（正相关起） |
| "读信"词典命中 | ❌ 空 → MyMemory 直译 | ✅ 词典直接命中 read/mail/message |

## 受影响文件

| 文件 | 角色 | 改动性质 |
|------|------|----------|
| `code_embedder.py` | 模型加载 + 前缀 + MPS + 长度保护 | 🔴 核心改动 |
| `code_search.py` | 向量路搜索文本改为中文原文 | 🔴 核心改动 |
| `code_mcp.py` | MCP 层新增空 query 防御 | 🟡 防御性修复 |
| `code_db.py` | `get_dimension()` 返回值 384 不变 | 🟢 无需改动（但确认过） |
| `main.py` | `get_code_model_info()` 返回值自动变 | 🟢 无需改动（`_MODEL_NAME` 改了自动生效） |
| `query_translator.py` | 三项已完成修复保留不改 | 🟢 已完成 |

## 改动清单

### 1. `backend/code_embedder.py` — 换模型 + 前缀 + MPS + 长度保护

**模型**：`BAAI/bge-small-en-v1.5` → `intfloat/multilingual-e5-small`（384维不变，LanceDB schema 不动）

**前缀**（e5 系列不对称前缀。依据：HuggingFace 模型卡 `intfloat/multilingual-e5-small`，训练时 query 侧用 `query:` 前缀、passage 侧用 `passage:` 前缀，推理时不加前缀会导致 query/passage 不在同一语义子空间，召回质量劣化）：

| 函数 | 前缀 | 调用方 |
|------|------|--------|
| `embed_query()` | `query: ` | code_search.py（搜索时） |
| `embed_text()` | `passage: ` | 当前无人调用，加前缀防未来复用入坑 |
| `embed_batch()` | `passage: ` | `_run_scan -> _process_batch`（通过 `embed_code_batch` 别名，索引时） |

**MPS+fp16 加速**（复用文档 `embedder.py` 写法）：
- 构造函数 `model_kwargs={"torch_dtype": "float16"}`
- `.to('mps')` + try/except 兜底
- batch_size 从 32 → 64（fp16 减半显存）

**长度保护**（新增，bge 换 e5 后 token 上限从 512 收紧）：
- 当前 `_make_display_text` 产出：header(~100 chars) + content(≤1000 chars) ≈ ≤1100 chars
- e5-small tokenizer 上限 512 tokens。英文代码 ~3 chars/token → ≤1100 chars 在安全域内；中文注释密集区可能超限
- 新增 `_MAX_CHARS = 1100` 截断 + 告警计数（参考文档 `embedder.py:19`），超长文本截断后仍 embed 但记录 warning

### 2. `backend/code_search.py` — 向量路改中文原文

两处改动（mode=vector 和 hybrid 各一）：

```python
# 改前
search_text = " ".join(translated_keywords) if translated_keywords else query

# 改后
search_text = query
```

翻译层保留不动，继续产出 `translated_keywords` 给符号路 C（`search_symbol_by_keywords`，需要英文词根 `LIKE %read%` 匹配 OC 符号名）。

### 3. `backend/code_mcp.py` — 空 query 防御（防御性修复）

HTTP 端点 `/api/code/search` 已有 query 校验（`code_routes.py:512`），但 MCP `execute_tool("code_search")` 直接把 `arguments["query"]` 透传给 `search_code`，空字符串/纯空白未拦截。

**修复**：MCP `code_search` 分支新增空 query 检查：`if not arguments.get("query", "").strip(): return {"error": "query 不能为空"}`。

### 4. 已完成修复（本分支保留，不再改）

| 文件 | 行 | 改动 |
|------|-----|------|
| `query_translator.py` | 70-72 | TERM_MAP 加 `读信/读邮件/阅读` → `read/mail/message` |
| `code_search.py` | 33 | `MIN_VECTOR_SIMILARITY` 0.0 → 0.5 |
| `query_translator.py` | 556-559 | MyMemory 分支删 `cache.set` + `add_to_dict` |

### 5. 重建索引（必须）

**换模型 = 向量空间变了**。虽然维度同为 384（LanceDB schema 不变），但新旧模型产出的向量余弦距离不可互比——旧向量对新模型 query 是随机噪声。

扫描 `/Users/admin/Documents/iOS_Project/demofortest`（917 个 OC 文件）做全量索引重建。

### 6. MyMemory 旧缓存清理（一次性迁移）

已删除 MyMemory 写入逻辑，但如有 `data/translation_cache.json` 且含 `"method": "mymemory"` 的旧条目，`cache.get` 命中后仍会返回错误翻译影响符号路。实施时执行：

```python
from translation_cache import get_cache
cache = get_cache()
for q, e in list(cache.cache.items()):
    if e.method == "mymemory":
        del cache.cache[q]
cache._save()
```

## 三路搜索改后数据流

```
用户输入"读信"
  │
  ├─ 翻译层（保留）：词典命中 → ["read", "mail", "message"]
  │   │
  │   └─ 路径C 符号名：symbol_name LIKE '%read%' → ReadViewController ✅
  │
  ├─ 路径A 关键词（FTS5）：MATCH '读信' → 搜中文 content
  │
  └─ 路径B 向量：embed_query("query: 读信") → LanceDB cosine → ReadViewController ✅
      （不再走翻译，中文原文直接跨语言 embed）
```

## 验证

1. 重建索引：`POST /api/code/scan` 扫 `/Users/admin/Documents/iOS_Project/demofortest`
2. 搜 `读信`，验证召回 Top-5 包含 `ReadViewController` 或 `ReadCell`
3. 确认翻译 step 仍记录但向量路不再依赖翻译结果
4. `embed_batch` 确认每条文本都加了 `passage: ` 前缀
5. 空 query MCP 调用返回明确错误而非异常
6. `embed_batch` 传入 >1100 chars 文本确认截断 + warning 日志

## 风险

| 风险 | 缓解 |
|------|------|
| 换模型后向量阈值 0.5 偏严/偏松 | 备注上线后根据实际分数分布微调 |
| 首个代码检索/扫描请求触发模型下载（~470MB） | 网络慢会阻塞首个请求 30s-2min；扫描 `demofortest` 时自然触发下载，后续请求无感 |
| e5 模型首次跑 MPS fp16 兼容性未知 | try/except 兜底回退 CPU |
| 中文注释密集的代码 chunk 可能超 512 tokens | `_MAX_CHARS=1100` 截断 + warning 计数 |
| `embed_text` 孤函数目前无人调用 | 一并加前缀，防止未来复用入坑 |

## 审核记录

- subagent 审核（2026-06-10）：发现 2 个严重问题（embed_batch 缺 passage 前缀、未明确重建索引）→ 已纳入设计修正
- Codex 审核（GPT-5，2026-06-10）：发现 7 个问题（5×P1 + 2×P2）→ 已全部纳入设计修正。详见审核报告
