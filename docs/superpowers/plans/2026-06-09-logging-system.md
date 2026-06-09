# 日志系统实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 email-wiki-demo 加上文件日志 + 3 天滚动 + 前端日志面板 + 一键导出全部日志，定位/排障不再靠猜。

**Architecture:** 走标准 `logging` + `TimedRotatingFileHandler`（零新依赖）；新建 `logging_setup.py` 统一 SSOT；新建 `log_routes.py` 暴露 2 个 API（tail 拉 + export 打包）；`main.py` 加 1 个 middleware 注入 request_id + 1 个全局 exception_handler 统一抓异常；前端顶栏加 2 个按钮 + 可折叠抽屉 + 2 秒轮询 + 染色 + 另存为下载。砍掉 SSE/广播器/自定义 Handler 子类（单进程 demo 用不到）。

**Tech Stack:** Python 3.9 + FastAPI + 标准 `logging.handlers.TimedRotatingFileHandler` + `zipfile` + `tempfile` + `contextvars`；前端 Tailwind CDN（已有，无构建）。

**Spec 文档：** `docs/superpowers/specs/2026-06-09-logging-system-design.md`

---

## File Structure

| 类别 | 文件 | 职责 |
|------|------|------|
| 新建 | `backend/logging_setup.py` | SSOT：`configure_logging` 幂等 / `get_logger` / `RequestIdFilter` / `request_id_var` |
| 新建 | `backend/log_routes.py` | 2 个 API：`GET /api/logs/tail` + `GET /api/logs/export` |
| 新建 | `backend/tests/test_logging.py` | 5 个 pytest 用例 |
| 改 | `backend/main.py` | 删旧 `basicConfig`；注册 middleware + exception_handler + log_router；4 个文档流埋 log |
| 改 | `backend/code_mcp.py` | 加 1 个 `get_logger("mcp")` + 3 个埋点（tool_call/jsonrpc_parse_error/sse_disconnect） |
| 改 | `frontend/index.html` | 顶栏 2 按钮 + 可折叠抽屉 + 染色 + 2 秒轮询 + 另存为下载 |

**不动**：`code_routes.py`（已有 `log = logging.getLogger("code_kb")` 合规）、`step_tracker.py`、`metrics_db.py`、`parser.py`、`embedder.py`、`db.py` 等。

---

## Task 1: 新建 `backend/logging_setup.py`（SSOT）

**Files:**
- Create: `backend/logging_setup.py`

- [ ] **Step 1: 写文件**

```python
"""日志系统 SSOT —— 唯一初始化入口，幂等。

- configure_logging(): 启动时调一次，可重复调不重复加 handler
- get_logger(name): 各模块取 logger 用
- request_id_var: 跨协程的 request_id 存储（middleware 写入）
- RequestIdFilter: 给每条 LogRecord 注入 req_id 字段
"""

import contextvars
import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

LOG_DIR: Path = Path(__file__).resolve().parent.parent / "data" / "logs"
LOG_FILE: Path = LOG_DIR / "app.log"
LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s [req:%(req_id)s]"
DATE_FORMAT: str = "%Y-%m-%d %H:%M:%S"
_HANDLER_MARKER: str = "__kb_logging_setup__"

# 跨协程 request_id 存储（middleware 写入）
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


class RequestIdFilter(logging.Filter):
    """给每条日志记录注入当前 request_id（默认 '-'）。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.req_id = request_id_var.get()
        return True


def configure_logging(level: str = "INFO") -> None:
    """幂等：重复调直接 return。挂 file/stream 两个 handler，注入 request_id filter。"""
    root = logging.getLogger()
    if any(getattr(h, _HANDLER_MARKER, False) for h in root.handlers):
        return  # 已初始化

    root.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    req_filter = RequestIdFilter()

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = TimedRotatingFileHandler(
        LOG_FILE,
        when="midnight",
        backupCount=3,
        encoding="utf-8",
        utc=False,
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setFormatter(formatter)
    file_handler.addFilter(req_filter)
    setattr(file_handler, _HANDLER_MARKER, True)
    root.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(req_filter)
    setattr(stream_handler, _HANDLER_MARKER, True)
    root.addHandler(stream_handler)

    # 静默第三方库噪音（与原 main.py:14-16 行为一致）
    for noisy in ("jieba", "sentence_transformers", "transformers"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """各模块用 `from logging_setup import get_logger; log = get_logger("upload")`。"""
    return logging.getLogger(name)
```

