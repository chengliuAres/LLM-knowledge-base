# 代码仓库增量刷新 + Git Watchdog 自动刷新设计

> 日期：2026-06-10
> 作者：柳哥
> 状态：待 review

## 背景

已索引的代码仓库在「code-repos」tab 点击「刷新」按钮时，前端 toast 报错：

```
刷新完成: undefined chunks
```

排查后定位到根因：

- `POST /api/code/repos/{name}/refresh` 端点（`backend/code_routes.py:878-892`）内部 `return await scan_repo_endpoint(req)`
- `scan_repo_endpoint`（`backend/code_routes.py:377-408`）启动后台线程后**立即返回** `{status, scan_id, repo_name, message}`，**响应里没有 `total_chunks` 字段**
- 前端 `codeRefreshRepo`（`code-repos.html:562-574`，`showToast` 在 569 行）期望 `data.total_chunks` → 拿到 `undefined`

**值得注意**：

- 后端增量逻辑**已经实现**：`compute_incremental`（`backend/code_config.py:129-172`）按 mtime diff 输出 added/updated/deleted/skipped 四类；`_run_scan`（`backend/code_routes.py:126-317`）走的就是它
- 现在的「刷新」**实际就是异步增量**，不是全量重建
- 所以「Bug」和「功能缺」其实是两件事：
  1. **Bug**：toast 拿错字段（应当走 SSE 等异步结果）
  2. **缺**：缺少"git 仓库变更自动触发刷新"的能力

## 目标

1. 修掉 toast undefined 的根因；前端体验与"开始扫描"一致（SSE 进度 + 真实 chunks 数字）
2. 对 git 仓库实现后台 watchdog：每 N 秒轮询 `git status --porcelain`，变更时自动触发增量扫描
3. 已有增量逻辑（`compute_incremental` + `_run_scan`）零修改复用

## 设计

### 1. 架构

```
┌──────────────────────────────────────────────────────────┐
│  前端  code-repos.html                                   │
│  ┌────────────────┐   ┌──────────────────────────────┐  │
│  │  仓库列表卡片   │   │  执行流程面板（SSE 步骤）    │  │
│  │  [刷新][删除]   │   │  parsing/embedding/done ...  │  │
│  └────────┬───────┘   └──────────┬───────────────────┘  │
│           │ click 刷新           │ 复用扫描 SSE         │
└───────────┼──────────────────────┼──────────────────────┘
            │ POST /refresh        │
            ▼                      │
┌──────────────────────────────────────────────────────────┐
│  后端                                                     │
│  ┌──────────────┐    ┌────────────────────────────────┐  │
│  │ /refresh     │    │ GitWatchdog (后台线程)         │  │
│  │ 端点          │    │ - 每轮重新识别 git 仓库        │  │
│  │              │    │ - 每 Ns 轮询 status --porcelain │  │
│  │  await       │    │ - 变更 → debounce 5s →         │  │
│  │  scan_repo   │    │   调 _start_scan_job (同步)   │  │
│  │  (async)     │    │   (走与手动同一条路径)         │  │
│  └──────┬───────┘    └────────────┬───────────────────┘  │
│         ▼                          ▼                    │
│  ┌──────────────────────────────────────────────────┐   │
│  │ scan_repo_endpoint (权威入口 / 唯一 SSoT)        │   │
│  │ - 后台线程 + SSE 推送 + 锁 + mtime 增量 diff     │   │
│  │ - watchdog 遇锁冲突 → 下一轮轮询自动重 schedule │  │
│  └──────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
```

**核心设计原则**：

- **单一权威入口**：手动刷新 + watchdog 都最终走 `scan_repo_endpoint`，增量逻辑只有一处实现
- **副作用分离**：watchdog 只负责检测 + 触发，不复制扫描逻辑
- **现有复用最大化**：`compute_incremental` 已是 mtime 增量，不重写

### 2. 数据契约

**`POST /api/code/repos/{name}/refresh` 返回**（修改后）：

```json
{
  "status": "started",
  "scan_id": "a1b2c3d4",
  "repo_name": "email-wiki-demo",
  "message": "扫描已启动，通过 SSE 获取实时进度"
}
```

