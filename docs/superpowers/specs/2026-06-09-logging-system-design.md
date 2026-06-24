# 日志系统设计文档

> 日期：2026-06-09
> 状态：待用户复核
> 适用项目：email-wiki-demo

## 1. 背景与目标

### 1.1 现状
- `main.py:7-11` 只用 `logging.basicConfig` 把日志输出到 stdout，**没有文件、没有轮转、没有导出**
- `code_routes.py:9` 使用了 `logging.getLogger("code_kb")`，但同样只走 stdout
- 其他模块（`parser.py`、`embedder.py`、`db.py` 等）**完全没 import logging**
- 异常处理统一模式：`try: ... except Exception as e: raise HTTPException(500, f"...: {str(e)}")` —— **stack trace 全部丢失**
- 后台扫描线程的取消/清理已用 `try/finally` 包裹，但无文件持久日志，排障困难
- 前端 `index.html`（2441 行）**没有"日志查看/导出"按钮**
- 已有 `StepTracker` + `metrics.db` 记录请求级步骤耗时（**职责是性能追踪，不是日志**，本文不动）

### 1.2 目标
1. 完善各业务流的日志节点（4 文档流 + 代码扫描 + 代码搜索/问答/追踪 + MCP），覆盖入口/出口/异常
2. 日志文件 3 天滚动存储，每天 0 点切割，保留最近 3 份
3. 前端可折叠"日志面板"，展开时拉取最近 100 条
4. 前端"导出"按钮一键下载整个 3 天滚动范围（zip 打包），通过浏览器"另存为"对话框让用户选目录

### 1.3 非目标
- 不引入第三方日志库（loguru 等）
- 不做日志聚合/集中化（ELK、Loki 等）
- 不做日志分析/可视化大盘（前端只展示文本+染色，不做图表）
- 不动 `StepTracker` / `metrics.db`（职责不同，但会通过 `request_id` 联动）
- 不改鉴权机制（项目全 API 无鉴权，日志接口同样无鉴权）

