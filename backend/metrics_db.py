"""性能指标数据库 - SQLite 存储 step 级原始耗时记录与基线快照"""

import sqlite3
import os
import json
from datetime import datetime, timedelta
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "metrics.db")


def get_connection():
    """获取数据库连接"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化指标数据库"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL,
            operation_type TEXT NOT NULL,
            step_name TEXT,
            duration_ms REAL NOT NULL,
            status TEXT NOT NULL,
            extra TEXT,
            created_at TEXT NOT NULL
        )
    ''')

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_op_type_time ON operations(operation_type, created_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_op_request ON operations(request_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_op_step ON operations(operation_type, step_name)')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS baselines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL,
            config TEXT NOT NULL,
            summary TEXT NOT NULL,
            notes TEXT,
            created_at TEXT NOT NULL
        )
    ''')

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_baseline_label ON baselines(label, created_at)')

    conn.commit()
    conn.close()


def record_operation(
    request_id: str,
    operation_type: str,
    duration_ms: float,
    status: str = "completed",
    step_name: Optional[str] = None,
    extra: Optional[dict] = None,
):
    """写入一条操作记录"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO operations (request_id, operation_type, step_name, duration_ms, status, extra, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        request_id,
        operation_type,
        step_name,
        duration_ms,
        status,
        json.dumps(extra, ensure_ascii=False) if extra else None,
        datetime.now().isoformat(),
    ))

    conn.commit()
    conn.close()


