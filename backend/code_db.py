"""代码知识库存储层 - LanceDB + SQLite FTS5 双写

LanceDB: 向量检索 (语义搜索)
SQLite FTS5: 关键词检索 (符号名/路径精确搜索)
"""

import os
import json
import sqlite3
import lancedb
from datetime import datetime
from typing import Optional

from code_embedder import get_dimension
from text_utils import segment_for_fts, segment_query_for_match

# ── 路径配置 ──────────────────────────────────────────────────────

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANCEDB_PATH = os.path.join(PROJECT_ROOT, "data", "code_lancedb")
SQLITE_PATH = os.path.join(PROJECT_ROOT, "data", "code_index.db")
TABLE_NAME = "code_chunks"

# ── LanceDB 单例 ─────────────────────────────────────────────────

import threading as _threading
_db_lock = _threading.RLock()  # 可重入锁，get_table() 内部调 get_db() 不会死锁
_db = None
_table = None


def get_db() -> lancedb.DBConnection:
    """获取 LanceDB 连接"""
    global _db
    if _db is None:
        with _db_lock:
            if _db is None:
                os.makedirs(LANCEDB_PATH, exist_ok=True)
                _db = lancedb.connect(LANCEDB_PATH)
    return _db


def get_table():
    """获取 code_chunks 表 (不存在则创建，维度不匹配则自动迁移)"""
    global _table
    if _table is None:
        with _db_lock:
            if _table is None:
                db = get_db()
                dim = get_dimension()
                try:
                    _table = db.open_table(TABLE_NAME)
                    # 检查维度是否匹配
                    schema = _table.schema
                    for field in schema:
                        if field.name == 'vector' and hasattr(field.type, 'list_size'):
                            existing_dim = field.type.list_size
                            if existing_dim != dim:
                                # 维度不匹配 → 抛显式错误，不静默删数据
                                msg = (f"LanceDB 向量维度不匹配！现存={existing_dim}维, 当前={dim}维。"
                                       f"请手动执行 DELETE /api/code/repos 清除旧数据后重新扫描。")
                                print(f"[code_db] {msg}")
                                raise RuntimeError(msg)
                except FileNotFoundError:
                    _table = None
                except Exception:
                    _table = None

                if _table is None:
                    placeholder = [{
                        "id": "__placeholder__",
                        "repo_name": "",
                        "project_type": "",
                        "file_path": "",
                        "file_name": "",
                        "language": "",
                        "chunk_type": "",
                        "symbol_name": "",
                        "content": "",
                        "display_text": "",
                        "line_start": 0,
                        "line_end": 0,
                        "vector": [0.0] * dim,
                        "metadata": "{}",
                    }]
                    _table = db.create_table(TABLE_NAME, data=placeholder)
                    _table.delete("id = '__placeholder__'")
    return _table


# ── SQLite FTS5 ──────────────────────────────────────────────────

_sqlite_conn = None