## 2. 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│ Frontend (index.html)                                       │
│  ┌────────────────────────────────────────┐                │
│  │ 顶栏: [📜 日志] [⬇ 导出]                │ ← 新增 2 个按钮 │
│  └────────────────────────────────────────┘                │
│         │  GET  /api/logs/tail?lines=100                   │
│         │  GET  /api/logs/export                           │
│         ▼                                                  │
│ FastAPI main.py                                            │
│  ┌──────────────────────────────────────────┐              │
│  │ 新模块 backend/logging_setup.py          │ ← SSOT 配置   │
│  │   configure_logging() — idempotent       │              │
│  │   get_logger(name)                       │              │
│  │   TimedRotatingFileHandler(midnight, 3)  │              │
│  └──────────────────────────────────────────┘              │
│  ┌──────────────────────────────────────────┐              │
│  │ 新模块 backend/log_routes.py             │              │
│  │   GET /api/logs/tail?lines=N            │              │
│  │   GET /api/logs/export  →  zip 临时文件  │              │
│  └──────────────────────────────────────────┘              │
│  ┌──────────────────────────────────────────┐              │
│  │ 现有 main.py / code_routes.py / code_mcp │              │
│  │   关键入口/出口/异常 埋 log.info/warn/   │              │
│  │   except 统一走全局 exception_handler    │              │
│  │   request_id 通过 contextvars 注入       │              │
│  └──────────────────────────────────────────┘              │
│         │                                                  │
│         ▼                                                  │
│ data/logs/ (运行时自动创建)                                │
│  ├── app.log             ← 当前正在写                       │
│  ├── app.log.2026-06-07  ← 3 天滚动备份                     │
│  ├── app.log.2026-06-08                                    │
│  └── app.log.2026-06-09                                    │
└─────────────────────────────────────────────────────────────┘
```

## 3. 关键设计决策

| # | 决策点 | 选择 | 理由 |
|---|--------|------|------|
| D1 | 范式 | 标准 `logging` + `TimedRotatingFileHandler` | 项目已用 2 处 logging，零新依赖；handler 自带轮转不写逻辑 |
| D2 | 路径 | `data/logs/app.log` | 跟 `metrics.db` 放一起，便于运维打包 data/ 目录；避免 venv 复制污染 |
| D3 | 轮转策略 | `when="midnight"`, `backupCount=3`, `suffix="%Y-%m-%d"` | 每天 0 点切，保留 3 份，命名直观 |
| D4 | 格式 | `2026-06-09 14:32:05 [INFO] upload: msg [req:abc123]` | 纯文本，grep/awk 友好；末尾自动带 request_id |
| D5 | 级别 | 默认 INFO；文件 + stdout 都写 | 与现状一致；不丢开发体验 |
| D6 | 埋点 | 4 文档流 + 扫描 + 3 code API + MCP + 全量异常 | 范围明确，避免漏点 |
| D7 | 全局异常 | 1 个 `@app.exception_handler(Exception)` 统一处理 | 避免每个 except 重复 5+ 行；FastAPI 推荐的减法 |
| D8 | request_id | `contextvars.ContextVar` + `logging.Filter` 自动注入 | 复用 StepTracker 已有的 request_id（同一请求两处一致） |
| D9 | 实时面板 | 砍 SSE：每 2 秒轮询 `/api/logs/tail?lines=100` | 单进程 demo 不需要 pub/sub；轮询足够；省 60% 代码 |
| D10 | 导出范围 | 整个 3 天滚动范围 zip 打包 | 贴合"3 天滚动"原话；跨日带历史 |
| D11 | 导出方式 | 后端写到 `data/logs/` 临时 zip → `FileResponse` + `BackgroundTask` 清理 | 避免一次性内存打包打到几十 MB |
| D12 | 前端下载 | `window.location.href = '/api/logs/export'` 触发浏览器另存为 | 浏览器安全模型限制：Web 不能写任意目录，"另存为" 是最贴近"用户选中文件夹"的方案 |
| D13 | 鉴权 | 无（跟现有 API 一致） | 保持 demo 体量 |
| D14 | 第三方日志 | 静默 `jieba` / `sentence_transformers` / `transformers` 的 WARNING | 与现状 `main.py:14-16` 行为一致 |

## 4. 模块设计

### 4.1 `backend/logging_setup.py`（SSOT，约 50 行）

**职责**：唯一初始化入口，幂等。

**关键 API**：
- `configure_logging(level: str = "INFO") -> None`
  - 幂等：检查 `logging.getLogger().handlers` 是否已包含自定义 handler，是则直接 return
  - `os.makedirs(LOG_DIR, exist_ok=True)`
  - 添加 `TimedRotatingFileHandler(LOG_FILE, when="midnight", backupCount=3, suffix="%Y-%m-%d", encoding="utf-8")`
  - 保留 `StreamHandler(stdout)`（不丢开发体验）
  - 静默 `jieba` / `sentence_transformers` / `transformers` 到 WARNING
  - 设置 `logging.getLogger().setLevel(level)`
  - 注册 `RequestIdFilter`（自动注入 `[req:xxx]`）
- `get_logger(name: str) -> logging.Logger`

**常量**：
```python
LOG_DIR = Path(__file__).parent.parent / "data" / "logs"
LOG_FILE = LOG_DIR / "app.log"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s [req:%(req_id)s]"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
```

> **说明**：`req_id` 字段由 `RequestIdFilter`（见 4.6）注入；Filter 必须挂在 root logger 上才能在 formatter 中读到该属性。

### 4.2 `backend/log_routes.py`（约 80 行）

**2 个 API**：

#### `GET /api/logs/tail?lines=100`
- 读取 `data/logs/app.log`（当前文件）最后 N 行
- 用 `collections.deque(open(...), maxlen=N)` 一次性高效读
- 返回 `{"lines": ["...", "..."], "total_bytes": ..., "file": "app.log"}`
- N 范围 [1, 500]，默认 100
- 文件不存在返回 `{"lines": [], "total_bytes": 0, "file": null}`

#### `GET /api/logs/export`
- 列出 `data/logs/` 下 `app.log` + `app.log.*`（最多 4 个：当前 + 3 备份）
- 临时 zip 路径：`tempfile.NamedTemporaryFile(suffix=".zip", dir=LOG_DIR, delete=False)`（也放在 `data/logs/` 下，跟正式日志一起，便于排查）
- 用 `zipfile.ZipFile(临时路径, "w", zipfile.ZIP_DEFLATED)` 打包
- 文件名按日期排序后加入 zip（`app-2026-06-07.log`、`app-2026-06-08.log`、`app-2026-06-09.log`、`app.log`）
- 返回 `FileResponse(临时路径, media_type="application/zip", filename="logs-export-{today}.zip")` + `BackgroundTask(清理临时文件)`
- 若 `data/logs/` 为空，返回 404 + `{"detail": "暂无日志"}`

### 4.3 `main.py` 改造点（最小侵入）

1. 删 `logging.basicConfig(...)`（旧 4-11 行）
2. 删第三方日志静默（迁移到 `configure_logging` 内部）
3. 新增 import：`from logging_setup import configure_logging, get_logger`
4. `@app.on_event("startup")` 开头调 `configure_logging()`
5. 模块级 `log = get_logger("main")`
6. 新增全局 exception_handler（见 4.5）
7. 业务关键点埋 `log.info` / `log.warning`：
   - `upload_file`: "开始处理上传"/"上传成功"/"上传失败"
   - `import_emails`: "邮件导入开始"/"成功"
   - `search`: "搜索 query=xxx, top_k=N"
   - `chat`: "问答 query=xxx, mode=stream/sync"
   - **不**在每个 `except Exception` 重复打（交给全局 handler）
8. `raise HTTPException` 之前**不**加 log（避免重复）

### 4.4 `code_routes.py` 改造点

- 已有 `log = logging.getLogger("code_kb")` 保留不变
- 业务关键点补 log（如有遗漏）：
  - `scan_repo_endpoint`: 已用 `log.info(f"[scan] 启动扫描: repo=...")` 保留
  - `_run_scan` 各阶段 step 已有 log 保留
  - `delete_repo_endpoint`: 已用 `log.info("[delete] ...")` 保留
- **不**新增 broadcast / SSE 端点
- `tracker.flush(status="error")` 保留不动（写 metrics.db 是它的本职）；**未捕获的 Exception** 统一由 `main.py` 全局 `exception_handler` 记 log（request_id 自动关联 metrics 里的同 id 记录）

### 4.5 全局 exception_handler（核心减法）

在 `main.py` 顶部注册 1 次：

```python
@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    rid = request_id_var.get()  # 来自 contextvars
    log = get_logger("main")
    log.exception(f"unhandled path={request.url.path} request_id={rid}")
    return JSONResponse(
        status_code=500,
        content={"detail": "内部错误", "request_id": rid},
    )
