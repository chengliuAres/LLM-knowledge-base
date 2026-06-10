"""git_watchdog 模块测试

覆盖：
- detect_git_repo 识别 .git 目录
- run_git_status_porcelain 调用 git 命令
- _schedule_scan debounce 合并多次变更
- _do_scan 锁冲突时跳过
- watchdog_loop shutdown_event 1s 内退出
"""

import os
import sys
import time
import json
import pytest
import threading
import subprocess
from unittest.mock import patch, MagicMock

# backend/ 加 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    """用 tmp_path 隔离 data/ 目录"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def fresh_module(isolated_data_dir, monkeypatch):
    """重新加载 git_watchdog，配置路径指向 tmp"""
    import git_watchdog
    import importlib
    importlib.reload(git_watchdog)
    monkeypatch.setattr(git_watchdog, "DATA_DIR", str(isolated_data_dir))
    monkeypatch.setattr(git_watchdog, "CONFIG_PATH", str(isolated_data_dir / "code_repos.json"))
    return git_watchdog


# ── 工具函数测试 ─────────────────────────────────────────────────

def test_detect_git_repo_returns_true_for_git_directory(fresh_module, tmp_path):
    """含 .git 子目录返回 True"""
    (tmp_path / ".git").mkdir()
    assert fresh_module.detect_git_repo(str(tmp_path)) is True


def test_detect_git_repo_returns_false_for_normal_directory(fresh_module, tmp_path):
    """不含 .git 返回 False"""
    (tmp_path / "src").mkdir()
    assert fresh_module.detect_git_repo(str(tmp_path)) is False


def test_detect_git_repo_returns_false_for_nonexistent_path(fresh_module, tmp_path):
    """目录不存在返回 False（不抛错）"""
    fake = str(tmp_path / "nope")
    assert fresh_module.detect_git_repo(fake) is False


def test_run_git_status_porcelain_invokes_git(fresh_module, tmp_path, monkeypatch):
    """调用 subprocess.run 跑 git status --porcelain --untracked-files=no"""
    (tmp_path / ".git").mkdir()
    captured = {}
    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        m = MagicMock()
        m.stdout = "M  README.md\n"
        m.returncode = 0
        return m
    monkeypatch.setattr(subprocess, "run", fake_run)
    result = fresh_module.run_git_status_porcelain(str(tmp_path))
    assert result == "M  README.md\n"
    assert captured["cmd"] == ["git", "status", "--porcelain", "--untracked-files=no"]
    assert captured["cwd"] == str(tmp_path)


def test_run_git_status_porcelain_propagates_subprocess_error(fresh_module, tmp_path, monkeypatch):
    """git 命令失败时抛 CalledProcessError（让调用方处理）"""
    (tmp_path / ".git").mkdir()
    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr="fatal: not a git repository")
    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        fresh_module.run_git_status_porcelain(str(tmp_path))


# ── debounce 测试 ───────────────────────────────────────────────

def test_schedule_scan_merges_consecutive_changes(fresh_module, monkeypatch):
    """5s 内连续 schedule 同一 name → 只触发 1 次 _do_scan"""
    calls = []
    def fake_do_scan(name, pending):
        calls.append(name)
    monkeypatch.setattr(fresh_module, "_do_scan", fake_do_scan)

    pending = {}
    try:
        # 1s 内连续 schedule 3 次（debounce=2s 缩短测试时间）
        fresh_module._schedule_scan("repo1", debounce=2, pending=pending)
        time.sleep(0.3)
        fresh_module._schedule_scan("repo1", debounce=2, pending=pending)
        time.sleep(0.3)
        fresh_module._schedule_scan("repo1", debounce=2, pending=pending)

        # 等最后一个 timer 触发
        time.sleep(2.5)
    finally:
        # tear down 前 cancel 所有 pending timer, 避免 pytest 退出时 daemon timer 触发 _do_scan
        # 导致 import lancedb 触发 atexit 注册失败
        for t in list(pending.values()):
            t.cancel()
        for t in list(pending.values()):
            t.join(timeout=1)

    assert len(calls) == 1, f"应该只触发 1 次，实际 {len(calls)} 次"
    assert calls[0] == "repo1"