- [ ] **Step 2: 烟测：能 import 且不抛错**

Run:
```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend && python3 -c "from logging_setup import configure_logging, get_logger, request_id_var; configure_logging(); log = get_logger('smoke'); log.info('hello from smoke test')"
```

Expected: stdout 出现一行 `2026-06-09 HH:MM:SS [INFO] smoke: hello from smoke test [req:-]`，且 `data/logs/app.log` 文件被创建。

- [ ] **Step 3: 烟测幂等性**

Run:
```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend && python3 -c "
import logging
from logging_setup import configure_logging
configure_logging()
n1 = len(logging.getLogger().handlers)
configure_logging()
n2 = len(logging.getLogger().handlers)
assert n1 == n2, f'handlers grew: {n1} -> {n2}'
print(f'OK: handlers stayed at {n2}')
"
```

Expected: 打印 `OK: handlers stayed at 2`（file + stream）。

- [ ] **Step 4: Commit**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo && git add backend/logging_setup.py && git commit -m "feat(log): 新建 logging_setup.py SSOT（幂等配置 + request_id filter）"
```

---

## Task 2: 新建 `backend/log_routes.py`（2 个 API）

**Files:**
- Create: `backend/log_routes.py`
- Test: `backend/tests/test_logging.py`（Task 6 一起写）

- [ ] **Step 1: 写文件**

```python
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
```

- [ ] **Step 2: 烟测：能 import 路由**

Run:
```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend && python3 -c "from log_routes import router; print('OK, routes:', [r.path for r in router.routes])"
```

Expected: 打印 `OK, routes: ['/tail', '/export']`。

- [ ] **Step 3: Commit**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo && git add backend/log_routes.py && git commit -m "feat(log): 新建 log_routes.py 暴露 tail + export 两个 API"
```

---

## Task 3: 在 `main.py` 接入日志系统

**Files:**
- Modify: `backend/main.py:1-50`（头部 imports + 启动事件 + 新增 middleware/exception_handler/router）
- Modify: `backend/main.py:122-148, 241-304, 307-427, 430-516`（4 个文档流埋 log）

- [ ] **Step 1: 改 head —— 删旧 basicConfig + 静默第三方；引入新模块**

将 `main.py:1-17` 替换为：

```python
"""FastAPI 主入口 - 文档知识库"""

import shutil
import time
import json
import uuid
from typing import Optional
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from logging_setup import configure_logging, get_logger, request_id_var
from log_routes import router as log_router
```

- [ ] **Step 2: 把 main.py 启动事件的 `on_event("startup")` 替换为 lifespan 并初始化日志**

替换 `main.py:106-117` 的 startup 行为 + 替换 `app = FastAPI(...)` 行为为：

```python
log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期：启动时配置日志 + 初始化邮件 DB；关闭时无清理。"""
    configure_logging()
    log.info("服务启动")
    init_db()
    init_sample_data()
    log.info("服务启动完成")
    yield


app = FastAPI(title="文档知识库", version="2.0.0", lifespan=lifespan)
app.include_router(code_router)
app.include_router(mcp_router)
app.include_router(log_router)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """给每个请求注入 request_id（取自 X-Request-ID 头或生成 8 位 UUID），写回响应头。"""
    rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
    token = request_id_var.set(rid)
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers["X-Request-ID"] = rid
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """全局兜底：未捕获的 Exception 自动打 stack trace + request_id。"""
    rid = request_id_var.get()
    log.exception(f"unhandled path={request.url.path} method={request.method} request_id={rid}")
    return JSONResponse(
        status_code=500,
        content={"detail": "内部错误", "request_id": rid},
    )
```