```

**作用**：
- 覆盖所有路由的 `except Exception` 路径
- 自动带 stack trace + request_id
- 路由里的 `except` 可以**只保留** `raise HTTPException(500, ...)` 那一行（不再写 log）

### 4.6 request_id 联动（contextvars）

```python
# backend/logging_setup.py
import contextvars
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.req_id = request_id_var.get()
        return True
```

**FastAPI middleware**（新增在 main.py）：
```python
@app.middleware("http")
async def request_id_middleware(request, call_next):
    rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
    token = request_id_var.set(rid)
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    request_id_var.reset(token)
    return response
```

**日志格式调整**：在 `LOG_FORMAT` 末尾追加 ` [req:%(req_id)s]`，自动出现在每条日志。

**StepTracker 联动**（可选简化）：不强制改 StepTracker；metrics.db 里 request_id 已经存在，排查时通过 `grep "[req:abc123]"` 可关联回 metrics 表。

### 4.7 `code_mcp.py` 改造点

- 入口加 `log = get_logger("mcp")`
- 三个埋点：
  - **tool 调用入口**：`log.info(f"tool_call name={name} args={...}")`
  - **JSON-RPC 解析失败**：`log.warning(f"jsonrpc_parse_error payload={...}")`
  - **SSE 连接断开**：`log.info(f"sse_disconnect client={...}")`

### 4.8 前端抽屉

**新增 2 个按钮**（顶栏，位置参考 `frontend/index.html` 现有顶栏）：

```html
<button id="btn-log-toggle" class="...">📜 日志</button>
<button id="btn-log-export" class="...">⬇ 导出</button>
```

**折叠状态**：`localStorage["kb_log_collapsed"]`，默认折叠。

**展开行为**：
1. 调 `GET /api/logs/tail?lines=100` 填面板
2. `setInterval(2000)` 持续轮询（折叠时清除 interval）
3. 颜色：正则 `/\[(ERROR|CRITICAL)\]/` → `text-red-600`；`/\[WARN(ING)?\]/` → `text-amber-500`
4. 复用 Tailwind 类，不引新 CSS

**导出行为**：
```js
window.location.href = '/api/logs/export';
// 浏览器自动弹"另存为"，让用户选文件夹
```

## 5. 数据流

### 5.1 日志写入流

```
业务代码 log.info("...")
   ↓