def get_sqlite() -> sqlite3.Connection:
    """获取 SQLite 连接 (单例, 含 FTS5 表)"""
    global _sqlite_conn
    if _sqlite_conn is not None:
        try:
            _sqlite_conn.execute("SELECT 1")
            return _sqlite_conn
        except (sqlite3.ProgrammingError, Exception):
            _sqlite_conn = None

    os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)
    _sqlite_conn = sqlite3.connect(SQLITE_PATH, check_same_thread=False)
    _sqlite_conn.execute("PRAGMA journal_mode=WAL")

    # FTS5 虚拟表
    _sqlite_conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS code_fts USING fts5(
            chunk_id,
            content,
            symbol_name,
            file_path,
            language,
            repo_name,
            tokenize='unicode61'
        )
    """)

    # 元数据表 (用于结构化过滤和统计)
    _sqlite_conn.execute("""
        CREATE TABLE IF NOT EXISTS code_meta (
            chunk_id TEXT PRIMARY KEY,
            repo_name TEXT,
            project_type TEXT,
            file_path TEXT,
            file_name TEXT,
            language TEXT,
            chunk_type TEXT,
            symbol_name TEXT,
            line_start INTEGER,
            line_end INTEGER
        )
    """)
    _sqlite_conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_repo ON code_meta(repo_name)")
    _sqlite_conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_lang ON code_meta(language)")
    # file_name 索引：code_file_context 按 file_name 查（v2.1 起替代 file_path 入口）
    _sqlite_conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_file_name ON code_meta(file_name)")

    # 调用关系表 (call graph) + 继承关系 (inherit hierarchy)
    # relation_type: 'call' (函数调用) / 'inherit' (类继承/实现)
    # 存量数据全部为 'call'，通过 DEFAULT 兼容
    _sqlite_conn.execute("""
        CREATE TABLE IF NOT EXISTS code_relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            caller_chunk_id TEXT NOT NULL,
            caller_symbol_name TEXT,
            caller_file_path TEXT,
            callee_name TEXT NOT NULL,
            callee_line INTEGER,
            repo_name TEXT NOT NULL,
            relation_type TEXT NOT NULL DEFAULT 'call'
        )
    """)
    # 存量表 ALTER：补 relation_type 列（如果还没加）
    cols = [r[1] for r in _sqlite_conn.execute("PRAGMA table_info(code_relations)").fetchall()]
    if "relation_type" not in cols:
        _sqlite_conn.execute(
            "ALTER TABLE code_relations ADD COLUMN relation_type TEXT NOT NULL DEFAULT 'call'"
        )
    _sqlite_conn.execute("CREATE INDEX IF NOT EXISTS idx_rel_caller ON code_relations(caller_chunk_id)")
    _sqlite_conn.execute("CREATE INDEX IF NOT EXISTS idx_rel_callee ON code_relations(callee_name, repo_name)")
    _sqlite_conn.execute("CREATE INDEX IF NOT EXISTS idx_rel_repo ON code_relations(repo_name)")
    _sqlite_conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_rel_type ON code_relations(relation_type, callee_name, repo_name)"
    )
    # 唯一约束: 同一 chunk 内同符号同行同类型只记录一次
    # 加 relation_type 后旧 idx_rel_unique 需要重建（否则 unique 冲突但包含 call/inherit 不同类型）
    _sqlite_conn.execute("DROP INDEX IF EXISTS idx_rel_unique")
    _sqlite_conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_rel_unique "
        "ON code_relations(caller_chunk_id, callee_name, callee_line, repo_name, relation_type)"
    )

    _sqlite_conn.commit()
    return _sqlite_conn


def _esc(val: str) -> str:
    """转义 LanceDB where 子句中的单引号 (防注入)"""
    return val.replace("'", "''")


# ── 距离转换 ─────────────────────────────────────────────────────

def cosine_distance_to_similarity(distance: float) -> float:
    """余弦距离 → 相似度 [0, 1]"""
    return (1.0 - distance + 1.0) / 2.0


# ── 双写: 批量插入 ───────────────────────────────────────────────

def insert_chunks(chunks: list[dict]):
    """批量插入代码 chunks (同时写 LanceDB + SQLite)

    chunks: code_parser.chunk_code() 返回的结构, 需要额外带 vector 字段

    内存优化：先写 SQLite（轻量元组），再就地补字段写 LanceDB（避免整份拷贝 content+vector）
    """
    if not chunks:
        return

    # ── SQLite 写入（轻量，先写确保数据安全） ──
    conn = get_sqlite()
    fts_rows = []
    meta_rows = []
    rel_rows = []
    for c in chunks:
        fts_rows.append((
            c["id"],
            segment_for_fts(c.get("display_text", c["content"])),
            c.get("symbol_name", ""),
            c["file_path"],
            c["language"],
            c["repo_name"],
        ))
        meta_rows.append((
            c["id"],
            c["repo_name"],
            c.get("project_type", ""),
            c["file_path"],
            c.get("file_name", ""),
            c["language"],
            c["chunk_type"],
            c.get("symbol_name", ""),
            c.get("line_start", 0),
            c.get("line_end", 0),
        ))
        # 调用关系
        calls = c.get("metadata", {}).get("calls", [])
        if isinstance(calls, list):
            for call in calls:
                if isinstance(call, dict) and call.get("name"):
                    rel_rows.append((
                        c["id"],
                        c.get("symbol_name", ""),
                        c["file_path"],
                        call["name"],
                        call.get("line", 0),
                        c["repo_name"],
                        "call",
                    ))
        # 继承关系（caller = 子类，callee_name = 父类，line = 父类在 superclass 子句的行号）
        inherits = c.get("metadata", {}).get("inherits", [])
        if isinstance(inherits, list):
            for inh in inherits:
                if isinstance(inh, dict) and inh.get("parent"):
                    rel_rows.append((
                        c["id"],
                        c.get("symbol_name", ""),
                        c["file_path"],
                        inh["parent"],
                        inh.get("line", 0),
                        c["repo_name"],
                        "inherit",
                    ))

    try:
        # 先写 SQLite 但延迟 commit：若 LanceDB 失败可 rollback，避免双存储不一致
        conn.execute("BEGIN")
        conn.executemany(
            "INSERT OR REPLACE INTO code_fts (chunk_id, content, symbol_name, file_path, language, repo_name) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            fts_rows
        )
        conn.executemany(
            "INSERT OR REPLACE INTO code_meta (chunk_id, repo_name, project_type, file_path, file_name, "
            "language, chunk_type, symbol_name, line_start, line_end) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            meta_rows
        )
        if rel_rows:
            conn.executemany(
                "INSERT OR IGNORE INTO code_relations "
                "(caller_chunk_id, caller_symbol_name, caller_file_path, callee_name, callee_line, repo_name, relation_type) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rel_rows,
            )

        # ── LanceDB 写入（只提取 schema 字段，避免多余字段导致报错） ──
        # Python dict 赋值是引用拷贝，content/vector 等大对象不会复制内存
        table = get_table()
        lancedb_records = []
        for c in chunks:
            meta = c.get("metadata", {})
            meta_str = json.dumps(meta, ensure_ascii=False) if isinstance(meta, dict) else str(meta)
            lancedb_records.append({
                "id": c["id"],
                "repo_name": c["repo_name"],
                "project_type": c.get("project_type", ""),
                "file_path": c["file_path"],
                "file_name": c.get("file_name", ""),
                "language": c["language"],
                "chunk_type": c["chunk_type"],
                "symbol_name": c.get("symbol_name", ""),
                "content": c["content"],
                "display_text": c.get("display_text", c["content"]),
                "line_start": c.get("line_start", 0),
                "line_end": c.get("line_end", 0),
                "vector": c["vector"],
                "metadata": meta_str,
            })

        table.add(lancedb_records)
        # 写入后立即释放 lancedb_records，让 GC 尽早回收
        del lancedb_records

        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ── 双删: 按仓库删除 ────────────────────────────────────────────

def delete_by_repo(repo_name: str) -> int:
    """删除指定仓库的所有 chunks, 返回删除数量"""
    # ── SQLite 先查 count (避免 LanceDB to_pandas) ──
    conn = get_sqlite()
    count = conn.execute("SELECT COUNT(*) FROM code_meta WHERE repo_name = ?", (repo_name,)).fetchone()[0]

    # ── LanceDB 删除 ──
    if count > 0:
        try:
            get_table().delete(f"repo_name = '{_esc(repo_name)}'")
        except Exception:
            pass

    # ── SQLite 删除 ──
    conn.execute("DELETE FROM code_fts WHERE repo_name = ?", (repo_name,))
    conn.execute("DELETE FROM code_meta WHERE repo_name = ?", (repo_name,))
    conn.execute("DELETE FROM code_relations WHERE repo_name = ?", (repo_name,))
    conn.commit()

    return count


def delete_by_file(repo_name: str, file_path: str) -> int:
    """删除指定文件的所有 chunks（用 SQLite 计数，避免 to_pandas 全表加载）"""
    conn = get_sqlite()
    count = conn.execute(
        "SELECT COUNT(*) FROM code_meta WHERE repo_name = ? AND file_path = ?",
        (repo_name, file_path)
    ).fetchone()[0]

    if count > 0:
        try:
            get_table().delete(f"repo_name = '{_esc(repo_name)}' AND file_path = '{_esc(file_path)}'")
        except Exception:
            pass

    conn.execute("DELETE FROM code_meta WHERE repo_name = ? AND file_path = ?", (repo_name, file_path))
    conn.execute("DELETE FROM code_fts WHERE repo_name = ? AND file_path = ?", (repo_name, file_path))
    conn.execute("DELETE FROM code_relations WHERE repo_name = ? AND caller_file_path = ?", (repo_name, file_path))
    conn.commit()

    return count


# ── 向量搜索 ─────────────────────────────────────────────────────

def search_vector(
    query_vector: list[float],
    top_k: int = 10,
    repo_name: Optional[str] = None,
    language: Optional[str] = None,
    chunk_type: Optional[str] = None,
    file_path: Optional[str] = None,
) -> list[dict]:
    """向量搜索 (LanceDB cosine)"""
    table = get_table()

    query = table.search(query_vector).metric("cosine")

    # 构造过滤条件
    filters = []
    if repo_name:
        filters.append(f"repo_name = '{_esc(repo_name)}'")
    if language:
        filters.append(f"language = '{_esc(language)}'")
    if chunk_type:
        filters.append(f"chunk_type = '{_esc(chunk_type)}'")
    if file_path:
        filters.append(f"file_path LIKE '{_esc(file_path)}%'")

    if filters:
        query = query.where(" AND ".join(filters))

    results = query.limit(top_k).to_list()

    formatted = []
    for r in results:
        distance = r.get("_distance", 0)
        score = cosine_distance_to_similarity(distance)

        item = {
            "id": r["id"],
            "repo_name": r["repo_name"],
            "project_type": r.get("project_type", ""),
            "file_path": r["file_path"],
            "file_name": r.get("file_name", ""),
            "language": r["language"],
            "chunk_type": r["chunk_type"],
            "symbol_name": r.get("symbol_name", ""),
            "content": r["content"],
            "line_start": r.get("line_start", 0),
            "line_end": r.get("line_end", 0),
            "score": score,
            "source": "vector",
        }

        try:
            item["metadata"] = json.loads(r.get("metadata", "{}"))
        except (json.JSONDecodeError, TypeError):
            item["metadata"] = {}

        formatted.append(item)

    return formatted


# ── 关键词搜索 ───────────────────────────────────────────────────

def search_keyword(
    query: str,
    top_k: int = 10,
    repo_name: Optional[str] = None,
    language: Optional[str] = None,
    chunk_type: Optional[str] = None,
    file_path: Optional[str] = None,
    symbol_name: Optional[str] = None,
) -> list[dict]:
    """关键词搜索 (SQLite FTS5)"""
    conn = get_sqlite()

    # 构造 FTS5 查询 — 中文查询先分词再构造短语查询
    fts_query = segment_query_for_match(query.strip())
    if not fts_query:
        return []

    # 如果有 symbol_name 精确匹配, 优先搜 symbol_name
    if symbol_name:
        fts_query = f'"{symbol_name}"'

    sql = """
        SELECT fts.chunk_id, fts.content, fts.symbol_name, fts.file_path, fts.language, fts.repo_name,
               rank
        FROM code_fts fts
        JOIN code_meta meta ON fts.chunk_id = meta.chunk_id
        WHERE code_fts MATCH ?
    """
    params: list = [fts_query]

    if repo_name:
        sql += " AND fts.repo_name = ?"
        params.append(repo_name)
    if language:
        sql += " AND fts.language = ?"
        params.append(language)
    if chunk_type:
        sql += " AND meta.chunk_type = ?"
        params.append(chunk_type)
    if file_path:
        sql += " AND fts.file_path LIKE ?"
        params.append(f"{file_path}%")

    sql += " ORDER BY rank LIMIT ?"
    params.append(top_k)

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        # FTS5 查询语法错误时降级为前缀搜索
        safe_query = fts_query.replace('"', '').replace("'", "")
        if not safe_query:
            return []
        sql = """
            SELECT fts.chunk_id, fts.content, fts.symbol_name, fts.file_path, fts.language, fts.repo_name,
                   rank
            FROM code_fts fts
            WHERE code_fts MATCH ?
            ORDER BY rank LIMIT ?
        """
        try:
            fb_params = [f'{safe_query}*']
            fb_sql = (
                "SELECT fts.chunk_id, fts.content, fts.symbol_name, fts.file_path, "
                "fts.language, fts.repo_name, rank "
                "FROM code_fts fts JOIN code_meta meta ON fts.chunk_id = meta.chunk_id "
                "WHERE code_fts MATCH ?"
            )
            if repo_name:
                fb_sql += " AND fts.repo_name = ?"; fb_params.append(repo_name)
            if language:
                fb_sql += " AND fts.language = ?"; fb_params.append(language)
            if chunk_type:
                fb_sql += " AND meta.chunk_type = ?"; fb_params.append(chunk_type)
            if file_path:
                fb_sql += " AND fts.file_path LIKE ?"; fb_params.append(f"{file_path}%")
            fb_sql += " ORDER BY rank LIMIT ?"; fb_params.append(top_k)
            rows = conn.execute(fb_sql, fb_params).fetchall()
        except sqlite3.OperationalError:
            return []

    # 从 code_meta 补充结构化字段
    formatted = []
    for row in rows:
        chunk_id, content, sym, fpath, lang, repo, rank = row

        # 读取 meta
        meta_row = conn.execute(
            "SELECT project_type, file_name, chunk_type, line_start, line_end FROM code_meta WHERE chunk_id = ?",
            (chunk_id,)
        ).fetchone()

        item = {
            "id": chunk_id,
            "repo_name": repo,
            "project_type": meta_row[0] if meta_row else "",
            "file_path": fpath,
            "file_name": meta_row[1] if meta_row else "",
            "language": lang,
            "chunk_type": meta_row[2] if meta_row else "",
            "symbol_name": sym or "",
            "content": content,
            "line_start": meta_row[3] if meta_row else 0,
            "line_end": meta_row[4] if meta_row else 0,
            "score": abs(rank),  # FTS5 rank 是负数, 越小越好
            "source": "keyword",
        }
        formatted.append(item)

    return formatted


# ── 符号名关键词搜索 ───────────────────────────────────────────────

def search_symbol_by_keywords(
    keywords: list[str],
    top_k: int = 10,
    repo_name: Optional[str] = None,
    language: Optional[str] = None,
    chunk_type: Optional[str] = None,
    file_path: Optional[str] = None,
    symbol_name: Optional[str] = None,
) -> list[dict]:
    """用英文关键词搜索 symbol_name 和 file_path 字段

    对每个关键词: symbol_name LIKE '%keyword%' OR file_path LIKE '%keyword%'
    多关键词命中越多的排越前（按命中数降序）。

    Args:
        keywords: 翻译后的英文关键词列表 ["login", "signin", "auth"]
        top_k: 最多返回条数
        repo_name, language, chunk_type: 可选过滤条件

    当前状态：已启用，作为 search_code(hybrid) 的第三路补充召回（权重 1.5x）。
             用于兜底 FTS5 驼峰拆分盲区——当 "viewcontroller" FTS5 零命中
             "GHMineViewController" 时，LIKE 子串匹配仍可召回。

    【后续优化方向 — 按优先级】
    TODO[1] 将 LIKE 全表扫描改为 FTS5 列查询：
            code_fts 表已有 symbol_name 列，但 unicode61 tokenizer 下
            "GHMineViewController" 是单 token，MATCH 'symbol_name:viewcontroller' 同样命中不了。
            需要先给 symbol_name 列也做驼峰拆分写入（方案一已给 display_text 加驼峰头，
            但 symbol_name 列本身仍是原始驼峰），再配合 MATCH 列查询。
            性能：0.2ms vs 当前 LIKE 10ms，快 50 倍。
    TODO[2] 建 trigram tokenizer 辅助 FTS5 表：
            CREATE VIRTUAL TABLE code_fts_sym USING fts5(symbol_name, tokenize='trigram');
            trigram 原生支持任意子串匹配，无需驼峰拆分即可命中。
            代价：多一张表 + 写入时多一次 INSERT。
    TODO[3] 当前 6.2 万行 code_meta 下 LIKE 全表扫描 ~10ms/关键词，
            多关键词循环累加 ~50ms。当前调用链为同步（search_code → search_symbol_by_keywords），
            但实测在现数据量下可接受。数据量超 50 万行后（预估 ~100ms/关键词），
            必须切到 TODO[1] 或 TODO[2]。
    """
    if not keywords:
        return []

    conn = get_sqlite()
    results = {}  # chunk_id → {item, hit_count}

    for kw in keywords:
        kw = kw.strip()
        if not kw or len(kw) < 2:
            continue

        sql = """
            SELECT chunk_id, repo_name, project_type, file_path, file_name,
                   language, chunk_type, symbol_name, line_start, line_end
            FROM code_meta
            WHERE (symbol_name LIKE ? OR file_path LIKE ?)
        """
        escaped_kw = kw.replace("%", "\\%").replace("_", "\\_")
        like_pattern = f"%{escaped_kw}%"
        glob_prefix_cap = f"??{kw.capitalize()}*"
        glob_prefix_low = f"??{kw.lower()}*"
        glob_cap = f"*{kw.capitalize()}*"
        glob_low = f"*{kw.lower()}*"
        params: list = [like_pattern, like_pattern]

        if repo_name:
            sql += " AND repo_name = ?"
            params.append(repo_name)
        if language:
            sql += " AND language = ?"
            params.append(language)
        if chunk_type:
            sql += " AND chunk_type = ?"
            params.append(chunk_type)
        if file_path:
            # 前缀匹配，与 search_vector/search_keyword 的 file_path 过滤语义一致
            sql += " AND file_path LIKE ?"
            params.append(f"{file_path}%")
        if symbol_name:
            # 前缀匹配——caller 传入的是符号名过滤条件，通常用于缩小范围
            sql += " AND symbol_name LIKE ?"
            params.append(f"{symbol_name}%")

        sql += """
            GROUP BY file_path, symbol_name
            ORDER BY (
                CASE 
                    WHEN symbol_name GLOB ? THEN 1
                    WHEN symbol_name GLOB ? THEN 1.5
                    WHEN symbol_name GLOB ? THEN 2
                    WHEN symbol_name GLOB ? THEN 3
                    WHEN file_path GLOB ? THEN 4
                    WHEN file_path GLOB ? THEN 5
                    ELSE 6
                END
            ) ASC, (
                CASE 
                    WHEN symbol_name LIKE '%ViewController%' OR symbol_name LIKE '%VC%' THEN 1
                    ELSE 2
                END
            ) ASC, length(symbol_name) ASC
            LIMIT 100
        """
        params.extend([glob_prefix_cap, glob_prefix_low, glob_cap, glob_low, glob_cap, glob_low])

        try:
            rows = conn.execute(sql, params).fetchall()
        except Exception as e:
            print(f"[code_db] search_symbol_by_keywords 查询失败 (kw={kw}): {e}")
            continue

        for row in rows:
            cid = row[0]
            if cid not in results:
                results[cid] = {
                    "id": cid,
                    "repo_name": row[1],
                    "project_type": row[2],
                    "file_path": row[3],
                    "file_name": row[4],
                    "language": row[5],
                    "chunk_type": row[6],
                    "symbol_name": row[7],
                    "line_start": row[8],
                    "line_end": row[9],
                    "hit_count": 0,
                    "matched_keywords": [],
                    "source": "symbol",
                }
            results[cid]["hit_count"] += 1
            results[cid]["matched_keywords"].append(kw)

    # 按命中数降序排序
    sorted_items = sorted(results.values(), key=lambda x: x["hit_count"], reverse=True)

    # 截断并补 content
    final = []
    for item in sorted_items[:top_k]:
        item["score"] = item["hit_count"] / max(len(keywords), 1)
        item["match_reason"] = f"符号匹配: {', '.join(item['matched_keywords'])}"
        # 补 content（从 LanceDB 或 FTS5 读）
        try:
            fts_row = conn.execute(
                "SELECT content FROM code_fts WHERE chunk_id = ?", (item["id"],)
            ).fetchone()
            item["content"] = fts_row[0] if fts_row else ""
        except Exception:
            item["content"] = ""
        final.append(item)

    return final


# ── 统计 ─────────────────────────────────────────────────────────

def get_stats(repo_name: str | None = None) -> dict:
    """获取代码知识库统计 (用 SQLite 避免全量加载 LanceDB)

    Args:
        repo_name: 可选，传入时只统计该仓库的数据
    """
    conn = get_sqlite()
    try:
        where = "WHERE repo_name = ?" if repo_name else ""
        params = (repo_name,) if repo_name else ()

        total = conn.execute(f"SELECT COUNT(*) FROM code_meta {where}", params).fetchone()[0]
        if total == 0:
            return {"total_chunks": 0, "total_repos": 0, "by_language": {}, "by_chunk_type": {}, "by_repo": {}}

        by_lang = dict(conn.execute(f"SELECT language, COUNT(*) FROM code_meta {where} GROUP BY language", params).fetchall())
        by_type = dict(conn.execute(f"SELECT chunk_type, COUNT(*) FROM code_meta {where} GROUP BY chunk_type", params).fetchall())
        by_repo = dict(conn.execute(f"SELECT repo_name, COUNT(*) FROM code_meta {where} GROUP BY repo_name", params).fetchall())

        return {
            "total_chunks": total,
            "total_repos": len(by_repo),
            "by_language": by_lang,
            "by_chunk_type": by_type,
            "by_repo": by_repo,
        }
    except Exception:
        return {"total_chunks": 0, "total_repos": 0, "by_language": {}, "by_chunk_type": {}, "by_repo": {}}


def get_storage_stats() -> dict:
    """获取代码知识库存储占用统计"""
    import os
    
    def get_dir_size(path):
        """获取目录大小（字节）"""
        total = 0
        try:
            with os.scandir(path) as it:
                for entry in it:
                    if entry.is_file():
                        total += entry.stat().st_size
                    elif entry.is_dir():
                        total += get_dir_size(entry.path)
        except (OSError, PermissionError):
            pass
        return total
    
    def get_file_size(path):
        """获取文件大小（字节）"""
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    
    def format_size(size_bytes):
        """格式化文件大小"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
    
    # 数据目录路径
    data_dir = os.path.join(PROJECT_ROOT, "data")
    config_dir = os.path.join(PROJECT_ROOT, "config")
    
    # 各个文件/目录的大小
    storage_info = {
        "code_lancedb": {
            "path": LANCEDB_PATH,
            "size_bytes": get_dir_size(LANCEDB_PATH),
            "size_formatted": format_size(get_dir_size(LANCEDB_PATH)),
            "description": "代码向量数据库 (LanceDB)"
        },
        "code_index_db": {
            "path": SQLITE_PATH,
            "size_bytes": get_file_size(SQLITE_PATH),
            "size_formatted": format_size(get_file_size(SQLITE_PATH)),
            "description": "代码索引 (SQLite FTS5)"
        },
        "code_repos_json": {
            "path": os.path.join(config_dir, "code_repos.json"),
            "size_bytes": get_file_size(os.path.join(config_dir, "code_repos.json")),
            "size_formatted": format_size(get_file_size(os.path.join(config_dir, "code_repos.json"))),
            "description": "仓库配置 (JSON)"
        },
        "code_skip_rules_json": {
            "path": os.path.join(config_dir, "code_skip_rules.json"),
            "size_bytes": get_file_size(os.path.join(config_dir, "code_skip_rules.json")),
            "size_formatted": format_size(get_file_size(os.path.join(config_dir, "code_skip_rules.json"))),
            "description": "跳过规则 (JSON)"
        },
        "code_agent_config_json": {
            "path": os.path.join(config_dir, "code_agent_config.json"),
            "size_bytes": get_file_size(os.path.join(config_dir, "code_agent_config.json")),
            "size_formatted": format_size(get_file_size(os.path.join(config_dir, "code_agent_config.json"))),
            "description": "Agent 配置 (JSON)"
        },
        "translation_cache_json": {
            "path": os.path.join(config_dir, "translation_cache.json"),
            "size_bytes": get_file_size(os.path.join(config_dir, "translation_cache.json")),
            "size_formatted": format_size(get_file_size(os.path.join(config_dir, "translation_cache.json"))),
            "description": "翻译缓存 (JSON)"
        },
        "translation_dict_json": {
            "path": os.path.join(config_dir, "translation_dict.json"),
            "size_bytes": get_file_size(os.path.join(config_dir, "translation_dict.json")),
            "size_formatted": format_size(get_file_size(os.path.join(config_dir, "translation_dict.json"))),
            "description": "翻译词典 (JSON)"
        }
    }
    
    # 计算总大小
    total_size = sum(item["size_bytes"] for item in storage_info.values())
    
    return {
        "storage": storage_info,
        "total_size_bytes": total_size,
        "total_size_formatted": format_size(total_size),
        "data_directory": data_dir
    }


