# e5-small 跨语言模型替换 + 向量路中文原文 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 代码 embedding 模型从 bge-small-en 换为 multilingual-e5-small，向量路直接用中文原文 embed，翻译层退化为仅服务符号路。

**Architecture:** 三路混搜架构不动。向量路 B 从"翻译英文→embed"改为"中文原文→embed"（e5 跨语言原生支持）。翻译层（词典→缓存→LLM）保留但只服务符号路 C 的 `LIKE symbol_name` 精确匹配。维度 384 不变，LanceDB schema 不动。

**Tech Stack:** sentence-transformers, PyTorch MPS fp16, multilingual-e5-small (118M, 384-dim)

---

### Task 1: `code_embedder.py` — 模型 + 前缀 + MPS + 长度保护

**Files:**
- Rewrite: `backend/code_embedder.py`

- [ ] **Step 1: 替换 code_embedder.py 全文**

```python
"""代码 Embedding - multilingual-e5-small

multilingual-e5-small: 118M，384-dim，512-token，94语言跨语言模型。
原生支持中文 query → 英文代码的跨语言检索，不再依赖翻译层架桥。
"""

import os
import torch
import logging
from sentence_transformers import SentenceTransformer

log = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_CACHE_DIR = os.path.join(PROJECT_ROOT, "models")

_MODEL_NAME = "intfloat/multilingual-e5-small"
_DIMENSION = 384
_QUERY_PREFIX = "query: "
_PASSAGE_PREFIX = "passage: "
# e5-small token 上限 512；英文代码 ~3 chars/token，1100 chars 在安全域内；
# 中文注释密集区可能超限，超出截断并 warning
_MAX_CHARS = 1100

_model = None


def _load_model() -> SentenceTransformer:
    """模型加载（单例，MPS + fp16 加速）"""
    global _model

    if _model is not None:
        return _model

    os.makedirs(MODEL_CACHE_DIR, exist_ok=True)
    print(f"正在加载 Embedding 模型: {_MODEL_NAME} ...")
    print(f"模型缓存目录: {MODEL_CACHE_DIR}")

    _model = SentenceTransformer(
        _MODEL_NAME,
        cache_folder=MODEL_CACHE_DIR,
        model_kwargs={"torch_dtype": "float16"},
    )

    # MPS 加速
    if hasattr(torch, 'backends') and hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
        try:
            _model = _model.to('mps')
            print("Embedding 模型已移至 MPS (Apple Silicon GPU)")
        except Exception:
            pass

    print(f"模型加载完成!")
    return _model


def get_model() -> SentenceTransformer:
    """获取模型实例（单例）"""
    return _load_model()


def embed_text(text: str) -> list[float]:
    """passage embedding（索引阶段用，加 passage: 前缀）"""
    model = get_model()
    if len(text) > _MAX_CHARS:
        log.warning(f"文本过长 ({len(text)} > {_MAX_CHARS})，已截断")
    safe_text = text[:_MAX_CHARS] if len(text) > _MAX_CHARS else text
    embedding = model.encode(_PASSAGE_PREFIX + safe_text, normalize_embeddings=True)
    return embedding.tolist()


def embed_query(text: str) -> list[float]:
    """query embedding（搜索阶段用，加 query: 前缀）"""
    model = get_model()
    if len(text) > _MAX_CHARS:
        log.warning(f"查询过长 ({len(text)} > {_MAX_CHARS})，已截断")
    safe_text = text[:_MAX_CHARS] if len(text) > _MAX_CHARS else text
    embedding = model.encode(_QUERY_PREFIX + safe_text, normalize_embeddings=True)
    return embedding.tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """批量 embedding（索引阶段用，加 passage: 前缀）"""
    model = get_model()
    truncated = sum(1 for t in texts if len(t) > _MAX_CHARS)
    if truncated:
        log.warning(f"批量 embedding: {truncated}/{len(texts)} 条文本过长，已截断")
    safe_texts = [_PASSAGE_PREFIX + (t[:_MAX_CHARS] if len(t) > _MAX_CHARS else t) for t in texts]
    embeddings = model.encode(safe_texts, normalize_embeddings=True, batch_size=64)
    return embeddings.tolist()


def get_dimension() -> int:
    """返回 embedding 维度"""
    return _DIMENSION


# ── 兼容旧接口 ────────────────────────────────────────────────────

embed_code_batch = embed_batch


def get_code_model_info() -> dict:
    return {
        "model_name": _MODEL_NAME,
        "dimension": _DIMENSION,
        "cache_dir": MODEL_CACHE_DIR,
    }
```