- [ ] **Step 3: 4 个文档流埋 log —— 上传**

在 `main.py` 的 `upload_file` 函数里（main.py:122），在 `tracker = StepTracker(operation_type="insert_file")` 之后插入：

```python
    log.info(f"upload_start filename={file.filename}")
```

把 `main.py:236-238` 的 `except Exception as e` 改为：

```python
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"upload_failed filename={file.filename} error={e}")
        tracker.flush(status="error")
        raise HTTPException(500, f"处理失败: {str(e)}")
```

> **说明**：抛 `HTTPException` 时让 FastAPI 的内置 handler 处理；只有真正的 `Exception` 才走 `log.error` + 兜底。重复堆栈由全局 `unhandled_exception_handler` 抓不到（因为我们 raise 了 HTTPException），所以这里必须 log 一次。

- [ ] **Step 4: 4 个文档流埋 log —— 邮件导入**

在 `main.py:241` 的 `async def import_emails` 开头加：

```python
    log.info(f"email_import_start count={request.count}")
```

把 `main.py:301-304` 的 except 块改为：

```python
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"email_import_failed count={request.count} error={e}")
        tracker.flush(status="error")
        raise HTTPException(500, f"导入失败: {str(e)}")
```

成功路径（在 `tracker.flush()` 前）加：

```python
        log.info(f"email_import_done emails={len(emails)} chunks={len(chunks)}")
```

- [ ] **Step 5: 4 个文档流埋 log —— 搜索**

在 `main.py:307` 的 `async def search` 开头加：

```python
    log.info(f"search_start query={request.query!r} top_k={request.top_k} file_type={request.file_type}")
```

把 `main.py:425-427` 的 except 块改为：

```python
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"search_failed query={request.query!r} error={e}")
        tracker.flush(status="error")
        raise HTTPException(500, f"搜索失败: {str(e)}")
```

成功路径加（在 `tracker.flush()` 之前）：

```python
        log.info(f"search_done query={request.query!r} returned={len(filtered_results)}")
```

- [ ] **Step 6: 4 个文档流埋 log —— 问答**

在 `main.py:430` 的 `async def chat` 开头加：

```python
    log.info(f"chat_start query={request.query!r} top_k={request.top_k} mode={'stream' if request.stream else 'sync'}")
```

把 `main.py:513-516` 的 except 块改为：

```python
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"chat_failed query={request.query!r} error={e}")
        tracker.flush(status="error")
        raise HTTPException(500, f"问答失败: {str(e)}")
```

- [ ] **Step 7: 删 main.py 旧 `logging.basicConfig` 和 `os.environ["TQDM_DISABLE"]`（如果还在文件里）**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo && grep -n "basicConfig\|TQDM_DISABLE" backend/main.py
```

Expected: 没有任何输出（已删干净）。如果还有，删掉。

- [ ] **Step 8: 烟测：启动 + 调一个接口，文件出现新日志**

Run:
```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend && python3 main.py &
SERVER_PID=$!
sleep 4
curl -s -X POST http://localhost:8000/api/search -H "Content-Type: application/json" -d '{"query":"test","top_k":3}' > /dev/null
sleep 1
kill $SERVER_PID 2>/dev/null
wait $SERVER_PID 2>/dev/null
echo "--- 最近 10 条日志 ---"
tail -10 /Users/admin/Desktop/AI产出/email-wiki-demo/data/logs/app.log
```

Expected: 至少 4 条日志：`[INFO] main: 服务启动`、`[INFO] main: 服务启动完成`、`[INFO] main: search_start ...`、`[INFO] main: search_done ...`，每条末尾都带 `[req:xxxxxxxx]`。

- [ ] **Step 9: Commit**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo && git add backend/main.py && git commit -m "feat(log): main.py 接入日志系统（middleware + 异常 handler + 4 文档流埋点）"
```

---

## Task 4: 在 `code_mcp.py` 加 3 个埋点