root logger (logging.getLogger())
   ↓
Filter (RequestIdFilter) 注入 req_id
   ↓
├─ TimedRotatingFileHandler (midnight, 3) → data/logs/app.log
└─ StreamHandler (stdout) → terminal
```

### 5.2 日志读取流（前端拉取）

```
前端 setInterval(2000)
   ↓
GET /api/logs/tail?lines=100
   ↓
后端: deque(open(data/logs/app.log), maxlen=100)
   ↓
{"lines": [...], "total_bytes": N}
   ↓
前端: 渲染到 <pre>，按正则染色
```

### 5.3 导出流

```
前端: window.location.href = '/api/logs/export'
   ↓
后端: 列出 data/logs/ 下 app.log + app.log.*
   ↓
zipfile.ZipFile(临时文件) 写入
   ↓
FileResponse(临时文件, media_type="application/zip", filename="logs-export-2026-06-09.zip")
   ↓
BackgroundTask: 删临时文件
   ↓
浏览器: 弹"另存为"对话框 → 用户选目录 → 下载
```

## 6. 错误处理

| 场景 | 处理 |
|------|------|
| `configure_logging()` 调多次 | idempotent，重复调直接 return |
| `data/logs/` 不存在 | `configure_logging()` 内 `makedirs(exist_ok=True)` |
| `app.log` 不存在（首次启动） | `tail` 返回空 list，不报错 |
| `app.log` 被外部删/锁 | `tail` 捕获 `OSError` 返回 500 + log.exception |
| 导出时空目录 | 404 + `{"detail": "暂无日志"}` |
| 全局 exception_handler 自身抛错 | fallback 走 FastAPI 默认 500 |
| 第三方库（jieba 等）DEBUG 日志噪音 | configure_logging 静默到 WARNING |
| SSE 替代品轮询遇网络断 | 前端 setInterval 自然跳过，下次拉取恢复 |

## 7. 测试计划

**`backend/tests/test_logging.py`**（5 个用例）：

| # | 测试 | 方法 |
|---|------|------|
| T1 | `configure_logging()` 调两次不重复加 handler | 调 2 次，断言 `len(root.handlers) == 2` |
| T2 | `tail` 读最后 N 行正确 | 写 10 行到临时 `app.log`，调 `tail(3)` 断言返回最后 3 行 |
| T3 | `export` 接口返回 zip 且 Content-Disposition 含 filename | 调接口，断言 `Content-Type: application/zip` + `Content-Disposition: attachment; filename=logs-export-*.zip` |
| T4 | 异常 handler 触发后日志带 `[req:xxx]` 前缀 | 用 `caplog` 捕获，触发未处理异常，断言日志记录含 `req:` |
| T5 | 轮转 backupCount 生效 | mock time 触发 4 次 `doRollover`，断言目录下只剩 3 个备份文件 + 1 个当前 |

**手动验证清单**：
- [ ] `python3 main.py` 启动后 `data/logs/app.log` 自动创建
- [ ] 触发上传/搜索/问答/邮件导入/扫描/取消，每个动作至少有 1 条 INFO 日志
- [ ] 手动抛错时，全局 handler 抓到 1 条 ERROR + stack trace
- [ ] 等 1 次午夜（或 mock 时间），看到 `app.log.2026-06-XX` 文件生成
- [ ] 当备份数 = 3 时再触发一次，**最老的备份被删**（backupCount 起作用）
- [ ] 前端点 📜 展开：看到 100 条最近日志
- [ ] 触发了新动作后 2 秒内：面板上自动追加
- [ ] 点 ⬇ 导出：浏览器弹"另存为"对话框，文件名 `logs-export-2026-06-09.zip`

## 8. 验收标准

- [ ] 所有 5 个 pytest 用例通过
- [ ] 所有手动验证清单勾选完成
- [ ] main.py 启动时间 < 5 秒（日志初始化不阻塞）
- [ ] 日志写入对业务性能影响 < 1%（handler 走异步 flush 默认）
- [ ] `data/logs/` 目录大小：3 天滚动后 ≤ 50 MB（demo 体量预期）
- [ ] 前端"日志"按钮折叠状态刷新页面后保留
- [ ] 导出 zip 在 macOS Finder 解压正常，文件名按日期排序

## 9. 实施步骤预览

1. 写 `backend/logging_setup.py`（SSOT + idempotent + request_id filter）
2. 写 `backend/log_routes.py`（tail + export）
3. 在 `main.py` 删旧 logging 配置、注册 middleware、注册 exception_handler、注册 router
4. 在 `code_routes.py` 删冗余 `except` 中的 log（统一交给 handler）
5. 在 `code_mcp.py` 加 3 个埋点
6. 写 `backend/tests/test_logging.py` 5 个用例
7. 在 `frontend/index.html` 加 2 按钮 + 抽屉 + 染色 + 轮询 + 导出
8. 跑 `pytest`，跑 `python3 main.py` 手动 smoke test

## 10. 风险与回滚

| 风险 | 缓解 |
|------|------|
| logging 重复配置导致日志写多份 | configure_logging idempotent 检查 |
| 大量日志拖慢 IO | 单条 INFO < 1KB，handler 默认带缓冲；日活 100 次请求 ≈ 100KB |
| 临时 zip 文件残留 | `BackgroundTask` 在响应后清理 |
| 轮询频率太高反而卡 | 2 秒间隔 + 折叠时清除 interval |
| request_id 与 StepTracker 不一致 | 同一 middleware 内生成；不修改 StepTracker |
| 前端下载走 `window.location` 触发新导航 | 接受：本来就是下载行为；如要避免可改 `<a download>` + fetch blob |
| 导出大文件阻塞响应 | 临时文件写完再返回；FastAPI `BackgroundTask` 不阻塞发送 |

## 11. 参考与背景

- `backend/main.py`：现状入口，需要删旧 logging 配置
- `backend/code_routes.py`：现状后台线程 + SSE，已有 log
- `backend/code_mcp.py`：MCP SSE 端点，本次要埋 3 个点
- `backend/step_tracker.py`：已有的 request_id 源（不动）
- `backend/metrics_db.py`：性能追踪（不动）
- Python 官方 `logging.handlers.TimedRotatingFileHandler` 文档
