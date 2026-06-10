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

- `POST /api/code/repos/{name}/refresh` 端点（`backend/code_routes.py:892`）内部直接 `return await scan_repo_endpoint(req)`
- `scan_repo_endpoint` 启动后台线程后**立即返回** `{status, scan_id, repo_name, message}`，**响应里没有 `total_chunks` 字段**
- 前端 `codeRefreshRepo`（`code-repos.html:569`）期望 `data.total_chunks` → 拿到 `undefined`

**值得注意**：

- 后端增量逻辑**已经实现**：`compute_incremental`（`backend/code_config.py:129-172`）按 mtime diff 输出 added/updated/deleted/skipped 四类；`_run_scan` 走的就是它
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
│           │ click 刷新           │ 自动刷新 SSE 事件    │
└───────────┼──────────────────────┼──────────────────────┘
            │ POST /refresh        │
            ▼                      │
┌──────────────────────────────────────────────────────────┐
│  后端                                                     │
│  ┌──────────────┐    ┌────────────────────────────────┐  │
│  │ /refresh     │    │ GitWatchdog (后台线程)         │  │
│  │ 端点          │    │ - 每 Ns 轮询 is_git_repo       │  │
│  │              │    │ - git status --porcelain       │  │
│  │  直接调        │    │ - 变更 → debounce 5s →         │  │
│  │  scan_repo    │    │   调 scan_repo (复用入口)     │  │
│  └──────┬───────┘    └────────────┬───────────────────┘  │
│         ▼                          ▼                    │
│  ┌──────────────────────────────────────────────────┐   │
│  │ scan_repo_endpoint (权威入口 / 唯一 SSoT)        │   │
│  │ - 后台线程 + SSE 推送 + 锁 + mtime 增量 diff     │   │
│  │ - watchdog 遇 409 → 跳过本轮，下轮重试            │   │
│  └──────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
```

**核心设计原则**：

- **单一权威入口**：手动刷新 + watchdog 都走 `scan_repo_endpoint`，增量逻辑只有一处实现
- **副作用分离**：watchdog 只负责检测 + 触发，不复制扫描逻辑
- **现有复用最大化**：`compute_incremental` 已是 mtime 增量，不重写

### 2. 数据契约

**`POST /api/code/repos/{name}/refresh` 返回**（修改后）：

```json
{
  "status": "started",
  "scan_id": "a1b2c3d4",
  "repo_name": "email-wiki-demo",
  "source": "manual",
  "message": "扫描已启动，通过 SSE 获取实时进度"
}
```

新增 `source` 字段（`"manual"` / `"watchdog"`），方便前端和日志区分触发来源。

**新增 `GET /api/code/repos/{name}/watchdog-status`**（供前端可选展示）：

```json
{
  "is_git_repo": true,
  "watching": true,
  "last_check_at": "2026-06-10T14:30:00",
  "last_changed_at": "2026-06-10T14:25:13",
  "last_scan_source": "watchdog",
  "interval_seconds": 60
}
```

**`code_repos.json` 新增 `watchdog` 段**（全局默认值，`repos[name]` 可覆盖）：

```json
{
  "repos": { "email-wiki-demo": { /* 既有 */ } },
  "file_mtimes": { /* 既有 */ },
  "watchdog": {
    "interval_seconds": 60,
    "debounce_seconds": 5,
    "repos": {
      "email-wiki-demo": {
        "interval_seconds": 60,
        "last_check_at": "...",
        "last_porcelain": "M  README.md"
      }
    }
  }
}
```

- 字段读取顺序：优先用 `repos[name].interval_seconds`（per-repo 配置），未配置则用顶层默认
- `interval_seconds: 0` 表示该 repo 关闭自动刷新

### 3. 关键算法

**Watchdog 轮询循环**（伪代码）：

```python
# 启动时机：FastAPI lifespan startup
# 优雅停止：lifespan shutdown