- [ ] **Step 2: 验证模块导入正常**

```bash
cd backend && source venv/bin/activate && python3 -c "
import code_embedder
print('model:', code_embedder.get_code_model_info()['model_name'])
print('dimension:', code_embedder.get_dimension())
print('prefix query:', repr(code_embedder._QUERY_PREFIX))
print('prefix passage:', repr(code_embedder._PASSAGE_PREFIX))
" 2>&1
```
Expected: 输出 model=intfloat/multilingual-e5-small, dimension=384, prefixes 正确。不会触发模型下载（仅导入模块，未调用 embed 函数）。

- [ ] **Step 3: 提交**

```bash
git add backend/code_embedder.py
git commit -m "feat(code_embedder): 换 multilingual-e5-small + e5 前缀 + MPS fp16 + 长度保护"
```

---

### Task 2: `code_search.py` — 向量路改中文原文 + tracker 文案更新

**Files:**
- Modify: `backend/code_search.py:171, 175-176, 228-229`

- [ ] **Step 1: 修改 tracker 文案（mode=vector 分支，line 171）**

将 `"向量搜索 (bge-small-en)"` 改为 `"向量搜索 (e5-small 跨语言)"`

- [ ] **Step 2: 改 mode=vector 路径的 search_text（lines 175-176）**

```python
# 改前
search_text = " ".join(translated_keywords) if translated_keywords else query

# 改后
search_text = query
```

- [ ] **Step 3: 改 hybrid 路径的 search_text（lines 228-229）**

同样替换：
```python
# 改前
search_text = " ".join(translated_keywords) if translated_keywords else query

# 改后
search_text = query
```

- [ ] **Step 4: 验证 search_code 导入 + 语法**

```bash
cd backend && source venv/bin/activate && python3 -c "
import code_search
print('MIN_VECTOR_SIMILARITY =', code_search.MIN_VECTOR_SIMILARITY)
print('模块导入 OK')
" 2>&1
```
Expected: 输出阈值 0.5 + 导入成功。

- [ ] **Step 5: 提交**

```bash
git add backend/code_search.py
git commit -m "feat(code_search): 向量路改用中文原文（e5 跨语言支持）+ tracker 文案"
```

---

### Task 3: `code_mcp.py` — MCP 层空 query 防御

**Files:**
- Modify: `backend/code_mcp.py:105`

- [ ] **Step 1: 在 MCP code_search 分支新增空 query 检查**

在 `if name == "code_search":` 之后、`result = search_code(...)` 之前插入：

```python
    if name == "code_search":
        query = arguments.get("query", "").strip()
        if not query:
            return {"error": "query 不能为空"}
        result = search_code(
            query=query,
            mode=arguments.get("mode", "hybrid"),
            top_k=arguments.get("top_k", 10),
            repo_name=arguments.get("repo"),
            language=arguments.get("language"),
            symbol_name=arguments.get("symbol"),
        )
```

注意：原本 `arguments["query"]` 改为 `query` 变量。

- [ ] **Step 2: 验证防御生效**

```bash
cd backend && source venv/bin/activate && python3 -c "
from code_mcp import execute_tool
import asyncio
r = asyncio.run(execute_tool('code_search', {'query': ''}))
print('空 query:', r)
r2 = asyncio.run(execute_tool('code_search', {'query': '   '}))
print('空格 query:', r2)
" 2>&1
```
Expected: 两次都返回 `{"error": "query 不能为空"}`，不抛异常。