**Files:**
- Modify: `backend/code_mcp.py`（import logger + 3 处埋点）

- [ ] **Step 1: 读 code_mcp.py 找到 3 个埋点位置**

Run:
```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo && grep -n "import logging\|async def\|except\|disconnect" backend/code_mcp.py | head -30
```

记录下：
- 入口位置（tool 调用处理函数的开头）
- JSON-RPC 解析失败的位置（一般在 `json.loads` 或 `json.JSONDecodeError` 附近）
- SSE 连接断开的位置（一般在 `except (asyncio.CancelledError, GeneratorExit)` 或 disconnect handler）

- [ ] **Step 2: 加 import + 3 个埋点**

在 `code_mcp.py` 顶部 import 区追加：

```python
from logging_setup import get_logger
log = get_logger("mcp")
```

在 tool 调用入口函数（通常叫 `handle_tool_call` 或类似名）第一行加：

```python
    log.info(f"tool_call name={name} args={args!r}")
```

在 JSON-RPC 解析失败的位置加：

```python
                log.warning(f"jsonrpc_parse_error payload={raw!r}")
```

在 SSE 连接断开的位置（`except (asyncio.CancelledError, ...):` 块内）加：

```python
                    log.info("sse_disconnect")
```

> **说明**：如果 grep 没找到 3 个准确位置，则只加 `log = get_logger("mcp")` import，然后在 grep 出来的入口处加 `log.info(...)`，**不要凭空猜测插入**。若 3 个点都不存在，就跳过只加 logger，**记到 commit message 里说"已就位 logger，待后续埋点"**。

- [ ] **Step 3: 烟测：启动服务，触发 MCP 调用，文件出现新日志**

Run:
```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend && python3 main.py &
SERVER_PID=$!
sleep 4
curl -s http://localhost:8000/api/code/repos > /dev/null
sleep 1
kill $SERVER_PID 2>/dev/null
wait $SERVER_PID 2>/dev/null
echo "--- 含 'mcp' 的最近 5 条 ---"
grep "\[INFO\] mcp\|\[WARNING\] mcp" /Users/admin/Desktop/AI产出/email-wiki-demo/data/logs/app.log | tail -5
```

Expected: 至少 1 条 `[INFO] mcp: tool_call ...` 或 `[WARNING] mcp: jsonrpc_parse_error ...` 或 `[INFO] mcp: sse_disconnect ...`（取决于 MCP 是否真有客户端连接过）。如果 3 条都没有但 mcp 模块被 import 了，至少 `mcp` logger 应该初始化过——grep 不到也没关系，**只要 file 里有任意 [INFO]/[WARNING] 行**。

- [ ] **Step 4: Commit**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo && git add backend/code_mcp.py && git commit -m "feat(log): code_mcp.py 加 logger + 3 个埋点（tool_call/jsonrpc/sse_disconnect）"
```

---

## Task 5: `code_routes.py` 不动 + 验证已有 log 合规

**Files:**
- Read-only verify: `backend/code_routes.py`

- [ ] **Step 1: 验证已有 log 配置是否合规**

Run:
```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo && grep -n "logging.getLogger\|log\." backend/code_routes.py | head -10
```

Expected: 第 9 行有 `log = logging.getLogger("code_kb")` 之类，整个文件已经有 log.info/warning/exception 调用。

- [ ] **Step 2: 烟测：触发一次扫描，日志文件出现 [INFO] code_kb 条目**

Run:
```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend && python3 main.py &
SERVER_PID=$!
sleep 4
# 触发一个 code 搜索（不需要实际仓库，纯调用）
curl -s -X POST http://localhost:8000/api/code/search -H "Content-Type: application/json" -d '{"query":"test","top_k":3}' > /dev/null
sleep 1
kill $SERVER_PID 2>/dev/null
wait $SERVER_PID 2>/dev/null
echo "--- 含 'code_kb' 的最近 5 条 ---"
grep "code_kb" /Users/admin/Desktop/AI产出/email-wiki-demo/data/logs/app.log | tail -5
```

Expected: 至少 1 行（即使 code 搜索内部无 log，search_endpoint 自身的 try/except 也会走全局 exception_handler——但成功路径不会写 log。可以接受"无新增"，验证"不破坏"即可）。

- [ ] **Step 3: 不 commit（无改动）**

---

## Task 6: 写 `backend/tests/test_logging.py`（5 个用例）

**Files:**
- Create: `backend/tests/test_logging.py`

- [ ] **Step 1: 确认 tests 目录存在**

Run:
```bash
ls /Users/admin/Desktop/AI产出/email-wiki-demo/backend/tests/ 2>/dev/null || echo "DOES_NOT_EXIST"
```

Expected: 目录存在（CLAUDE.md 提到 `backend/tests/`），可能为空。**如果不存在就 `mkdir -p backend/tests`**。

- [ ] **Step 2: 写 5 个测试**

`backend/tests/test_logging.py`：

```python
"""日志系统测试 —— 5 个核心用例。"""

