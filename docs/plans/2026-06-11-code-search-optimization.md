# 代码搜索优化实现计划

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 优化代码搜索流程，简化为两路搜索（向量 + FTS5 关键词），保留注释，提升搜索精度。

**Architecture:** 
- 中文查询 → 翻译成英文 → 向量搜索（用英文）+ FTS5 关键词搜索（用原始中文）
- 英文查询 → 直接向量搜索 + FTS5 关键词搜索
- RRF 融合：向量结果 × 1.0 + FTS5 关键词结果 × 0.3

**Tech Stack:** Python 3.9, LanceDB, SQLite FTS5, sentence-transformers (bge-small-en-v1.5)

---

## 任务概览

| 任务 | 文件 | 说明 |
|------|------|------|
| 1 | code_parser.py | display_text 改为保留注释 |
| 2 | code_search.py | 简化搜索流程，移除三路搜索，改为两路 |
| 3 | code_db.py | 保留 search_symbol_by_keywords 代码，加注释 |
| 4 | - | 清理数据，重新扫描 |
| 5 | - | 测试搜索效果 |
| 6 | docs/ | 更新文档 |

---

## Task 1: 修改 code_parser.py - display_text 保留注释

**Objective:** 修改 `_make_display_text` 函数，保留代码注释，增加语义信息。

**Files:**
- Modify: `backend/code_parser.py:780-810`

**Step 1: 读取当前实现**

```python
def _make_display_text(
    rel_path: str,
    chunk_type: str,
    symbol_name: str,
    line_start: int,
    line_end: int,
    content: str,
    language: str,
) -> str:
    """构造带上下文头部的 display_text，用于 embedding 提升检索质量

    注释会被剥离——中文注释/字符串字面量会误导跨语言 embedding 模型
    （如中文 query 匹配代码里的中文注释而非符号语义）。
    """
    if language in ('python', 'ruby', 'shell', 'yaml', 'json'):
        prefix = '#'
        clean_content = _HASH_COMMENT_RE.sub('', content)
    else:
        prefix = '//'
        clean_content = _C_COMMENT_RE.sub('', content)

    # 剥离中文字符串（硬编码字符串/测试数据，干扰跨语言检索）
    clean_content = _CN_STRIP_RE.sub('', clean_content)

    if chunk_type == 'file':
        type_info = 'file'
    else:
        type_info = f"{chunk_type}: {symbol_name}"

    header = f"{prefix} File: {rel_path} | {type_info} | Lines {line_start}-{line_end}"
    return f"{header}\n{clean_content}"
```

**Step 2: 修改为保留注释**

```python
def _make_display_text(
    rel_path: str,
    chunk_type: str,
    symbol_name: str,
    line_start: int,
    line_end: int,
    content: str,
    language: str,
) -> str:
    """构造带上下文头部的 display_text，用于 embedding 提升检索质量

    保留注释——注释包含语义信息，有助于提升搜索精度。
    bge-small-en 模型对英文注释有较好的理解能力。
    """
    if language in ('python', 'ruby', 'shell', 'yaml', 'json'):
        prefix = '#'
    else:
        prefix = '//'

    if chunk_type == 'file':
        type_info = 'file'
    else:
        type_info = f"{chunk_type}: {symbol_name}"

    header = f"{prefix} File: {rel_path} | {type_info} | Lines {line_start}-{line_end}"
    return f"{header}\n{content}"
```

**Step 3: 测试修改**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend
source venv/bin/activate
python3 -c "
from code_parser import _make_display_text
result = _make_display_text(
    'test.py', 'method', 'test_func', 1, 10,
    '# This is a comment\ndef test_func():\n    pass',
    'python'
)
print(result)
"
```

**Step 4: 提交修改**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo
git add backend/code_parser.py
git commit -m "refactor(code-parser): display_text 保留注释，增加语义信息"
```

---

## Task 2: 修改 code_search.py - 简化搜索流程

**Objective:** 简化搜索流程，移除三路搜索，改为两路（向量 + FTS5 关键词）。

**Files:**
- Modify: `backend/code_search.py:112-330`

**Step 1: 读取当前实现**

当前实现是三路搜索：
- 路径A: FTS5 关键词搜索（搜原始中文 content）
- 路径B: 向量搜索（搜翻译后英文）
- 路径C: 符号名搜索（搜翻译后英文关键词 LIKE symbol_name）

**Step 2: 修改为两路搜索**