def get_chunks_by_file(repo_name: str, file_path: str) -> list[dict]:
    """获取指定文件的所有 chunks（用 SQLite 查询，避免 to_pandas 全表加载）"""
    conn = get_sqlite()
    rows = conn.execute(
        "SELECT chunk_id, chunk_type, symbol_name, line_start, line_end "
        "FROM code_meta WHERE repo_name = ? AND file_path = ? "
        "ORDER BY line_start",
        (repo_name, file_path)
    ).fetchall()

    if not rows:
        return []

    result = []
    for chunk_id, chunk_type, sym, lstart, lend in rows:
        # content 从 FTS5 索引读
        fts_row = conn.execute(
            "SELECT content FROM code_fts WHERE chunk_id = ?", (chunk_id,)
        ).fetchone()
        result.append({
            "id": chunk_id,
            "content": fts_row[0] if fts_row else "",
            "chunk_type": chunk_type,
            "symbol_name": sym or "",
            "line_start": lstart or 0,
            "line_end": lend or 0,
            "metadata": {},
        })
    return result


def resolve_file_by_name(repo_name: str, file_name: str) -> list[dict]:
    """按 file_name 找文件（v2.1 起替代 get_chunks_by_file 的 file_path 入口）

    Returns:
        列表（多匹配也全部返回），每项含 file_path / file_name / chunk_count。
        调用方按业务需求决定：唯一命中直接取内容，多匹配返回给 AI 让它挑。
    """
    conn = get_sqlite()
    rows = conn.execute(
        "SELECT file_path, file_name, COUNT(*) AS cnt "
        "FROM code_meta WHERE repo_name = ? AND file_name = ? "
        "GROUP BY file_path, file_name "
        "ORDER BY cnt DESC",
        (repo_name, file_name)
    ).fetchall()
    return [
        {"file_path": r[0], "file_name": r[1], "chunk_count": r[2]}
        for r in rows
    ]