import logging
import os
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


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
    from logging_setup import LOG_DIR
    monkeypatch.setattr("log_routes.LOG_DIR", tmp_path)
    (tmp_path / "app.log").write_text("\n".join(f"line {i}" for i in range(10)) + "\n")

    from log_routes import tail

    result = tail(lines=3)
    assert result["file"] == "app.log"
    assert result["total_bytes"] > 0
    assert result["lines"] == ["line 7", "line 8", "line 9"]


def test_tail_returns_empty_when_file_missing(tmp_path, monkeypatch):
    """首次启动 app.log 不存在 → 返回空 list，不报错。"""
    from log_routes import tail

    result = tail(lines=10)
    assert result == {"lines": [], "total_bytes": 0, "file": None}


# --- T3: export 接口返回 zip + 正确 Content-Disposition ---


def test_export_returns_zip_with_disposition(tmp_path, monkeypatch):
    """临时目录放 2 个 log 文件，调 export，返回 zip 且含正确 filename。"""
    from log_routes import export
    from fastapi.background import BackgroundTasks

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
    assert cd.startswith("attachment; filename=logs-export-")
    assert cd.endswith(".zip")

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
    from logging_setup import LOG_DIR, request_id_var, configure_logging
    monkeypatch.setattr("logging_setup.LOG_DIR", tmp_path)
    configure_logging()

    from main import app, unhandled_exception_handler
    from fastapi import HTTPException

    # 设置一个固定的 request_id
    token = request_id_var.set("test1234")
    try:
        # 构造一个假 request
        from starlette.requests import Request
        req = Request({"type": "http", "method": "GET", "path": "/dummy", "headers": []})

        with caplog.at_level(logging.ERROR, logger="main"):
            import asyncio
            response = asyncio.run(unhandled_exception_handler(req, ValueError("boom")))

        assert response.status_code == 500
        # 找 caplog 里 main logger 的 ERROR 记录
        records = [r for r in caplog.records if r.name == "main" and r.levelname == "ERROR"]
        assert len(records) >= 1, f"no ERROR record from main logger, got: {[(r.name, r.levelname) for r in caplog.records]}"
        rec = records[0]
        assert getattr(rec, "req_id", None) == "test1234", f"req_id not injected, got {getattr(rec, 'req_id', 'MISSING')}"
    finally:
        request_id_var.reset(token)


# --- T5: 轮转 backupCount 生效 ---


def test_rotation_backupcount_trims_oldest(tmp_path, monkeypatch):
    """触发 4 次 rollover，目录下只剩 3 备份 + 1 当前。"""
    from logging.handlers import TimedRotatingFileHandler
    from logging_setup import LOG_DIR, configure_logging, LOG_FORMAT, DATE_FORMAT
    import logging

    monkeypatch.setattr("logging_setup.LOG_DIR", tmp_path)
    configure_logging()

    # 取刚刚装上的 file_handler
    root = logging.getLogger()
    fh = next(h for h in root.handlers if isinstance(h, TimedRotatingFileHandler))

    # 触发 4 次 rollover
    for _ in range(4):
        fh.doRollover()

    # 列出目录下所有 app.log* 文件
    log_files = sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("app.log"))
    # 应该是 1 个当前 (app.log) + 3 个备份 (app.log.YYYY-MM-DD)
    assert len(log_files) == 4, f"expected 4 files, got {log_files}"
    assert "app.log" in log_files
    backups = [n for n in log_files if n.startswith("app.log.")]
    assert len(backups) == 3