- [ ] **Step 3: 提交**

```bash
git add backend/code_mcp.py
git commit -m "fix(code_mcp): MCP code_search 空 query 防御"
```

---

### Task 4: MyMemory 旧缓存清理（一次性迁移）

**Files:**
- 操作: `data/translation_cache.json`（如存在）

- [ ] **Step 1: 运行清理脚本**

```bash
cd backend && source venv/bin/activate && python3 -c "
import os, json
CACHE_FILE = os.path.join('..', 'data', 'translation_cache.json')
if os.path.exists(CACHE_FILE):
    with open(CACHE_FILE, 'r') as f:
        data = json.load(f)
    before = len(data)
    cleaned = {k: v for k, v in data.items() if v.get('method') != 'mymemory'}
    after = len(cleaned)
    removed = before - after
    if removed > 0:
        with open(CACHE_FILE, 'w') as f:
            json.dump(cleaned, f, ensure_ascii=False, indent=2)
        print(f'已清理 {removed} 条 MyMemory 缓存（{before} → {after}）')
    else:
        print(f'无 MyMemory 缓存需清理（共 {before} 条）')
else:
    print('缓存文件不存在，跳过清理')
" 2>&1
```

- [ ] **Step 2: 提交（如清理了文件）**

```bash
git add ../data/translation_cache.json 2>/dev/null && git commit -m "chore: 清理 MyMemory 翻译缓存残留" || echo "无缓存文件需提交"
```

---

### Task 5: 验证 — 重建索引 + 搜索"读信"

**前置**: 服务已启动（`./start.sh`）

- [ ] **Step 1: 触发全量扫描 demofortest**

```bash
curl -s -X POST http://localhost:8000/api/code/scan \
  -H "Content-Type: application/json" \
  -d '{"repo_path":"/Users/admin/Documents/iOS_Project/demofortest"}' | python3 -m json.tool | head -20
```
Expected: 返回 scan_id，状态 pending。**此次扫描会触发模型首次下载（~470MB，需耐心等待 30s-2min）**。

- [ ] **Step 2: 等待扫描完成**

可通过 SSE 进度流监听：
```bash
# 用上一步返回的 scan_id 替换
curl -s -N "http://localhost:8000/api/code/scan/{scan_id}/sse"
```
或轮询：
```bash
curl -s http://localhost:8000/api/code/repos | python3 -c "import json,sys; d=json.load(sys.stdin); [print(r['name'],r['status']) for r in d.get('repos',[])]"
```

- [ ] **Step 3: 搜索"读信"**

```bash
curl -s -X POST http://localhost:8000/api/code/search \
  -H "Content-Type: application/json" \
  -d '{"query":"读信","mode":"hybrid","top_k":5}' | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'query: {d[\"query\"]}, mode: {d[\"mode\"]}, results: {len(d[\"results\"])}')
for r in d['results']:
    print(f'  {r[\"file_path\"]}:{r[\"line_start\"]} | {r[\"symbol_name\"]} | score={r.get(\"score\",0):.4f} | source={r[\"source\"]}')
print()
print('translation:', json.dumps(d.get('translation',{}), ensure_ascii=False, indent=2))
print('steps:')
for s in d.get('steps', []):
    print(f'  [{s[\"name\"]}] status={s[\"status\"]}')
"
```
Expected:
- Top-5 结果包含 `ReadViewController` 或 `ReadCell` 或 `ReadTable`
- `translation.method` 为 `dict`，`translated` 含 `read/mail/message`
- steps 中包含 query_translate step（翻译层仍在服务符号路）
- source 标注 `vector+symbol` 或 `vector+keyword+symbol`（三路命中）

- [ ] **Step 4: 提交**

```bash
git commit -m "verify: 扫描 demofortest + 验证「读信」召回 ReadViewController/ReadCell" --allow-empty
```
