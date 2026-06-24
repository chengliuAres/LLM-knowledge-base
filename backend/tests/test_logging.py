"""日志系统测试 —— 5 个核心用例。"""

import logging
import os
import sys
import zipfile
from pathlib import Path

import pytest

# 把 backend/ 加入 sys.path，让 logging_setup / log_routes / main 可直接 import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# --- T1: configure_logging 幂等 ---


def test_configure_logging_is_idempotent():
    """重复调 configure_logging 不会重复加 handler。"""
    # 重置 root（避免前序测试污染）
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    from logging_setup import configure_logging

    configure_logging()
    n1 = len(root.handlers)
    configure_logging()
    configure_logging()
    n2 = len(root.handlers)
    assert n1 == n2 == 2, f"expected 2 handlers, got n1={n1} n2={n2}"


# --- T2: tail 接口读最后 N 行 ---


def test_tail_reads_last_n_lines(tmp_path, monkeypatch):
    """写 10 行 → tail(3) 返回最后 3 行。"""
    monkeypatch.setattr("log_routes.LOG_DIR", tmp_path)
    (tmp_path / "app.log").write_text("\n".join(f"line {i}" for i in range(10)) + "\n")

    from log_routes import tail

    result = tail(lines=3)
    assert result["file"] == "app.log"
    assert result["total_bytes"] > 0
    assert result["lines"] == ["line 7", "line 8", "line 9"]


def test_tail_returns_empty_when_file_missing(tmp_path, monkeypatch):
    """首次启动 app.log 不存在 → 返回空 list，不报错。"""
    monkeypatch.setattr("log_routes.LOG_DIR", tmp_path)

    from log_routes import tail

    result = tail(lines=10)
    assert result == {"lines": [], "total_bytes": 0, "file": None}


# --- T3: export 接口返回 zip + 正确 Content-Disposition ---


def test_export_returns_zip_with_disposition(tmp_path, monkeypatch):
    """临时目录放 2 个 log 文件，调 export，返回 zip 且含正确 filename。"""
    from fastapi.background import BackgroundTasks
    from log_routes import export

    # 准备临时日志目录
    monkeypatch.setattr("log_routes.LOG_DIR", tmp_path)
    (tmp_path / "app.log").write_text("current\n")
    (tmp_path / "app.log.2026-06-08").write_text("day-1\n")

    bg = BackgroundTasks()
    response = export(background=bg)

    # 验证 Content-Type 和 Content-Disposition
    assert response.media_type == "application/zip"
    cd = response.headers["content-disposition"]
    assert "attachment" in cd
    # FastAPI/Starlette 会把 filename 用双引号包起来
    assert "filename=" in cd
    assert "logs-export-" in cd
    assert ".zip" in cd

    # 验证 zip 真的可解压且内容正确
    with zipfile.ZipFile(response.path, "r") as zf:
        names = sorted(zf.namelist())
        assert "app.log" in names
        assert "app-2026-06-08.log" in names
        # 至少 1 个非空内容
        assert zf.read("app.log") == b"current\n"


# --- T4: 异常 handler 触发后日志带 [req:xxx] ---


def test_unhandled_exception_handler_logs_with_request_id(tmp_path, monkeypatch, caplog):
    """触发一个未处理 Exception，日志行必须含 [req:xxxxxxxx] 前缀。"""
    monkeypatch.setattr("logging_setup.LOG_DIR", tmp_path)

    from logging_setup import configure_logging, request_id_var

    configure_logging()

    from main import unhandled_exception_handler

    # 设置一个固定的 request_id
    token = request_id_var.set("test1234")
    try:
        # 构造一个假 request（scope 必须完整，handler 会访问 request.url.path）
        from starlette.requests import Request

        req = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/dummy",
                "headers": [],
                "query_string": b"",
                "scheme": "http",
                "server": ("testserver", 80),
                "client": ("testclient", 50000),
                "root_path": "",
            }
        )

        with caplog.at_level(logging.ERROR, logger="main"):
            import asyncio

            response = asyncio.run(unhandled_exception_handler(req, ValueError("boom")))

        assert response.status_code == 500
        # 找 caplog 里 main logger 的 ERROR 记录
        records = [r for r in caplog.records if r.name == "main" and r.levelname == "ERROR"]
        assert len(records) >= 1, (
            f"no ERROR record from main logger, got: {[(r.name, r.levelname) for r in caplog.records]}"
        )
        rec = records[0]
        assert getattr(rec, "req_id", None) == "test1234", (
            f"req_id not injected, got {getattr(rec, 'req_id', 'MISSING')}"
        )
    finally:
        request_id_var.reset(token)


# --- T5: 轮转 backupCount 生效 ---


def test_rotation_backupcount_trims_oldest(tmp_path, monkeypatch):
    """backupCount=3：构造 5 个远期 backup + 当前文件，触发一次 rollover 后
    最老的 2 个 backup 应被删除，最终剩 1 当前 + 3 backup。

    说明：用 2099 年远期日期预创建 5 个 backup，避免与今日（rollover 实际日期）撞名。
    rollover 产生的 backup 文件名 = 今日，排序上 2099-* > 今日，所以保留 3 个
    2099-*（最老 2 个被裁）。
    """
    from logging.handlers import TimedRotatingFileHandler
    import logging

    monkeypatch.setattr("logging_setup.LOG_DIR", tmp_path)
    # LOG_FILE 在 logging_setup 模块加载时已冻结为 LOG_DIR/'app.log'，需同步改
    monkeypatch.setattr("logging_setup.LOG_FILE", tmp_path / "app.log")

    from logging_setup import configure_logging

    # 先重置 root（避免前序测试残留 handler 干扰 T5）
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    configure_logging()

    # 取刚刚装上的 file handler（SUT 真 handler，不是 stdlib 裸 handler）
    fh = next(h for h in root.handlers if isinstance(h, TimedRotatingFileHandler))
    assert fh.backupCount == 3, f"expected backupCount=3, got {fh.backupCount}"

    # 用远期日期（2099）预创建 5 个 backup，今日的 rollover 不会冲突
    (tmp_path / "app.log").write_text("current\n")
    for i in range(1, 6):
        (tmp_path / f"app.log.2099-01-{i:02d}").write_text(f"day {i}\n")

    # 给 handler 一个打开的当前文件，再触发一次 rollover
    fh.stream = open(fh.baseFilename, "a")
    rec = logging.LogRecord("test", logging.INFO, "", 1, "current\n", None, None)
    rec.req_id = "-"
    fh.emit(rec)
    fh.stream.close()
    fh.doRollover()

    # 列出所有 app.log* 文件
    log_files = sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("app.log"))
    backups = [n for n in log_files if n.startswith("app.log.")]

    # 期望：1 个当前 + 3 个 backup（最老的 2 个被裁，剩下最新 3 个）
    assert "app.log" in log_files, f"missing current app.log, got {log_files}"
    assert len(backups) == 3, f"expected 3 backups (backupCount=3), got {len(backups)}: {backups}"
    # 5 个 2099-* 中最老的 2 个应被裁
    assert "app.log.2099-01-01" not in log_files
    assert "app.log.2099-01-02" not in log_files
    # 5 个 2099-* 中最新 3 个应保留
    assert "app.log.2099-01-03" in log_files
    assert "app.log.2099-01-04" in log_files
    assert "app.log.2099-01-05" in log_files