```python
def search_code(
    query: str,
    mode: str = "hybrid",
    top_k: int = 10,
    repo_name: Optional[str] = None,
    project_type: Optional[str] = None,
    language: Optional[str] = None,
    chunk_type: Optional[str] = None,
    file_path: Optional[str] = None,
    symbol_name: Optional[str] = None,
    tracker: Optional[StepTracker] = None,
) -> dict:
    """代码搜索主入口

    Args:
        query: 搜索内容
        mode: vector / keyword / hybrid
        top_k: 返回数量 (1-100)
        repo_name, project_type, language, chunk_type, file_path, symbol_name: 过滤条件
        tracker: 步骤追踪器

    Returns:
        {\"query\": str, \"mode\": str, \"results\": [...], \"steps\": [...]}
    """
    # top_k 限流
    top_k = max(1, min(top_k, 100))

    # ── 查询翻译（中文 → 英文关键词） ──
    translated_keywords = []
    translation_info = None
    if _has_chinese(query):
        step_trans = None
        if tracker:
            step_trans = tracker.add_step("query_translate", "查询翻译: 中文→英文关键词")
            step_trans.start()

        from query_translator import translate_query_sync
        translation = translate_query_sync(query, use_llm=True, timeout=3.0, tracker=tracker)
        translated_keywords = translation.translated
        translation_info = {
            "original": translation.original,
            "translated": translated_keywords,
            "method": translation.method,
            "confidence": translation.confidence,
            "duration_ms": getattr(translation, "duration_ms", 0.0),
            "steps": getattr(translation, "steps", []) or [],
        }

        if tracker and step_trans:
            step_trans.complete({
                "method": translation.method,
                "keywords": translated_keywords,
                "confidence": translation.confidence,
            })

    results = []

    if mode == "vector":
        if tracker:
            step = tracker.add_step("vector_search", "向量搜索 (bge-small-en)")
            step.start()

        from code_embedder import embed_query
        # 向量搜索用翻译后的英文关键词
        search_text = " ".join(translated_keywords) if translated_keywords else query
        query_vec = embed_query(search_text)

        results = search_vector(
            query_vector=query_vec,
            top_k=top_k,
            repo_name=repo_name,
            language=language,
            chunk_type=chunk_type,
            file_path=file_path,
        )

        # 过滤低质量向量结果
        results = [r for r in results if r.get("score", 0) >= MIN_VECTOR_SIMILARITY]

        if tracker:
            step.complete({"results_count": len(results)})

    elif mode == "keyword":
        if tracker:
            step = tracker.add_step("keyword_search", "关键词搜索 (SQLite FTS5)")
            step.start()

        results = search_keyword(
            query=query,
            top_k=top_k,
            repo_name=repo_name,
            language=language,
            chunk_type=chunk_type,
            file_path=file_path,
            symbol_name=symbol_name,
        )

        if tracker:
            step.complete({"results_count": len(results)})

    else:
        # ── hybrid: 两路搜索 + RRF ──
        from code_embedder import embed_query

        if tracker:
            step_hybrid = tracker.add_step("hybrid_search", "混合搜索 (向量+关键词)")
            step_hybrid.start()

        pool_k = max(top_k * 5, 100)

        # 路径A: FTS5 关键词搜索（搜原始中文 content）
        keyword_results = search_keyword(
            query=query, top_k=pool_k,
            repo_name=repo_name, language=language,
            chunk_type=chunk_type, file_path=file_path,
            symbol_name=symbol_name,
        )

        # 路径B: 向量搜索（用翻译后的英文关键词 embed）
        search_text = " ".join(translated_keywords) if translated_keywords else query
        query_vec = embed_query(search_text)
        vector_results = search_vector(
            query_vector=query_vec, top_k=pool_k,
            repo_name=repo_name, language=language,
            chunk_type=chunk_type, file_path=file_path,
        )

        # 过滤低质量向量结果
        vector_results = [r for r in vector_results if r.get("score", 0) >= MIN_VECTOR_SIMILARITY]

        if tracker:
            step_hybrid.complete({
                "vector_hits": len(vector_results),
                "keyword_hits": len(keyword_results),
                "translated_keywords": translated_keywords,
            })
            step_rrf = tracker.add_step("rrf_fusion", "RRF 融合排序 (2路)")
            step_rrf.start()

        # RRF 融合：向量 1.0x，关键词 0.3x
        results = rrf_fusion(
            vector_results, keyword_results,
            top_k=top_k,
            weights=[1.0, 0.3],
        )

        # 标注来源
        vec_ids = {r["id"] for r in vector_results}
        kw_ids = {r["id"] for r in keyword_results}

        filtered = []
        for r in results:
            cid = r["id"]
            sources = []
            if cid in vec_ids:
                sources.append("vector")
            if cid in kw_ids:
                sources.append("keyword")
            r["source"] = "+".join(sources) if len(sources) > 1 else (sources[0] if sources else "unknown")

            # 过滤仅向量命中且低相似度的结果
            if r["source"] == "vector" and r.get("score", 0) < MIN_VECTOR_SIMILARITY:
                continue
            filtered.append(r)
        results = filtered

        if tracker:
            step_rrf.complete({
                "vector_hits": len(vector_results),
                "keyword_hits": len(keyword_results),
                "merged": len(results),
            })

        # ── 按 file_name 去重：每组只保留 score 最高的一条 ──
        if results:
            best_by_file: dict[str, dict] = {}
            for r in results:
                repo = r.get("repo_name") or ""
                fname = r.get("file_path") or r.get("file_name") or ""
                dedup_key = f"{repo}::{fname}"
                cur = best_by_file.get(dedup_key)
                if cur is None or r.get("score", 0) > cur.get("score", 0):
                    best_by_file[dedup_key] = r
            results = list(best_by_file.values())

    # match_reason
    for r in results:
        r["match_reason"] = _generate_match_reason(r, query, mode, translated_keywords)
        # parent_symbol_id: 所在类/协议的 chunk id
        parent_class = r.get("metadata", {}).get("parent_class", "")
        if parent_class:
            r["parent_symbol_id"] = f"{r['repo_name']}_{r['file_path']}___{parent_class}_0"
        else:
            r["parent_symbol_id"] = None

    response = {
        "query": query,
        "mode": mode,
        "results": results,
        "steps": tracker.to_list() if tracker else [],
    }
    if translation_info:
        response["translation"] = translation_info

    return response
```