def test_schedule_scan_does_not_merge_different_repos(fresh_module, monkeypatch):
    """不同 repo 各自 schedule，独立触发"""
    calls = []
    def fake_do_scan(name, pending):
        calls.append(name)
    monkeypatch.setattr(fresh_module, "_do_scan", fake_do_scan)

    pending = {}
    try:
        fresh_module._schedule_scan("repo1", debounce=1, pending=pending)
        fresh_module._schedule_scan("repo2", debounce=1, pending=pending)
        time.sleep(1.5)
    finally:
        for t in list(pending.values()):
            t.cancel()
        for t in list(pending.values()):
            t.join(timeout=1)

    assert sorted(calls) == ["repo1", "repo2"]


def test_schedule_scan_replaces_previous_timer(fresh_module, monkeypatch):
    """连续 schedule 时，前一个 timer 应当被替换"""
    pending = {}
    try:
        fresh_module._schedule_scan("repo1", debounce=2, pending=pending)
        first_timer = pending["repo1"]
        fresh_module._schedule_scan("repo1", debounce=2, pending=pending)
        second_timer = pending["repo1"]
        assert first_timer is not second_timer
        # dict 已被替换，第一个 timer 不会被触发（debounce 行为已由上一个 test 验证）
    finally:
        for t in list(pending.values()):
            t.cancel()
        for t in list(pending.values()):
            t.join(timeout=1)


# ── 主循环 + 生命周期 ───────────────────────────────────────────

def test_watchdog_loop_exits_immediately_when_interval_zero(fresh_module):
    """interval_seconds=0 时 watchdog 启动后立即 return"""
    cfg = {"interval_seconds": 0, "debounce_seconds": 5}
    shutdown = threading.Event()
    # 应在 <1s 内返回
    start = time.time()
    fresh_module.watchdog_loop(shutdown, cfg_provider=lambda: cfg)
    elapsed = time.time() - start
    assert elapsed < 0.5


def test_watchdog_loop_exits_on_shutdown_event(fresh_module):
    """shutdown_event.set() 后线程在 1s 内退出"""
    cfg = {"interval_seconds": 60, "debounce_seconds": 5}
    shutdown = threading.Event()
    t = threading.Thread(
        target=fresh_module.watchdog_loop,
        args=(shutdown,),
        kwargs={"cfg_provider": lambda: cfg},
        daemon=True,
    )
    t.start()
    time.sleep(0.3)  # 让线程进 wait
    shutdown.set()
    t.join(timeout=2)
    assert not t.is_alive(), "shutdown 后线程应在 2s 内退出"


def test_watchdog_loop_skips_non_git_repos(fresh_module, tmp_path, monkeypatch):
    """非 git repo 不被 schedule"""
    (tmp_path / "repos").mkdir()
    non_git = tmp_path / "repos" / "non_git"
    non_git.mkdir()
    # 写 code_repos.json
    cfg_path = fresh_module.CONFIG_PATH
    with open(cfg_path, "w") as f:
        json.dump({"repos": {"r1": {"repo_path": str(non_git)}}, "watchdog": {"interval_seconds": 60, "debounce_seconds": 1}}, f)

    scheduled = []
    monkeypatch.setattr(fresh_module, "_schedule_scan", lambda name, debounce, pending: scheduled.append(name))
    monkeypatch.setattr(fresh_module, "run_git_status_porcelain", lambda path: "")

    shutdown = threading.Event()
    def stop():
        time.sleep(0.5)
        shutdown.set()
    stop_thread = threading.Thread(target=stop, daemon=True)
    stop_thread.start()
    try:
        fresh_module.watchdog_loop(shutdown)
    finally:
        stop_thread.join(timeout=2)
    assert scheduled == [], f"非 git repo 不应被 schedule，实际: {scheduled}"