> **注**：原 `scan_repo_endpoint` 返回里没有 `source` 字段（已核实 `code_routes.py:403-408`）。本次**不**改返回结构 — 前端通过订阅 SSE 的 `done` 事件拿真实结果即可，watchdog 触发源在服务端 log 里区分（`log.info("[scan:watchdog] xxx")`）。

**`POST /api/code/scan/{scan_id}/sse` 的 `done` 事件**（前端 toast 用的真实数据）：

```json
{
  "status": "completed",
  "error": "",
  "stats": {
    "total_chunks": 1234,
    "total_repos": 1,
    "by_language": {"python": 1200, ...},
    "by_chunk_type": {"function": 800, ...},
    "by_repo": {"email-wiki-demo": 1234}
  }
}
```

> **`stats` 字段结构来自 `code_db.py:607-627` 的 `get_stats()`**：包含 `total_chunks / total_repos / by_language / by_chunk_type / by_repo`，**没有 `total_files`**。前端用 `data.stats.total_chunks` 即可。

**`code_repos.json` 新增 `watchdog` 段**（顶层全局默认）：

```json
{
  "repos": { "email-wiki-demo": { /* 既有 */ } },
  "file_mtimes": { /* 既有 */ },
  "watchdog": {
    "interval_seconds": 60,
    "debounce_seconds": 5,
    "repos": {}
  }
}
```

- **顶层默认**：`interval_seconds` / `debounce_seconds` 是全局值
- **`repos` 段**：保留为空对象 `{}`（预留给未来扩展；当前实现不在此存运行时状态）
- **git 识别**：每轮重新调用 `detect_git_repo(repo["repo_path"])`（看 `.git` 目录是否存在），不持久化识别结果
- **不**做 per-repo interval 覆盖 — 加层级但没真实需求（YAGNI）
- **关掉方式**：
  - 全局关：`watchdog.interval_seconds = 0`（watchdog 启动后立即退出主循环）
  - 单个 repo 关：把 repo 从 `code_repos.json` 里删掉（或目录里删 `.git`）

### 3. 关键算法

**Watchdog 启动**：FastAPI `lifespan` startup（`backend/main.py:44-52`，当前无清理逻辑需补充）：

```python
shutdown_event = threading.Event()
watchdog_thread = threading.Thread(target=watchdog_loop, args=(shutdown_event,), daemon=True)
watchdog_thread.start()
```

**Watchdog 主循环**（伪代码）：

```python
def watchdog_loop(shutdown_event):
    cfg = load_config()
    interval = cfg.get("watchdog", {}).get("interval_seconds", 60)
    debounce = cfg.get("watchdog", {}).get("debounce_seconds", 5)

    # 全局开关
    if interval <= 0:
        log.info("[watchdog] interval_seconds=0, watchdog 禁用")
        return

    pending: dict[str, threading.Timer] = {}  # 一次性 debounce timer
    last_porcelain: dict[str, str] = {}  # 内存缓存（不持久化，见下方"重启行为"）

    while not shutdown_event.is_set():
        # 每轮 reload config，捕获"新增 repo / 被删 repo"变化
        cfg = load_config()

        for name, repo in cfg["repos"].items():
            # 启动时 + 每轮重新识别 git 仓库
            is_git = detect_git_repo(repo["repo_path"])  # .git 目录存在?
            if not is_git:
                continue

            try:
                porcelain = run_git_status_porcelain(repo["repo_path"])
            except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
                log.warning(f"[watchdog] {name}: {e}")
                continue

            if last_porcelain.get(name) == porcelain:
                continue

            # 变更 → 重新 schedule（取消上一次 timer）
            last_porcelain[name] = porcelain
            _schedule_scan(name, debounce, pending)

        # 清理被删 repo 的 pending
        for stale in list(pending.keys()):
            if stale not in cfg["repos"]:
                pending.pop(stale, None)
                last_porcelain.pop(stale, None)

        shutdown_event.wait(timeout=interval)  # 可被 shutdown 唤醒
```

**`schedule_scan` 伪代码**：