**Step 3: 测试修改**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend
source venv/bin/activate
python3 -c "
from code_search import search_code
result = search_code('读信', mode='hybrid', top_k=5)
print(f'查询: {result[\"query\"]}')
print(f'结果数: {len(result[\"results\"])}')
for i, r in enumerate(result['results'][:3]):
    print(f'{i+1}. {r.get(\"symbol_name\", \"\")} | score={r.get(\"score\", 0):.4f}')
"
```

**Step 4: 提交修改**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo
git add backend/code_search.py
git commit -m "refactor(code-search): 简化为两路搜索（向量+FTS5关键词），移除符号名搜索"
```

---

## Task 3: 修改 code_db.py - 保留 search_symbol_by_keywords 代码，加注释

**Objective:** 保留 search_symbol_by_keywords 代码，加注释说明暂时不使用，后续可作为精确匹配的补充。

**Files:**
- Modify: `backend/code_db.py:503-625`

**Step 1: 读取当前实现**

```python
def search_symbol_by_keywords(
    keywords: list[str],
    top_k: int = 10,
    repo_name: Optional[str] = None,
    language: Optional[str] = None,
    chunk_type: Optional[str] = None,
) -> list[dict]:
    """用英文关键词搜索 symbol_name 和 file_path 字段

    TODO: LIKE '%keyword%' 无法走 B-tree 索引，大数据量下全表扫描。
    后续可为 symbol_name 建 FTS5 虚拟表或 trigram 索引加速。

    对每个关键词: symbol_name LIKE '%keyword%' OR file_path LIKE '%keyword%'
    多关键词命中越多的排越前（按命中数降序）。

    Args:
        keywords: 翻译后的英文关键词列表 ["login", "signin", "auth"]
        top_k: 最多返回条数
        repo_name, language, chunk_type: 可选过滤条件
    """
    # ... 实现代码 ...
```

**Step 2: 添加注释说明**

```python
def search_symbol_by_keywords(
    keywords: list[str],
    top_k: int = 10,
    repo_name: Optional[str] = None,
    language: Optional[str] = None,
    chunk_type: Optional[str] = None,
) -> list[dict]:
    """用英文关键词搜索 symbol_name 和 file_path 字段

    【后续优化方向】
    当前实现使用 LIKE '%keyword%' 做全表扫描，大数据量下性能差。
    后续可优化为：
    1. 为 symbol_name 建 FTS5 虚拟表或 trigram 索引加速
    2. 用 FTS5 trigram 索引替代 LIKE 全表扫描
    3. 降低权重：符号搜索权重设为 0.5（向量搜索权重为 1.0）

    当前状态：暂时不使用，保留代码作为后续优化方向。

    对每个关键词: symbol_name LIKE '%keyword%' OR file_path LIKE '%keyword%'
    多关键词命中越多的排越前（按命中数降序）。

    Args:
        keywords: 翻译后的英文关键词列表 ["login", "signin", "auth"]
        top_k: 最多返回条数
        repo_name, language, chunk_type: 可选过滤条件
    """
    # ... 实现代码 ...
```

**Step 3: 提交修改**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo
git add backend/code_db.py
git commit -m "docs(code-db): search_symbol_by_keywords 添加注释说明，标记为后续优化方向"
```

---

## Task 4: 清理数据，重新扫描

**Objective:** 清理 LanceDB 中的 1024 维向量数据，重新扫描。

**Files:**
- Delete: `data/code_lancedb/` 目录
- Delete: `data/code_index.db` 中的 code_meta、code_fts、code_relations 表

**Step 1: 停止服务**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo
./stop.sh
```