def test_watchdog_loop_triggers_scan_on_porcelain_change(fresh_module, tmp_path, monkeypatch):
    """git repo porcelain 变化时 schedule 一次"""
    (tmp_path / "repos").mkdir()
    git_repo = tmp_path / "repos" / "r1"
    git_repo.mkdir()
    (git_repo / ".git").mkdir()

    cfg_path = fresh_module.CONFIG_PATH
    with open(cfg_path, "w") as f:
        json.dump({"repos": {"r1": {"repo_path": str(git_repo)}}, "watchdog": {"interval_seconds": 60, "debounce_seconds": 1}}, f)

    scheduled = []
    monkeypatch.setattr(fresh_module, "_schedule_scan", lambda name, debounce, pending: scheduled.append(name))
    monkeypatch.setattr(fresh_module, "run_git_status_porcelain", lambda path: "M  README.md\n")

    shutdown = threading.Event()
    def stop():
        time.sleep(0.3)
        shutdown.set()
    stop_thread = threading.Thread(target=stop, daemon=True)
    stop_thread.start()
    try:
        fresh_module.watchdog_loop(shutdown)
    finally:
        stop_thread.join(timeout=2)
    assert scheduled == ["r1"]


def test_watchdog_loop_reschedules_after_lock_conflict(fresh_module, tmp_path, monkeypatch):
    """锁冲突时下一轮重新 schedule 该 repo（不靠用户再改文件）

    模拟场景：
    1. 主循环第一轮检测到 porcelain 变化 → schedule 一次（_schedule_scan 计数 =1）
    2. 模拟"用户立刻手动改文件"→ run_git_status_porcelain 返回新值
       实际这里直接 fake _lock_failed，让主循环下一轮末尾重 schedule
    3. 主循环末尾遍历 _lock_failed → 重新 schedule（_schedule_scan 计数 =2）
    4. 断言至少 schedule 2 次
    """
    # 准备 git 仓库 + 写 code_repos.json
    (tmp_path / "repos").mkdir()
    git_repo = tmp_path / "repos" / "r1"
    git_repo.mkdir()
    (git_repo / ".git").mkdir()
    cfg_path = fresh_module.CONFIG_PATH
    with open(cfg_path, "w") as f:
        json.dump(
            {
                "repos": {"r1": {"repo_path": str(git_repo)}},
                "watchdog": {"interval_seconds": 60, "debounce_seconds": 1},
            },
            f,
        )

    # mock porcelain 稳定
    monkeypatch.setattr(fresh_module, "run_git_status_porcelain", lambda path: "M  README.md\n")

    # 第一次 schedule 后，模拟 _do_scan 锁冲突（直接 add _lock_failed）
    call_count = {"schedule": 0}

    def fake_schedule(name, debounce, pending):
        call_count["schedule"] += 1
        if call_count["schedule"] == 1:
            # 第一次 schedule 后，模拟 _do_scan 锁失败
            fresh_module._lock_failed.add(name)
        # 第二次 schedule 是主循环重试

    monkeypatch.setattr(fresh_module, "_schedule_scan", fake_schedule)

    # 跑 2 轮就够：第一轮 schedule + _lock_failed.add，第二轮末尾重 schedule
    # 但主循环末尾会调 wait(interval) 60s，所以我们改 cfg 让 interval 极短
    # 用 cfg_provider 注入：interval=0.2s，debounce=0.05s
    shutdown = threading.Event()

    def run_loop():
        fresh_module.watchdog_loop(
            shutdown,
            cfg_provider=lambda: {"interval_seconds": 1, "debounce_seconds": 1},
        )

    stop_thread = threading.Thread(
        target=lambda: (time.sleep(1.2), shutdown.set()),
        daemon=True,
    )
    stop_thread.start()
    try:
        run_loop()
    finally:
        stop_thread.join(timeout=2)
    assert call_count["schedule"] >= 2, f"锁失败后应重 schedule，实际只 schedule {call_count['schedule']} 次"