def watchdog_loop():
    while not shutdown_event.is_set():
        for repo in enabled_repos:
            if not repo.is_git: continue
            try:
                porcelain = run_git_status_porcelain(repo.path)
                if porcelain == repo.last_porcelain:
                    continue
                # 变更 → 触发（带 debounce）
                schedule_scan(repo, source="watchdog", delay=5)
                repo.last_porcelain = porcelain
            except GitError as e:
                log.warning(f"[watchdog] {repo.name}: {e}")
        sleep(interval_seconds)

def schedule_scan(repo, source, delay):
    """5s 内多次变更合并为一次"""
    if repo.name in pending:
        cancel(pending[repo.name].timer)  # 取消上一次
    t = Timer(delay, do_scan, args=(repo, source))
    pending[repo.name] = Pending(source=source, timer=t)
    t.start()

def do_scan(repo, source):
    pending.pop(repo.name, None)
    if try_acquire_scan_lock(repo.name) is False:
        log.info(f"[watchdog] {repo.name} 锁冲突，跳过本轮")
        return  # 下一轮重试
    # 调 scan_repo_endpoint（已存在）
    # 失败：释放锁 + 记录错误
```

**手动 vs 自动去重**：用户在 debounce 期间手动点刷新 → 走 `scan_repo_endpoint`（拿锁），同时取消 pending 的 watchdog timer（避免双扫）。

**前端代码改动点**（按影响面排序）：

| 文件 | 改动 | 影响 |
|------|------|------|
| `code-repos.html` | `codeRefreshRepo` 改为创建虚拟 `scan_id`、订阅 `/api/code/scan/{id}/sse`、完成后用 `data.stats` toast | 修根因 + 体验一致 |
| `code-repos.html` | 订阅全局 SSE `/api/code/sse/watchdog`，收到 `auto_refresh_started` 时把执行流程面板展开 | 自动刷新通知 |
| `code-repos.html` | `__TAB_VERSION` bump（按前端规范） | 强制刷新 cache |

### 4. 错误处理

| 场景 | 行为 |
|------|------|
| 仓库非 git 目录 | watchdog 跳过该 repo，标 `is_git_repo=false` |
| `git status` 失败 | log 警告，下一轮重试；不抛错 |
| watchdog 触发时手动扫描正在跑 | 锁冲突，watchdog 本轮跳过，下轮重试 |
| 仓库目录被删 | 404，watchdog 自动 `remove_repo` |
| SSE 通道断连 | 前端自动重连；watchdog 独立线程不受影响 |
| debounce 期间用户手动点刷新 | 手动走 `scan_repo_endpoint`，同时取消 pending 的 watchdog timer |
| `interval_seconds` 设为 0 | watchdog 不启动该 repo（off 开关） |

### 5. 测试策略

| 测试 | 验证 |
|------|------|
| 单元：mock `git status` 输出变化 | watchdog 调度 timer，timer 触发后调用 `scan_repo_endpoint` |
| 单元：连续 3 次 porcelain 变化在 5s 内 | 只触发 1 次 scan |
| 单元：模拟锁冲突 | 返回 False，下一轮重试 |
| 集成：手动点刷新 | 修 toast undefined；走 SSE；完成后显示真实 chunks |
| 集成：端到端 git 切换分支 | watchdog 检测 → 自动扫描 → 索引更新 |
| 前端：`__TAB_VERSION` bump 后 | 强制刷 cache，HTML 加载新版本 |

## 不做的事（YAGNI）

- ❌ 不实现 git hook 推送事件（要每个仓库手动装 hook，不友好）
- ❌ 不做文件级 inotify/FSEvents 监听（要新依赖 + 跨平台坑）
- ❌ 不区分"新增文件"和"修改文件"的细分通知（toast 报"added N / updated M / deleted K"即可）
- ❌ 不做 watchdog 触发时的"是否要立即扫描"弹窗确认（trust user 已选 git 仓库即代表同意自动刷新）