```python
def _schedule_scan(name, debounce, pending):
    if name in pending:
        pending[name].cancel()  # 取消上一次未触发的 timer（Timer.cancel 返回 False 表示已 fire，无害）
    t = threading.Timer(debounce, _do_scan, args=(name, pending))
    pending[name] = t
    t.start()

def _do_scan(name, pending):
    """被 timer 线程调用；需要拿锁 + 复用 scan_repo 路径"""
    # 1. 拿锁（与手动刷新共享同一把锁）
    if not try_acquire_scan_lock(name):
        log.info(f"[watchdog] {name} 锁冲突，下一轮重试")
        return  # 下一轮轮询自然重 schedule（porcelain 仍 != last_porcelain）

    try:
        # 2. 走 refresh 端点同款路径（同步入口，因为是后台线程不能 await）
        repo_cfg = get_repo_config(name)
        if not repo_cfg:
            log.info(f"[watchdog] {name} 仓库已被删除，跳过")
            return  # 仓库已被删除

        req = ScanRequest(
            repo_name=name,
            repo_path=repo_cfg["repo_path"],
            project_type=repo_cfg.get("project_type", "generic"),
            languages=repo_cfg.get("languages", []),
        )
        # 抽出的同步入口（见下方"实现细节"）
        scan_id = _start_scan_job(req)
        log.info(f"[watchdog] {name} 触发扫描, scan_id={scan_id}, source=watchdog")
    except Exception as e:
        log.exception(f"[watchdog] {name} 扫描失败: {e}")
    finally:
        pending.pop(name, None)
        # 锁由 _run_scan 后台线程的 finally 释放（code_routes.py:309），这里不重复释放
```

**实现细节：watchdog 同步入口**

`_run_scan`（`code_routes.py:126`）是普通 `def`，只在后台线程里跑。watchdog 复用方式：

- **方案 A（推荐）**：从 `scan_repo_endpoint`（`code_routes.py:377-408`）抽出"建 ScanJob + 启 thread + 返回 scan_id"逻辑，命名为 **`_start_scan_job(req) -> scan_id`**（**同步入口**，返回 `scan_id`），让 watchdog 线程直接调它
- `scan_repo_endpoint` 内部改为：

  ```python
  @router.post("/scan")
  async def scan_repo_endpoint(req: ScanRequest):
      # ... 锁检查等前置逻辑保持不变 ...
      scan_id = _start_scan_job(req)  # 新增：调抽出的同步函数
      return {"status": "started", "scan_id": scan_id, "repo_name": req.repo_name, "message": "..."}
  ```

- **锁职责唯一化**：watchdog 拿到锁后**只起 job**，锁的释放由 `_run_scan` 的 `finally`（`code_routes.py:309`）负责 — 避免双重释放
- **零行为变更**，纯粹抽函数 + 加一个调用点

**重启行为**：`last_porcelain` 是**内存变量**，**不持久化**。进程重启后第一次轮询必然触发一次扫描（即使仓库没新变更），这是可以接受的"冷启动"成本。

**手动 vs 自动去重**：用户在 debounce 期间手动点刷新 → `codeRefreshRepo` → `POST /refresh` → 走 `scan_repo_endpoint` 路径（**在 watchdog 拿到锁之前**会先抢到锁）→ watchdog 后续 `_do_scan` 触发时锁冲突 → 直接 return，等下一轮。如果用户手动那次扫完后 porcelain 仍与 last_porcelain 不同（用户又改了文件），下一轮轮询会再 schedule。

**前端代码改动点**（按影响面排序）：

| 文件 | 改动 | 影响 |
|------|------|------|
| `code-repos.html` `codeRefreshRepo` (562-574) | 改为：调 `/refresh` → 拿到 `scan_id` → 订阅 `/api/code/scan/{id}/sse` → 收到 `done` 事件时用 `data.stats.total_chunks` toast | 修根因 + 体验与 `codeScanRepo` (296-371) 一致 |

> **不**新增 `__TAB_VERSION` — 全项目无此机制（已 grep 验证 `frontend/tabs/*.html` 都没有 `__TAB_VERSION`），保持最小改动。
>
> **不**新增全局 SSE `/api/code/sse/watchdog` 端点 — YAGNI。watchdog 自动刷新的进度复用扫描 SSE 即可，前端在已有「执行流程面板」里能直接看到。

### 4. 错误处理