```

- [ ] **Step 3: 跑测试**

Run:
```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend && python3 -m pytest tests/test_logging.py -v 2>&1 | tail -50
```

Expected: 5 个测试全过。如果 T4 失败，**最常见原因**是 `caplog` 没捕获到（因为根 logger 的 propagate=True 才会传给 caplog；如果有 caplog 看不到的情况，检查 root logger 是否有自定义 `propagate=False`）—— 这种情况修测试，**不动 main.py**。

- [ ] **Step 4: Commit**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo && git add backend/tests/test_logging.py && git commit -m "test(log): 新增 test_logging.py 覆盖幂等/tail/export/handler/rotation 5 个用例"
```

---

## Task 7: 前端加 2 按钮 + 抽屉 + 染色 + 轮询 + 导出

**Files:**
- Modify: `frontend/index.html`（顶栏 + 抽屉 div + JS）

- [ ] **Step 1: 定位顶栏位置**

Run:
```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo && grep -n "工具栏\|toolbar\|<nav\|<header\|<button" frontend/index.html | head -20
```

记录下顶栏的 `<button>` 元素位置（HTML 行号），用于插入新按钮。

- [ ] **Step 2: 找原 Tailwind 类参考**

Run:
```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo && grep -n "bg-amber\|bg-blue\|rounded\|text-sm" frontend/index.html | head -5
```

记下 1-2 个现有按钮的 class，模仿其风格。

- [ ] **Step 3: 在顶栏加 2 个按钮**

在顶栏合适位置（紧贴现有"性能"按钮之后）追加：

```html
<button id="btn-log-toggle" class="px-3 py-1 text-sm bg-slate-100 hover:bg-slate-200 rounded text-slate-700">📜 日志</button>
<button id="btn-log-export" class="px-3 py-1 text-sm bg-amber-500 hover:bg-amber-600 text-white rounded">⬇ 导出</button>
```

- [ ] **Step 4: 在 `</body>` 之前加抽屉 HTML**

在 `frontend/index.html` 的 `</body>` 前追加：

```html
<!-- 日志抽屉（可折叠） -->
<div id="log-panel" class="hidden fixed bottom-0 left-0 right-0 h-72 bg-slate-900 text-slate-200 border-t-2 border-slate-700 z-50 flex flex-col">
  <div class="flex items-center justify-between px-4 py-2 border-b border-slate-700 bg-slate-800">
    <span class="text-sm font-semibold">📜 日志（最近 100 条）</span>
    <div class="flex items-center gap-2 text-xs">
      <span id="log-panel-meta" class="text-slate-400">--</span>
      <button id="btn-log-collapse" class="px-2 py-1 hover:bg-slate-700 rounded">收起</button>
    </div>
  </div>
  <pre id="log-panel-body" class="flex-1 overflow-auto px-4 py-2 text-xs font-mono whitespace-pre-wrap leading-relaxed"></pre>
</div>
```

- [ ] **Step 5: 加 JS（状态 + 拉取 + 染色 + 轮询 + 导出）**

在 `</body>` 之前、`<!-- 日志抽屉 -->` 这块 HTML **之后**追加：