# ── FTS5 中文分词迁移 ──────────────────────────────────────────────

def migrate_fts_chinese(repo_name: Optional[str] = None) -> dict:
    """一次性迁移：对已有 FTS5 索引的中文内容进行分词重建。

    读取所有 (或指定仓库) 的 FTS5 行，用 jieba 分词后重新插入。
    FTS5 虚拟表不支持 UPDATE content，所以用 DELETE + INSERT。

    Args:
        repo_name: 可选，仅迁移指定仓库

    Returns:
        {"total": int, "updated": int}
    """
    conn = get_sqlite()

    if repo_name:
        rows = conn.execute(
            "SELECT chunk_id, content, symbol_name, file_path, language, repo_name "
            "FROM code_fts WHERE repo_name = ?",
            (repo_name,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT chunk_id, content, symbol_name, file_path, language, repo_name FROM code_fts"
        ).fetchall()

    updated = 0
    for row in rows:
        chunk_id, content, sym, fpath, lang, repo = row
        segmented = segment_for_fts(content) if content else ""
        if segmented != content:
            conn.execute("DELETE FROM code_fts WHERE chunk_id = ?", (chunk_id,))
            conn.execute(
                "INSERT INTO code_fts (chunk_id, content, symbol_name, file_path, language, repo_name) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (chunk_id, segmented, sym, fpath, lang, repo)
            )
            updated += 1

    conn.commit()
    return {"total": len(rows), "updated": updated}


# ── 清空全部 ─────────────────────────────────────────────────────

def clear_all() -> int:
    """清空所有代码索引数据 (LanceDB + SQLite), 返回删除数量"""
    global _table

    # SQLite count + 清空
    conn = get_sqlite()
    total = conn.execute("SELECT COUNT(*) FROM code_meta").fetchone()[0]
    conn.execute("DELETE FROM code_fts")
    conn.execute("DELETE FROM code_meta")
    conn.execute("DELETE FROM code_relations")
    conn.commit()

    # LanceDB: 删除并重建表
    try:
        db = get_db()
        db.drop_table(TABLE_NAME)
        _table = None  # 重置单例
    except Exception:
        pass

    return total


# ── 调用关系查询 ─────────────────────────────────────────────────

def get_callees(chunk_id: str) -> list[dict]:
    """查询某个 chunk 调用了哪些符号

    Returns:
        [{"callee_name": str, "callee_line": int, "caller_symbol_name": str, "caller_file_path": str}, ...]
    """
    conn = get_sqlite()
    rows = conn.execute(
        "SELECT DISTINCT callee_name, callee_line, caller_symbol_name, caller_file_path "
        "FROM code_relations WHERE caller_chunk_id = ? ORDER BY callee_line",
        (chunk_id,)
    ).fetchall()
    return [
        {"callee_name": r[0], "callee_line": r[1],
         "caller_symbol_name": r[2], "caller_file_path": r[3]}
        for r in rows
    ]


def find_callers(symbol_name: str, repo_name: str = "", top_n: int = 30) -> list[dict]:
    """反向查找：谁调用了指定符号

    Args:
        symbol_name: 被调用的符号名
        repo_name: 可选，限制仓库
        top_n: 最多返回条数

    Returns:
        [{"caller_chunk_id": str, "caller_symbol_name": str, "caller_file_path": str, "callee_line": int}, ...]
    """
    conn = get_sqlite()
    if repo_name:
        rows = conn.execute(
            "SELECT DISTINCT caller_chunk_id, caller_symbol_name, caller_file_path, callee_line "
            "FROM code_relations WHERE callee_name = ? AND repo_name = ? "
            "ORDER BY callee_line LIMIT ?",
            (symbol_name, repo_name, top_n)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT DISTINCT caller_chunk_id, caller_symbol_name, caller_file_path, callee_line "
            "FROM code_relations WHERE callee_name = ? "
            "ORDER BY callee_line LIMIT ?",
            (symbol_name, top_n)
        ).fetchall()
    return [
        {"caller_chunk_id": r[0], "caller_symbol_name": r[1],
         "caller_file_path": r[2], "callee_line": r[3]}
        for r in rows
    ]


def trace_chain(
    symbol_name: str,
    repo_name: str = "",
    direction: str = "both",
    depth: int = 2,
) -> dict:
    """多跳追踪调用链

    Args:
        symbol_name: 起始符号名
        repo_name: 仓库名过滤
        direction: "callers"（谁调我）/ "callees"（我调谁）/ "both"（双向）
        depth: 追踪跳数 (1-3)

    Returns:
        {"symbol": str, "callers": [...], "callees": [...], "chain": [...]}
        其中 chain 包含每跳的节点和边
    """
    depth = max(1, min(depth, 3))
    conn = get_sqlite()

    visited = set()
    nodes = {}     # symbol_name → {"symbol": str, "file": str, "chunk_id": str}
    edges = []     # [{"from": str, "to": str, "line": int}]

    # BFS / 受限深度遍历
    from collections import deque

    # 初始化: 找到起始符号对应的 chunk
    base_filter = "AND repo_name = ?" if repo_name else ""
    base_params = [symbol_name]
    if repo_name:
        base_params.append(repo_name)

    start_rows = conn.execute(
        f"SELECT DISTINCT caller_chunk_id, caller_symbol_name, caller_file_path "
        f"FROM code_relations WHERE callee_name = ? {base_filter} LIMIT 1",
        base_params
    ).fetchall()

    if not start_rows:
        # 也许是被调用方，试试作为 caller 搜
        start_rows = conn.execute(
            f"SELECT DISTINCT caller_chunk_id, caller_symbol_name, caller_file_path "
            f"FROM code_relations WHERE caller_symbol_name = ? {base_filter} LIMIT 1",
            base_params
        ).fetchall()

    if not start_rows:
        return {"symbol": symbol_name, "callers": [], "callees": [], "chain": {"nodes": [], "edges": []}}

    # 用第一个匹配的 chunk 作为起始
    start_chunk_id = start_rows[0][0]
    start_symbol = start_rows[0][1] or symbol_name
    start_file = start_rows[0][2] or ""

    nodes[symbol_name] = {"symbol": start_symbol, "file": start_file, "chunk_id": start_chunk_id}

    # BFS 双向遍历
    queue = deque()
    queue.append((symbol_name, 0))
    visited.add(symbol_name)

    while queue:
        current, current_depth = queue.popleft()
        if current_depth >= depth:
            continue

        # ── 查 callees (我调谁) ──
        if direction in ("callees", "both"):
            current_cid = nodes[current].get("chunk_id", "")
            if current_cid:
                callee_rows = conn.execute(
                    "SELECT DISTINCT callee_name, callee_line FROM code_relations "
                    "WHERE caller_chunk_id = ? LIMIT 30",
                    (current_cid,)
                ).fetchall()
                for row in callee_rows:
                    callee, line = row
                    if callee not in nodes:
                        # 回查 callee 的 chunk_id（在 code_meta 或 code_relations 中找）
                        callee_cid = ""
                        callee_file = ""
                        cid_rows = conn.execute(
                            "SELECT chunk_id, file_path FROM code_meta "
                            "WHERE symbol_name = ? AND repo_name = ? LIMIT 1",
                            (callee, nodes[current].get("repo_name", repo_name or ""))
                        ).fetchall()
                        if not cid_rows and repo_name:
                            cid_rows = conn.execute(
                                "SELECT chunk_id, file_path FROM code_meta "
                                "WHERE symbol_name = ? LIMIT 1",
                                (callee,)
                            ).fetchall()
                        if cid_rows:
                            callee_cid = cid_rows[0][0]
                            callee_file = cid_rows[0][1] or ""
                        nodes[callee] = {"symbol": callee, "file": callee_file, "chunk_id": callee_cid}
                    edges.append({"from": current, "to": callee, "line": line, "relation": "calls"})
                    if callee not in visited:
                        visited.add(callee)
                        queue.append((callee, current_depth + 1))

        # ── 查 callers (谁调我) ──
        if direction in ("callers", "both"):
            caller_rows = conn.execute(
                "SELECT DISTINCT caller_symbol_name, callee_line, caller_chunk_id, caller_file_path "
                "FROM code_relations WHERE callee_name = ? "
                + (f"AND repo_name = ? " if repo_name else "") + "LIMIT 15",
                [current] + ([repo_name] if repo_name else [])
            ).fetchall()
            for row in caller_rows:
                caller_sym, line, cid, cfile = row
                caller_name = caller_sym or f"_caller_{cid[-8:]}"
                if caller_name not in nodes:
                    nodes[caller_name] = {"symbol": caller_name, "file": cfile or "", "chunk_id": cid}
                edges.append({"from": caller_name, "to": current, "line": line, "relation": "called_by"})
                if caller_name not in visited:
                    visited.add(caller_name)
                    queue.append((caller_name, current_depth + 1))

    # 整理结果
    callers_list = [e for e in edges if e["relation"] == "called_by" and e["to"] == symbol_name]
    callees_list = [e for e in edges if e["relation"] == "calls" and e["from"] == symbol_name]

    return {
        "symbol": symbol_name,
        "depth": depth,
        "direction": direction,
        "direct_callers": [
            {"symbol": e["from"], "file": nodes.get(e["from"], {}).get("file", ""), "line": e["line"]}
            for e in callers_list
        ],
        "direct_callees": [
            {"symbol": e["to"], "line": e["line"]}
            for e in callees_list
        ],
        "chain": {
            "nodes": [{"symbol": k, "file": v["file"], "chunk_id": v["chunk_id"]} for k, v in nodes.items()],
            "edges": edges,
        },
    }


# ── 继承链追踪 ──────────────────────────────────────────────────────

def trace_hierarchy(
    symbol_name: str,
    repo_name: str = "",
    direction: str = "both",  # parents / children / both
    depth: int = 3,
) -> dict:
    """追踪类/接口/协议的继承链（relation_type='inherit'）

    双向 BFS：
    - parents：找该符号继承的所有父类（沿 relation_type='inherit' 边反向）
    - children：找继承该符号的所有子类（沿 relation_type='inherit' 边正向）

    Returns:
        {
            "symbol": str,
            "parents": [{"symbol": "Parent", "file": ..., "line": N}, ...],
            "children": [...],
            "chain": {"nodes": [...], "edges": [{"from": "Sub", "to": "Parent", "relation": "inherits"}]},
            "depth": int,
            "direction": str,
        }
    """
    conn = get_sqlite()
    repo_filter = "AND repo_name = ?" if repo_name else ""
    repo_params = [repo_name] if repo_name else []

    def _query_one_hop(current: str, want_parents: bool) -> list[dict]:
        """查一阶父类（callee_name 匹配）或子类（caller_symbol_name 匹配）"""
        if want_parents:
            # 找 current 继承的所有父类：current 是 caller，callee 是父类
            rows = conn.execute(
                f"SELECT DISTINCT caller_symbol_name, caller_chunk_id, caller_file_path, "
                f"callee_name, callee_line "
                f"FROM code_relations "
                f"WHERE caller_symbol_name = ? AND relation_type = 'inherit' "
                f"{repo_filter} LIMIT 30",
                [current] + repo_params
            ).fetchall()
            return [
                {"symbol": r[3], "chunk_id": "", "file": "", "line": r[4] or 0,
                 "via": r[0], "via_chunk_id": r[1] or "", "via_file": r[2] or ""}
                for r in rows
            ]
        else:
            # 找继承 current 的所有子类：current 是 callee，caller 是子类
            rows = conn.execute(
                f"SELECT DISTINCT caller_symbol_name, caller_chunk_id, caller_file_path, "
                f"callee_name, callee_line "
                f"FROM code_relations "
                f"WHERE callee_name = ? AND relation_type = 'inherit' "
                f"{repo_filter} LIMIT 30",
                [current] + repo_params
            ).fetchall()
            return [
                {"symbol": r[0] or "", "chunk_id": r[1] or "", "file": r[2] or "", "line": r[4] or 0,
                 "via": r[3], "via_chunk_id": "", "via_file": ""}
                for r in rows
            ]

    # BFS 双向遍历
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    visited = {symbol_name}
    queue = [(symbol_name, 0)]

    # 起始符号的 chunk/file（从 code_meta 反查）
    start_meta = conn.execute(
        f"SELECT chunk_id, file_path FROM code_meta WHERE symbol_name = ? {repo_filter} LIMIT 1",
        [symbol_name] + repo_params
    ).fetchone()
    if start_meta:
        nodes[symbol_name] = {"symbol": symbol_name, "chunk_id": start_meta[0], "file": start_meta[1]}
    else:
        nodes[symbol_name] = {"symbol": symbol_name, "chunk_id": "", "file": ""}

    parents_collected: list[dict] = []
    children_collected: list[dict] = []

    from collections import deque as _deque
    bfs = _deque([(symbol_name, 0)])

    while bfs:
        current, d = bfs.popleft()
        if d >= depth:
            continue
        # parents
        if direction in ("parents", "both"):
            for hop in _query_one_hop(current, want_parents=True):
                p_sym = hop["symbol"]
                if p_sym not in visited:
                    visited.add(p_sym)
                    # 父类的 file/chunk 也要查
                    p_meta = conn.execute(
                        f"SELECT chunk_id, file_path FROM code_meta WHERE symbol_name = ? {repo_filter} LIMIT 1",
                        [p_sym] + repo_params
                    ).fetchone()
                    nodes[p_sym] = {"symbol": p_sym, "chunk_id": p_meta[0] if p_meta else "",
                                    "file": p_meta[1] if p_meta else ""}
                    edges.append({"from": current, "to": p_sym, "line": hop["line"], "relation": "inherits"})
                    parents_collected.append({"symbol": p_sym, "file": nodes[p_sym]["file"],
                                               "line": hop["line"], "via": current})
                    bfs.append((p_sym, d + 1))
        # children
        if direction in ("children", "both"):
            for hop in _query_one_hop(current, want_parents=False):
                c_sym = hop["symbol"]
                if c_sym and c_sym not in visited:
                    visited.add(c_sym)
                    nodes[c_sym] = {"symbol": c_sym, "chunk_id": hop["chunk_id"], "file": hop["file"]}
                    edges.append({"from": c_sym, "to": current, "line": hop["line"], "relation": "inherits"})
                    children_collected.append({"symbol": c_sym, "file": hop["file"],
                                                "line": hop["line"], "via": current})
                    bfs.append((c_sym, d + 1))

    return {
        "symbol": symbol_name,
        "depth": depth,
        "direction": direction,
        "parents": parents_collected,
        "children": children_collected,
        "chain": {
            "nodes": [{"symbol": k, "file": v["file"], "chunk_id": v["chunk_id"]} for k, v in nodes.items()],
            "edges": edges,
        },
    }
