"""日志系统对外 API：tail（拉最近 N 行） + export（zip 下载）。"""

import os
import tempfile
import zipfile
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

from logging_setup import LOG_DIR

router = APIRouter(prefix="/api/logs", tags=["logs"])

_TAIL_LINES_MIN = 1
_TAIL_LINES_MAX = 500
_TAIL_LINES_DEFAULT = 100


@router.get("/tail")
def tail(lines: int = _TAIL_LINES_DEFAULT) -> dict:
    """读取 data/logs/app.log 最后 N 行。文件不存在返回空 list，不报错。"""
    if not (_TAIL_LINES_MIN <= lines <= _TAIL_LINES_MAX):
        raise HTTPException(400, detail=f"lines 范围 [{_TAIL_LINES_MIN}, {_TAIL_LINES_MAX}]")

    log_file = LOG_DIR / "app.log"
    if not log_file.exists():
        return {"lines": [], "total_bytes": 0, "file": None}

    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            recent = deque(f, maxlen=lines)
    except OSError as e:
        raise HTTPException(500, detail=f"读取日志失败: {e}")

    size = log_file.stat().st_size
    return {
        "lines": [line.rstrip("\n") for line in recent],
        "total_bytes": size,
        "file": log_file.name,
    }


@router.get("/export")
def export(background: BackgroundTasks) -> FileResponse:
    """打包 data/logs/ 下 app.log + app.log.* 为 zip，通过 FileResponse 触发浏览器下载。"""
    # 收集日志文件（app.log + app.log.YYYY-MM-DD）
    if not LOG_DIR.exists():
        raise HTTPException(404, detail="暂无日志")

    files: List[Path] = []
    for name in sorted(os.listdir(LOG_DIR)):
        p = LOG_DIR / name
        if not p.is_file():
            continue
        if name == "app.log" or (name.startswith("app.log.") and name != "app.log.zip"):
            files.append(p)

    if not files:
        raise HTTPException(404, detail="暂无日志")

    # 临时 zip 也放 LOG_DIR，便于排查
    tmp_fd, tmp_path_str = tempfile.mkstemp(suffix=".zip", prefix="logs-export-", dir=LOG_DIR)
    os.close(tmp_fd)
    tmp_path = Path(tmp_path_str)

    # 按日期排序：app.log.* 按后缀字典序即可；app.log 排最前（最新）
    def _sort_key(p: Path) -> str:
        return "" if p.name == "app.log" else p.name

    files_sorted = sorted(files, key=_sort_key)
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for src in files_sorted:
            # 重命名：app.log.YYYY-MM-DD → app-YYYY-MM-DD.log；app.log 保持原名
            arc = src.name if src.name == "app.log" else src.name.replace("app.log.", "app-") + ".log"
            zf.write(src, arcname=arc)

    today = datetime.now().strftime("%Y-%m-%d")
    download_name = f"logs-export-{today}.zip"

    background.add_task(_cleanup_tmp, tmp_path)

    return FileResponse(
        path=tmp_path,
        media_type="application/zip",
        filename=download_name,
    )


def _cleanup_tmp(path: Path) -> None:
    """下载响应发完后删除临时 zip。"""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