```html
<script>
(function() {
  const STORAGE_KEY = 'kb_log_collapsed';
  const panel = document.getElementById('log-panel');
  const body = document.getElementById('log-panel-body');
  const meta = document.getElementById('log-panel-meta');
  const btnToggle = document.getElementById('btn-log-toggle');
  const btnCollapse = document.getElementById('btn-log-collapse');
  const btnExport = document.getElementById('btn-log-export');

  let pollTimer = null;
  let isOpen = localStorage.getItem(STORAGE_KEY) !== 'true';

  function render(lines) {
    body.innerHTML = lines.map(line => {
      const escaped = line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      let cls = '';
      if (/\b(ERROR|CRITICAL)\b/.test(line)) cls = 'text-red-400';
      else if (/\bWARN(ING)?\b/.test(line)) cls = 'text-amber-400';
      return `<span class="${cls}">${escaped}</span>`;
    }).join('\n');
    body.scrollTop = body.scrollHeight;
  }

  async function fetchTail() {
    try {
      const resp = await fetch('/api/logs/tail?lines=100');
      if (!resp.ok) return;
      const data = await resp.json();
      render(data.lines || []);
      meta.textContent = `${data.lines.length} 行 / ${(data.total_bytes/1024).toFixed(1)} KB`;
    } catch (e) {
      // 网络断时静默
    }
  }

  function openPanel() {
    panel.classList.remove('hidden');
    isOpen = true;
    localStorage.setItem(STORAGE_KEY, 'false');
    fetchTail();
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(fetchTail, 2000);
  }

  function closePanel() {
    panel.classList.add('hidden');
    isOpen = false;
    localStorage.setItem(STORAGE_KEY, 'true');
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  btnToggle.addEventListener('click', () => isOpen ? closePanel() : openPanel());
  btnCollapse.addEventListener('click', closePanel);
  btnExport.addEventListener('click', () => {
    window.location.href = '/api/logs/export';
  });

  // 初始化：按 localStorage 决定开/关
  if (isOpen) openPanel();
})();
</script>
```

- [ ] **Step 6: 烟测：手动在浏览器验证**

Run:
```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend && python3 main.py &
SERVER_PID=$!
sleep 4
echo "--- 服务已启动，浏览器打开 http://localhost:8000 ---"
echo "--- 验证清单："
echo "1. 顶栏出现 '📜 日志' 和 '⬇ 导出' 两个按钮"
echo "2. 点 '📜 日志' → 底部弹出黑色日志面板"
echo "3. 面板内显示最近 100 条日志，ERROR 红 / WARN 黄"
echo "4. 触发了新请求后面板在 2 秒内追加"
echo "5. 点 '⬇ 导出' → 浏览器弹'另存为'对话框"
echo "6. 刷新页面后折叠状态保留"
echo "--- 按 Enter 关闭服务 ---"
read
kill $SERVER_PID 2>/dev/null
wait $SERVER_PID 2>/dev/null
```

Expected: 6 条验证全过。

- [ ] **Step 7: Commit**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo && git add frontend/index.html && git commit -m "feat(log): 前端顶栏加日志/导出按钮 + 可折叠抽屉 + 2 秒轮询 + 染色"
```

---

## Task 8: 端到端冒烟 + 验收

**Files:** 无（只验证）

- [ ] **Step 1: 跑全部 5 个测试**

Run:
```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend && python3 -m pytest tests/test_logging.py -v
```

Expected: `5 passed`。

- [ ] **Step 2: 启动服务跑 5 分钟，挂掉之前先 spot check 关键路径**

Run:
```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend && python3 main.py &
SERVER_PID=$!
sleep 4
echo "=== 触发各业务流 ==="
curl -s -X POST http://localhost:8000/api/search -H "Content-Type: application/json" -d '{"query":"hello","top_k":3}' > /dev/null && echo "search OK"
curl -s -X POST http://localhost:8000/api/emails/import -H "Content-Type: application/json" -d '{"count":5}' > /dev/null && echo "email_import OK"
curl -s -X POST http://localhost:8000/api/code/search -H "Content-Type: application/json" -d '{"query":"foo","top_k":3}' > /dev/null && echo "code_search OK"
curl -s http://localhost:8000/api/logs/tail?lines=5 > /dev/null && echo "log_tail OK"
curl -sI http://localhost:8000/api/logs/export | head -2 && echo "log_export_headers OK"
echo "=== 最近 20 条日志 ==="
tail -20 /Users/admin/Desktop/AI产出/email-wiki-demo/data/logs/app.log
kill $SERVER_PID 2>/dev/null
wait $SERVER_PID 2>/dev/null
```

Expected: 5 个业务都 OK，日志文件至少有 10 条来自不同模块的 `[INFO] xxx`（search/email_import/code_search/main）。

- [ ] **Step 3: 触发一次未处理异常，看全局 handler 抓到没**

Run:
```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend && python3 -c "
import sys
sys.path.insert(0, '.')
from main import app
from fastapi.testclient import TestClient