def record_operations_batch(records: list[dict]):
    """批量写入操作记录（一次请求的所有 step 一起落库，性能更优）

    每条 record: {request_id, operation_type, step_name, duration_ms, status, extra}
    """
    if not records:
        return

    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    rows = [
        (
            r["request_id"],
            r["operation_type"],
            r.get("step_name"),
            r["duration_ms"],
            r.get("status", "completed"),
            json.dumps(r["extra"], ensure_ascii=False) if r.get("extra") else None,
            now,
        )
        for r in records
    ]

    cursor.executemany('''
        INSERT INTO operations (request_id, operation_type, step_name, duration_ms, status, extra, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', rows)

    conn.commit()
    conn.close()


def get_summary(operation_type: str, step_name: Optional[str] = None, since_days: Optional[int] = None) -> dict:
    """获取某类操作的聚合统计：count / avg / P50 / P95 / max / min

    operation_type: 'search' / 'insert_file' / 'insert_chunk' / 'chat' / ...
    step_name: 可选，进一步限定到某个 step
    since_days: 可选，只统计最近 N 天
    """
    conn = get_connection()
    cursor = conn.cursor()

    sql = "SELECT duration_ms FROM operations WHERE operation_type = ? AND status = 'completed'"
    params: list = [operation_type]

    if step_name:
        sql += " AND step_name = ?"
        params.append(step_name)
    else:
        # 不指定 step_name 时，只统计「请求级总耗时」（step_name IS NULL 表示父级）
        sql += " AND step_name IS NULL"

    if since_days:
        cutoff = (datetime.now() - timedelta(days=since_days)).isoformat()
        sql += " AND created_at >= ?"
        params.append(cutoff)

    sql += " ORDER BY duration_ms"

    cursor.execute(sql, params)
    durations = [row[0] for row in cursor.fetchall()]
    conn.close()

    n = len(durations)
    if n == 0:
        return {"count": 0, "avg_ms": 0, "p50_ms": 0, "p95_ms": 0, "max_ms": 0, "min_ms": 0}

    return {
        "count": n,
        "avg_ms": round(sum(durations) / n, 2),
        "p50_ms": round(durations[int(n * 0.50)], 2),
        "p95_ms": round(durations[min(int(n * 0.95), n - 1)], 2),
        "max_ms": round(durations[-1], 2),
        "min_ms": round(durations[0], 2),
    }


def get_trend(operation_type: str, days: int = 7) -> list[dict]:
    """按天聚合趋势数据"""
    conn = get_connection()
    cursor = conn.cursor()

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    cursor.execute('''
        SELECT
            DATE(created_at) AS day,
            COUNT(*) AS count,
            AVG(duration_ms) AS avg_ms,
            MAX(duration_ms) AS max_ms
        FROM operations
        WHERE operation_type = ?
          AND status = 'completed'
          AND step_name IS NULL
          AND created_at >= ?
        GROUP BY DATE(created_at)
        ORDER BY day
    ''', (operation_type, cutoff))

    rows = [
        {
            "day": r["day"],
            "count": r["count"],
            "avg_ms": round(r["avg_ms"], 2),
            "max_ms": round(r["max_ms"], 2),
        }
        for r in cursor.fetchall()
    ]
    conn.close()
    return rows


def get_step_breakdown(operation_type: str, since_days: Optional[int] = None) -> list[dict]:
    """获取某类操作各 step 的平均耗时占比，定位瓶颈"""
    conn = get_connection()
    cursor = conn.cursor()

    sql = '''
        SELECT
            step_name,
            COUNT(*) AS count,
            AVG(duration_ms) AS avg_ms,
            MAX(duration_ms) AS max_ms
        FROM operations
        WHERE operation_type = ?
          AND status = 'completed'
          AND step_name IS NOT NULL
    '''
    params: list = [operation_type]

    if since_days:
        cutoff = (datetime.now() - timedelta(days=since_days)).isoformat()
        sql += " AND created_at >= ?"
        params.append(cutoff)

    sql += " GROUP BY step_name ORDER BY avg_ms DESC"

    cursor.execute(sql, params)
    rows = [
        {
            "step_name": r["step_name"],
            "count": r["count"],
            "avg_ms": round(r["avg_ms"], 2),
            "max_ms": round(r["max_ms"], 2),
        }
        for r in cursor.fetchall()
    ]
    conn.close()
    return rows


def get_insert_throughput() -> dict:
    """两种粒度的插入耗时：avg_per_file_ms = 单文件平均；avg_per_chunk_ms = 总耗时/总 chunk 数"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT duration_ms, extra
        FROM operations
        WHERE operation_type IN ('insert_file', 'email_import')
          AND status = 'completed'
          AND step_name IS NULL
    ''')

    rows = cursor.fetchall()
    conn.close()

    total_duration = 0.0
    total_chunks = 0
    file_durations: list[float] = []

    for r in rows:
        duration = r["duration_ms"]
        extra = json.loads(r["extra"]) if r["extra"] else {}
        chunk_count = extra.get("chunk_count", 0)

        if chunk_count > 0:
            total_duration += duration
            total_chunks += chunk_count
            file_durations.append(duration)

    return {
        "file_count": len(file_durations),
        "chunk_count": total_chunks,
        "avg_per_file_ms": round(sum(file_durations) / len(file_durations), 2) if file_durations else 0,
        "avg_per_chunk_ms": round(total_duration / total_chunks, 2) if total_chunks else 0,
    }


def get_disk_usage(path: str) -> int:
    """递归计算目录磁盘占用（字节）"""
    if not os.path.exists(path):
        return 0

    total = 0
    for dirpath, _, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def save_baseline(label: str, config: dict, summary: dict, notes: str = "") -> int:
    """保存基线快照"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO baselines (label, config, summary, notes, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (
        label,
        json.dumps(config, ensure_ascii=False),
        json.dumps(summary, ensure_ascii=False),
        notes,
        datetime.now().isoformat(),
    ))

    baseline_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return baseline_id


def list_baselines(limit: int = 50) -> list[dict]:
    """列出所有基线快照"""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT id, label, config, summary, notes, created_at
        FROM baselines
        ORDER BY created_at DESC
        LIMIT ?
    ''', (limit,))

    rows = [
        {
            "id": r["id"],
            "label": r["label"],
            "config": json.loads(r["config"]),
            "summary": json.loads(r["summary"]),
            "notes": r["notes"],
            "created_at": r["created_at"],
        }
        for r in cursor.fetchall()
    ]
    conn.close()
    return rows


init_db()