| 场景 | 行为 |
|------|------|
| 仓库非 git 目录 | 每轮 `detect_git_repo` 返回 False → 跳过；不进 `pending` |
| `git status` 失败（命令缺失 / timeout） | log warning，下一轮重试；不抛错 |
| watchdog `_do_scan` 时手动扫描在跑 | `try_acquire_scan_lock` 返回 False → log + return；porcelain 仍 != last_porcelain → 下一轮自动重 schedule |
| `_do_scan` 期间仓库被 `DELETE /api/code/repos/{name}` 删了 | `_do_scan` 内 `get_repo_config` 返回 None → return（不抛错） |
| 仓库目录被删（文件系统） | `run_git_status_porcelain` 抛 OSError → log + skip，下一轮重试 |
| 锁重入 / 释放异常 | `release_scan_lock`（`code_config.py:181-187`）已 try/except RuntimeError |
| `watchdog.interval_seconds = 0`（全局） | watchdog 启动后立即 return，不进入主循环 |
| 单个 repo 非 git（`.git` 不存在） | `detect_git_repo` 返回 False → 轮询跳过该 repo |
| 进程退出 / lifespan shutdown | `daemon=True` 线程随主进程退出；`shutdown_event.wait()` 替代裸 `sleep` 可立即响应 shutdown |
| SSE 断连 | 浏览器 `EventSource` 内建自动重连；前端**不**额外实现（依赖默认行为） |
| 进程冷启动（last_porcelain 为空） | 首次轮询时真实 porcelain 必非空 → 触发**第一次扫描**（这是想要的行为：让 git 仓库有初始索引） |

### 5. 测试策略

| 测试 | 验证 |
|------|------|
| 单元：mock `git status` 输出变化 | watchdog 调度 timer，timer 触发后调 `_start_scan_job`（抽取后的函数） |
| 单元：连续 3 次 porcelain 变化在 5s 内 | `Timer.cancel()` + 新 Timer → 只触发 1 次 scan（验证 `pending` 字典 + cancel 正确） |
| 单元：模拟锁冲突（`try_acquire_scan_lock` 返回 False） | `_do_scan` return，porcelain 仍 != last → 下一轮自动重 schedule |
| 单元：watchdog 主循环识别 git 仓库 | `detect_git_repo` 对含/不含 `.git` 的目录返回正确 boolean；非 git repo 跳过 |
| 单元：lifespan startup/shutdown | `shutdown_event.set()` 后线程在 1s 内退出 |
| 集成：手动点刷新（前端） | toast 显示真实 chunks（不是 undefined）；走 SSE 路径；与 `codeScanRepo` 体验一致 |
| 集成：watchdog 端到端 | 真实 git 仓库 + 改文件 + 等 5s debounce + 60s 轮询 → 索引更新（CI 跑要 mock `subprocess.run`） |
| 集成：watchdog 遇锁冲突 | 手动扫描跑中 → watchdog 触发 → 锁冲突 log + 跳过 → 手动结束后下一轮 watchdog 成功 |

**测试实现注意**：

- 「mock `git status`」必须 mock 掉 `subprocess.run` / `subprocess.check_output`（取决于实现），不要真的调用 git
- 「端到端 git 切换分支」CI 跑要 mock，**不能**真启 60s 轮询
- 验收用**真实环境**跑：scan 一个 git 仓库 → 改文件 → 等 ≤ 70s → 索引更新

## 不做的事（YAGNI）

- ❌ 不实现 git hook 推送事件（要每个仓库手动装 hook，不友好）
- ❌ 不做文件级 inotify/FSEvents 监听（要新依赖 + 跨平台坑）
- ❌ 不区分"新增文件"和"修改文件"的细分通知（toast 报"added N / updated M / deleted K"即可）
- ❌ 不做 watchdog 触发时的"是否要立即扫描"弹窗确认（trust user 已选 git 仓库即代表同意自动刷新）
- ❌ **不**做 per-repo `interval_seconds` 覆盖（全局默认够用；加层级但无真实需求）
- ❌ **不**做 `GET /api/code/repos/{name}/watchdog-status` 端点（YAGNI：前端不需要单独查询，状态在 log + SSE 步骤里都有）
- ❌ **不**做全局 SSE `/api/code/sse/watchdog`（自动刷新的进度复用扫描 SSE 即可，避免双通道）
- ❌ **不**做 `__TAB_VERSION` bump（项目无此机制，且本次只是改一个文件的方法体，不需 cache bust）