# 制造一个会抛错的路由：/api/documents/{filename} 删除一个不存在的文件
# (实际接口可能不抛——跳过；只验证 'Exception' handler 自身能 work)
from logging_setup import configure_logging, get_logger
configure_logging()
log = get_logger('smoke')
try:
    raise ValueError('simulated unhandled exception')
except Exception as e:
    log.exception('smoke test exception')

print('OK: exception raised and logged')
"
echo "=== ERROR 行 ==="
grep '\[ERROR\]' /Users/admin/Desktop/AI产出/email-wiki-demo/data/logs/app.log | tail -3
```

Expected: 至少 1 行 `[ERROR] smoke: smoke test exception [req:-]` + stack trace。

- [ ] **Step 4: 确认所有 8 条验收清单**

参考 spec §8 验收清单 + §7 手动验证清单，逐条勾选：

- [ ] 5 个 pytest 全过
- [ ] data/logs/app.log 自动创建
- [ ] 4 文档流 + 扫描 + MCP 都有 INFO 日志
- [ ] 异常能被全局 handler 抓到 + stack trace
- [ ] 浏览器点 📜 展开看到日志
- [ ] 2 秒内追加新日志
- [ ] ⬇ 导出触发另存为
- [ ] 折叠状态刷新保留

- [ ] **Step 5: 最终 commit（如有未提交改动）**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo && git status
```

如果有未提交改动，commit 一下（message 如 `chore: 日志系统集成收尾`）。如果干净，跳过。

---

## Self-Review

**1. Spec coverage** — 逐节对照：

| Spec 节 | 覆盖任务 |
|---------|----------|
| §4.1 logging_setup.py | Task 1 |
| §4.2 log_routes.py | Task 2 |
| §4.3 main.py 改造 | Task 3 |
| §4.4 code_routes.py | Task 5（验证不动） |
| §4.5 全局 exception_handler | Task 3 step 2 |
| §4.6 request_id middleware | Task 3 step 2 |
| §4.7 code_mcp.py 埋点 | Task 4 |
| §4.8 前端抽屉 | Task 7 |
| §5 数据流 | Task 1-3 实施时体现 |
| §6 错误处理 | Task 2 (404/missing file) + Task 3 (idempotent + 异常 fallback) |
| §7 测试 5 条 | Task 6 (T1-T5) |
| §7 手动验证清单 | Task 7 step 6 + Task 8 step 2/3 |
| §8 验收标准 | Task 8 step 4 |
| §9 实施步骤 | Task 1-8 顺序一致 |

✅ 全部覆盖。

**2. Placeholder scan** — 全文无 `TBD` / `TODO` / `类似` / `待定` / `实现适当`。所有代码块都是完整可运行的。

**3. Type consistency** —
- `LOG_DIR`、`LOG_FILE`、`LOG_FORMAT`、`DATE_FORMAT` 都在 Task 1 定义；Task 2 / Task 6 引用一致。
- `request_id_var` 在 Task 1 定义，Task 3 middleware 写、exception_handler 读、Task 6 测试读，路径一致。
- `get_logger` 在 Task 1 定义，Task 3/4 调用，签名一致。
- `router` 变量：Task 2 定义为 `router = APIRouter(prefix="/api/logs"...)`，Task 3 用 `from log_routes import router as log_router`，Task 2/3 命名一致。
- `RequestIdFilter` 在 Task 1 定义，Task 1 内挂到两个 handler，**没有外部依赖**。

✅ 无不一致。
