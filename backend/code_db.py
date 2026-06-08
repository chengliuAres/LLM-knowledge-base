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

from code_embedder import get_code_dimension
from text_utils import segment_for_fts, segment_query_for_match

# ── 路径配置 ──────────────────────────────────────────────────────

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANCEDB_PATH = os.path.join(PROJECT_ROOT, "data", "code_lancedb")
SQLITE_PATH = os.path.join(PROJECT_ROOT, "data", "code_index.db")
TABLE_NAME = "code_chunks"

# ── LanceDB 单例 ─────────────────────────────────────────────────

_db = None
_table = None


def get_db() -> lancedb.DBConnection:
    """获取 LanceDB 连接"""
    global _db
    if _db is None:
        os.makedirs(LANCEDB_PATH, exist_ok=True)
        _db = lancedb.connect(LANCEDB_PATH)
    return _db


def get_table():
    """获取 code_chunks 表 (不存在则创建，维度不匹配则自动迁移)"""
    global _table
    if _table is None:
        db = get_db()
        dim = get_code_dimension()
        try:
            _table = db.open_table(TABLE_NAME)
            # 检查维度是否匹配
            schema = _table.schema
            for field in schema:
                if field.name == 'vector' and hasattr(field.type, 'list_size'):
                    existing_dim = field.type.list_size
                    if existing_dim != dim:
                        import uuid
                        backup_name = f"{TABLE_NAME}_{existing_dim}dim_backup"
                        print(f"[code_db] 向量维度不匹配: 现存={existing_dim}, 当前={dim}")
                        print(f"[code_db] 备份旧表为 {backup_name}，创建新表")
                        try:
                            db.drop_table(backup_name)
                        except Exception:
                            pass
                        try:
                            db.drop_table(TABLE_NAME)
                        except Exception:
                            pass
                        _table = None
                        raise FileNotFoundError("schema 已废弃，重建表")
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

    # 调用关系表 (call graph)
    _sqlite_conn.execute("""
        CREATE TABLE IF NOT EXISTS code_relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            caller_chunk_id TEXT NOT NULL,
            caller_symbol_name TEXT,
            caller_file_path TEXT,
            callee_name TEXT NOT NULL,
            callee_line INTEGER,
            repo_name TEXT NOT NULL
        )
    """)
    _sqlite_conn.execute("CREATE INDEX IF NOT EXISTS idx_rel_caller ON code_relations(caller_chunk_id)")
    _sqlite_conn.execute("CREATE INDEX IF NOT EXISTS idx_rel_callee ON code_relations(callee_name, repo_name)")
    _sqlite_conn.execute("CREATE INDEX IF NOT EXISTS idx_rel_repo ON code_relations(repo_name)")
    # 唯一约束: 同一 chunk 内同符号同行的调用只记录一次，支持 INSERT OR IGNORE 去重
    _sqlite_conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_rel_unique "
        "ON code_relations(caller_chunk_id, callee_name, callee_line, repo_name)"
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
    """
    if not chunks:
        return

    # ── LanceDB 写入 ──
    table = get_table()
    lancedb_records = []
    for c in chunks:
        meta = c.get("metadata", {})
        if isinstance(meta, dict):
            meta_str = json.dumps(meta, ensure_ascii=False)
        else:
            meta_str = str(meta)

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

    # ── SQLite 写入 ──
    conn = get_sqlite()
    fts_rows = []
    meta_rows = []
    for c in chunks:
        fts_rows.append((
            c["id"],
            segment_for_fts(c.get("display_text", c["content"])),  # 用 display_text 索引，与向量搜索对齐
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

    # ── 写入调用关系 ──
    rel_rows = []
    for c in chunks:
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
                    ))
    if rel_rows:
        conn.executemany(
            "INSERT OR IGNORE INTO code_relations "
            "(caller_chunk_id, caller_symbol_name, caller_file_path, callee_name, callee_line, repo_name) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rel_rows
        )

    conn.commit()


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
    """删除指定文件的所有 chunks"""
    table = get_table()
    try:
        df = table.to_pandas()
        mask = (df['repo_name'] == repo_name) & (df['file_path'] == file_path)
        count = len(df[mask])
        if count > 0:
            table.delete(f"repo_name = '{_esc(repo_name)}' AND file_path = '{_esc(file_path)}'")
    except Exception:
        count = 0

    conn = get_sqlite()
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


# ── 统计 ─────────────────────────────────────────────────────────

def get_stats() -> dict:
    """获取代码知识库统计 (用 SQLite 避免全量加载 LanceDB)"""
    conn = get_sqlite()
    try:
        total = conn.execute("SELECT COUNT(*) FROM code_meta").fetchone()[0]
        if total == 0:
            return {"total_chunks": 0, "total_repos": 0, "by_language": {}, "by_chunk_type": {}, "by_repo": {}}

        by_lang = dict(conn.execute("SELECT language, COUNT(*) FROM code_meta GROUP BY language").fetchall())
        by_type = dict(conn.execute("SELECT chunk_type, COUNT(*) FROM code_meta GROUP BY chunk_type").fetchall())
        by_repo = dict(conn.execute("SELECT repo_name, COUNT(*) FROM code_meta GROUP BY repo_name").fetchall())

        return {
            "total_chunks": total,
            "total_repos": len(by_repo),
            "by_language": by_lang,
            "by_chunk_type": by_type,
            "by_repo": by_repo,
        }
    except Exception:
        return {"total_chunks": 0, "total_repos": 0, "by_language": {}, "by_chunk_type": {}, "by_repo": {}}


def get_chunks_by_file(repo_name: str, file_path: str) -> list[dict]:
    """获取指定文件的所有 chunks (用于 code_file_context MCP tool)"""
    table = get_table()
    try:
        df = table.to_pandas()
        mask = (df["repo_name"] == repo_name) & (df["file_path"] == file_path)
        rows = df[mask]
        if rows.empty:
            return []
        result = []
        for _, r in rows.iterrows():
            try:
                meta = json.loads(r.get("metadata", "{}"))
            except (json.JSONDecodeError, TypeError):
                meta = {}
            result.append({
                "id": r["id"],
                "content": r["content"],
                "chunk_type": r["chunk_type"],
                "symbol_name": r.get("symbol_name", ""),
                "line_start": r.get("line_start", 0),
                "line_end": r.get("line_end", 0),
                "metadata": meta,
            })
        return sorted(result, key=lambda x: x["line_start"])
    except Exception:
        return []


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
