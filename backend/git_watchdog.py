"""Git Watchdog: 后台轮询 git 仓库变更并自动触发增量扫描

- 配置文件: data/code_repos.json 顶层 watchdog 段
- 启动: FastAPI lifespan startup（在 main.py 里调用 start_watchdog()）
- 关闭: lifespan shutdown（调用 stop_watchdog()）
- 触发路径: watchdog → _start_scan_job (code_routes.py 同步入口) → _run_scan 后台线程
"""

import os
import json
import time
import logging
import threading
import subprocess
from typing import Optional

# 项目根目录 + 配置文件路径（测试时 monkeypatch）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
CONFIG_PATH = os.path.join(DATA_DIR, "code_repos.json")

log = logging.getLogger("code_kb.watchdog")


# ── 工具函数（独立可测） ─────────────────────────────────────────

def detect_git_repo(path: str) -> bool:
    """判断目录是否是 git 仓库（看 .git 子目录是否存在）"""
    return os.path.isdir(os.path.join(path, ".git"))


def run_git_status_porcelain(path: str) -> str:
    """调用 git status --porcelain --untracked-files=no

    Raises:
        subprocess.CalledProcessError: git 命令返回非零
        FileNotFoundError: git 命令不存在
        OSError: 目录不存在
    """
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return result.stdout


def load_watchdog_config() -> dict:
    """从 code_repos.json 读取 watchdog 段；不存在则返回默认"""
    if not os.path.exists(CONFIG_PATH):
        return {"interval_seconds": 60, "debounce_seconds": 5}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        wd = data.get("watchdog", {})
        return {
            "interval_seconds": wd.get("interval_seconds", 60),
            "debounce_seconds": wd.get("debounce_seconds", 5),
        }
    except (json.JSONDecodeError, OSError):
        return {"interval_seconds": 60, "debounce_seconds": 5}


def load_repo_configs() -> dict:
    """从 code_repos.json 读取所有 repo 配置

    Returns:
        {repo_name: {"repo_path": ..., "project_type": ..., "languages": [...]}, ...}
    """
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("repos", {})
    except (json.JSONDecodeError, OSError):
        return {}


# ── 调度逻辑 ────────────────────────────────────────────────────

# 锁失败回退集合：_do_scan 拿不到锁时把 repo name 加进来，
# watchdog_loop 主循环末尾取出这些 name 重新 schedule。
# 用模块级 set 是因为 _do_scan 在 timer 线程、watchdog_loop 在主线程，
# 跨线程通讯用模块级 set（set.add 是原子的）。
_lock_failed: set[str] = set()


def _schedule_scan(name: str, debounce: int, pending: dict) -> None:
    """为单个 repo schedule 一次扫描（带 debounce）

    Args:
        name: 仓库名
        debounce: debounce 秒数
        pending: {name: threading.Timer} 字典（外部传入，方便测试）
    """
    if name in pending:
        pending[name].cancel()  # 取消上一次未触发的 timer
    t = threading.Timer(debounce, _do_scan, args=(name, pending))
    pending[name] = t
    t.start()


def _do_scan(name: str, pending: dict) -> None:
    """被 timer 线程调用：拿锁 + 调 _start_scan_job

    锁管理：
    - 拿锁失败 → 不持锁，直接 return（外层 finally 兜底 pop pending）
    - 拿锁成功 + 仓库被删 → 必须主动 release_scan_lock（外层没人接）
    - 拿锁成功 + 异常 → 必须主动 release_scan_lock（避免泄漏）
    - 拿锁成功 + _start_scan_job 成功 → 不释放（_run_scan 后台线程 finally 负责）
    """
    # 锁依赖 code_routes（避免循环 import 放函数内）
    from code_routes import try_acquire_scan_lock, _start_scan_job, release_scan_lock
    from code_config import get_repo_config
    from code_routes import ScanRequest

    try:
        if not try_acquire_scan_lock(name):
            log.info(f"[watchdog] {name} 锁冲突，下一轮重试")
            _lock_failed.add(name)  # 通知 watchdog_loop 主循环重 schedule
            return  # 走外层 finally 兜底 pop pending

        try:
            repo_cfg = get_repo_config(name)
            if not repo_cfg:
                log.info(f"[watchdog] {name} 仓库已被删除，跳过")
                # 深度防御：拿锁后任何 return 路径都要释放锁（避免泄漏）
                release_scan_lock(name)
                return

            req = ScanRequest(
                repo_name=name,
                repo_path=repo_cfg["repo_path"],
                project_type=repo_cfg.get("project_type", "generic"),
                languages=repo_cfg.get("languages", []),
            )
            scan_id = _start_scan_job(req)
            log.info(f"[watchdog] {name} 触发扫描, scan_id={scan_id}, source=watchdog")
            # 锁不归本函数管；释放由 _run_scan 后台线程 finally 块负责
        except Exception as e:
            # 兜底：拿锁后任何异常都要释放锁，避免泄漏
            release_scan_lock(name)
            log.exception(f"[watchdog] {name} 扫描失败: {e}")
    finally:
        pending.pop(name, None)


