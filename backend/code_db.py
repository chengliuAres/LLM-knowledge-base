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
    """获取 code_chunks 表 (不存在则创建)"""
    global _table
    if _table is None:
        db = get_db()
        try:
            _table = db.open_table(TABLE_NAME)
        except Exception:
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
                "line_start": 0,
                "line_end": 0,
                "vector": [0.0] * 384,
                "metadata": "{}",
            }]
            _table = db.create_table(TABLE_NAME, data=placeholder)
            _table.delete("id = '__placeholder__'")
    return _table


# ── SQLite FTS5 ──────────────────────────────────────────────────

def get_sqlite() -> sqlite3.Connection:
    """获取 SQLite 连接 (含 FTS5 表)"""
    os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)
    conn = sqlite3.connect(SQLITE_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    # FTS5 虚拟表
    conn.execute("""
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
    conn.execute("""
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_repo ON code_meta(repo_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_meta_lang ON code_meta(language)")

    conn.commit()
    return conn


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
            c["content"],
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
    conn.commit()


# ── 双删: 按仓库删除 ────────────────────────────────────────────

def delete_by_repo(repo_name: str) -> int:
    """删除指定仓库的所有 chunks, 返回删除数量"""
    # ── LanceDB 删除 ──
    table = get_table()
    try:
        df = table.to_pandas()
        count = len(df[df['repo_name'] == repo_name])
        if count > 0:
            table.delete(f"repo_name = '{repo_name}'")
    except Exception:
        count = 0

    # ── SQLite 删除 ──
    conn = get_sqlite()
    cur = conn.execute("DELETE FROM code_meta WHERE repo_name = ?", (repo_name,))
    meta_deleted = cur.rowcount
    # FTS5 不支持 WHERE 删除, 需要重建或用辅助表
    # 简单方案: 删除匹配的 FTS 行
    conn.execute(
        "DELETE FROM code_fts WHERE chunk_id IN (SELECT chunk_id FROM code_meta WHERE repo_name = ?)",
        (repo_name,)
    )
    # 上面已经删了 meta, 这里用 chunk_id 前缀匹配
    conn.execute("DELETE FROM code_fts WHERE repo_name = ?", (repo_name,))
    conn.commit()

    return max(count, meta_deleted)


def delete_by_file(repo_name: str, file_path: str) -> int:
    """删除指定文件的所有 chunks"""
    table = get_table()
    try:
        df = table.to_pandas()
        mask = (df['repo_name'] == repo_name) & (df['file_path'] == file_path)
        count = len(df[mask])
        if count > 0:
            table.delete(f"repo_name = '{repo_name}' AND file_path = '{file_path}'")
    except Exception:
        count = 0

    conn = get_sqlite()
    conn.execute("DELETE FROM code_meta WHERE repo_name = ? AND file_path = ?", (repo_name, file_path))
    conn.execute("DELETE FROM code_fts WHERE repo_name = ? AND file_path = ?", (repo_name, file_path))
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
        filters.append(f"repo_name = '{repo_name}'")
    if language:
        filters.append(f"language = '{language}'")
    if chunk_type:
        filters.append(f"chunk_type = '{chunk_type}'")
    if file_path:
        filters.append(f"file_path LIKE '{file_path}%'")

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

    # 构造 FTS5 查询
    fts_query = query.strip()
    if not fts_query:
        return []

    # 如果有 symbol_name 精确匹配, 优先搜 symbol_name
    if symbol_name:
        fts_query = f'"{symbol_name}"'

    sql = """
        SELECT fts.chunk_id, fts.content, fts.symbol_name, fts.file_path, fts.language, fts.repo_name,
               rank
        FROM code_fts fts
        WHERE code_fts MATCH ?
    """
    params: list = [fts_query]

    if repo_name:
        sql += " AND fts.repo_name = ?"
        params.append(repo_name)
    if language:
        sql += " AND fts.language = ?"
        params.append(language)

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
            rows = conn.execute(sql, [f'{safe_query}*', top_k]).fetchall()
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
    """获取代码知识库统计"""
    table = get_table()
    try:
        df = table.to_pandas()
    except Exception:
        return {"total_chunks": 0, "total_repos": 0, "by_language": {}, "by_chunk_type": {}, "by_repo": {}}

    if df.empty:
        return {"total_chunks": 0, "total_repos": 0, "by_language": {}, "by_chunk_type": {}, "by_repo": {}}

    return {
        "total_chunks": len(df),
        "total_repos": df["repo_name"].nunique(),
        "by_language": df.groupby("language").size().to_dict(),
        "by_chunk_type": df.groupby("chunk_type").size().to_dict(),
        "by_repo": df.groupby("repo_name").size().to_dict(),
    }


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