**Step 2: 清理数据**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo
rm -rf data/code_lancedb/
rm -f data/code_index.db
rm -f data/code_repos.json
```

**Step 3: 重启服务**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo
./start.sh
```

**Step 4: 重新扫描**

通过 Web UI 或 API 重新扫描代码仓库。

---

## Task 5: 测试搜索效果

**Objective:** 测试中文查询和英文查询的搜索效果。

**Step 1: 测试中文查询**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend
source venv/bin/activate
python3 -c "
from code_search import search_code
result = search_code('读信', mode='hybrid', top_k=10)
print(f'查询: {result[\"query\"]}')
print(f'结果数: {len(result[\"results\"])}')
for i, r in enumerate(result['results'][:5]):
    print(f'{i+1}. {r.get(\"symbol_name\", \"\")} | score={r.get(\"score\", 0):.4f} | {r.get(\"file_path\", \"\")}')
"
```

**Step 2: 测试英文查询**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend
source venv/bin/activate
python3 -c "
from code_search import search_code
result = search_code('read mail', mode='hybrid', top_k=10)
print(f'查询: {result[\"query\"]}')
print(f'结果数: {len(result[\"results\"])}')
for i, r in enumerate(result['results'][:5]):
    print(f'{i+1}. {r.get(\"symbol_name\", \"\")} | score={r.get(\"score\", 0):.4f} | {r.get(\"file_path\", \"\")}')
"
```

**Step 3: 验证结果**

- 中文查询 "读信" 应该返回 GHReadViewController、RCReadVC 等读信相关类
- 英文查询 "read mail" 应该返回类似结果
- 搜索结果应该包含 score 字段，表示搜索相关性

---

## Task 6: 更新文档

**Objective:** 更新 AGENTS.md 和相关文档。

**Files:**
- Modify: `AGENTS.md`

**Step 1: 更新搜索流程说明**

在 AGENTS.md 中更新搜索流程说明：

```markdown
### 代码搜索流程

**中文查询**：
1. 检测到中文 → 翻译成英文关键词（词典 → 缓存 → MyMemory API → LLM）
2. 向量搜索：用英文关键词做 embedding，搜索 LanceDB
3. FTS5 关键词搜索：用原始中文查询搜索 SQLite FTS5
4. RRF 融合：向量结果 × 1.0 + FTS5 关键词结果 × 0.3
5. 去重：按 file_name 去重，每组只保留 score 最高的一条

**英文查询**：
1. 直接用英文查询做 embedding
2. 向量搜索：搜索 LanceDB
3. FTS5 关键词搜索：用英文查询搜索 SQLite FTS5
4. RRF 融合：向量结果 × 1.0 + FTS5 关键词结果 × 0.3
5. 去重：按 file_name 去重，每组只保留 score 最高的一条
```

**Step 2: 更新打分公式说明**

```markdown
### 搜索结果打分

**向量搜索打分**：
```python
score = (1 - distance + 1) / 2
# distance = 0.0 → score = 1.0（完全相似）
# distance = 1.0 → score = 0.5（正交）
# distance = 2.0 → score = 0.0（完全相反）
```

**FTS5 关键词搜索打分**：
```python
score = 1.0 / (1.0 + abs(rank))
# rank 越小越相关，归一化到 0-1 范围
```

**RRF 融合打分**：
```python
score = Σ(weight / (k + rank))
# k = 60（常量）
# weight：每路的权重（向量 1.0，关键词 0.3）
```

**Step 3: 提交修改**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo
git add AGENTS.md
git commit -m "docs: 更新代码搜索流程和打分公式说明"
```

---

## 验证清单

- [ ] Task 1: code_parser.py 修改完成，display_text 保留注释
- [ ] Task 2: code_search.py 修改完成，简化为两路搜索
- [ ] Task 3: code_db.py 修改完成，search_symbol_by_keywords 添加注释
- [ ] Task 4: 数据清理完成，重新扫描
- [ ] Task 5: 测试通过，中文查询返回 GHReadViewController、RCReadVC
- [ ] Task 6: 文档更新完成

---

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 保留注释导致中文干扰 | 中文查询可能匹配到注释而非符号 | FTS5 关键词搜索用原始中文，向量搜索用翻译后英文 |
| FTS5 关键词搜索性能 | 大数据量下可能较慢 | 使用 FTS5 索引，避免全表扫描 |
| RRF 融合权重不合适 | 搜索结果可能不理想 | 可调整权重配置 |

---

## 回滚方案

如果出现问题，可以回滚到之前的版本：

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo
git checkout HEAD~1 -- backend/code_parser.py backend/code_search.py backend/code_db.py
```