# ── 主循环 ──────────────────────────────────────────────────────

def watchdog_loop(
    shutdown_event: threading.Event,
    cfg_provider=None,
) -> None:
    """主循环：轮询 git 仓库变更 → schedule 扫描

    Args:
        shutdown_event: 外部传入的 Event，set 时线程退出
        cfg_provider: 配置提供者（默认读磁盘），测试时可注入
    """
    if cfg_provider is None:
        cfg_provider = load_watchdog_config

    cfg = cfg_provider()
    interval = cfg.get("interval_seconds", 60)
    debounce = cfg.get("debounce_seconds", 5)

    if interval <= 0:
        log.info("[watchdog] interval_seconds=0, watchdog 禁用")
        return

    pending: dict[str, threading.Timer] = {}
    last_porcelain: dict[str, str] = {}

    while not shutdown_event.is_set():
        # 每轮 reload config，捕获"新增 repo / 被删 repo"变化
        repos = load_repo_configs()

        for name, repo in repos.items():
            path = repo.get("repo_path", "")
            if not path or not detect_git_repo(path):
                continue

            try:
                porcelain = run_git_status_porcelain(path)
            except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
                log.warning(f"[watchdog] {name}: {e}")
                continue

            if last_porcelain.get(name) == porcelain:
                continue

            last_porcelain[name] = porcelain
            _schedule_scan(name, debounce, pending)

        # 清理被删 repo 的 pending（cancel timer 避免 fire 后 stale _do_scan 锁泄漏）
        for stale in list(pending.keys()):
            if stale not in repos:
                t = pending.pop(stale, None)
                if t is not None:
                    t.cancel()
                last_porcelain.pop(stale, None)

        # 重 schedule 任何在 _do_scan 锁失败的 repo
        # 流程：_do_scan 拿不到锁 → add 到 _lock_failed → 主循环末尾
        # 取消旧 timer + 重新 schedule + 清空集合（下一轮重新累积）
        if _lock_failed:
            for name in list(_lock_failed):
                if name in pending:
                    pending[name].cancel()
                _schedule_scan(name, debounce, pending)
            _lock_failed.clear()

        shutdown_event.wait(timeout=interval)


# ── 生命周期管理（供 main.py lifespan 调用） ───────────────────

_shutdown_event: Optional[threading.Event] = None
_watchdog_thread: Optional[threading.Thread] = None


def start_watchdog() -> None:
    """启动 watchdog 后台线程（幂等：重复调用不重启）"""
    global _shutdown_event, _watchdog_thread

    if _watchdog_thread and _watchdog_thread.is_alive():
        log.info("[watchdog] 已在运行，跳过启动")
        return

    _shutdown_event = threading.Event()
    _watchdog_thread = threading.Thread(
        target=watchdog_loop,
        args=(_shutdown_event,),
        daemon=True,
    )
    _watchdog_thread.start()
    log.info("[watchdog] 后台线程已启动")


def stop_watchdog(timeout: float = 2.0) -> None:
    """关闭 watchdog 线程（lifespan shutdown 调用）"""
    global _shutdown_event, _watchdog_thread

    if _shutdown_event is None:
        return

    _shutdown_event.set()
    if _watchdog_thread:
        _watchdog_thread.join(timeout=timeout)
        if _watchdog_thread.is_alive():
            log.warning("[watchdog] 线程未在 %ss 内退出，强制放弃", timeout)
    _shutdown_event = None
    _watchdog_thread = None
    log.info("[watchdog] 后台线程已停止")
