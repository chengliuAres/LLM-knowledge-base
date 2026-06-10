"""folder picker endpoints 测试

覆盖：
- /api/code/resolve-path：唯一命中 / 多匹配 / 无匹配 / 隐藏目录跳过 / 限深 / 无效 parent
- /api/code/open-in-finder：macOS/Windows/Linux 调用 / 路径不存在 / 黑名单 / 未知系统

使用临时目录隔离文件系统。
"""

import os
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# 模块在 backend/ 目录下
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app  # noqa: E402

client = TestClient(app)


# ── /api/code/resolve-path ──────────────────────────────────────

def test_resolve_path_unique(tmp_path, monkeypatch):
    """home 下只有一个同名目录 → 返回 {path}"""
    (tmp_path / "myrepo").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows 兜底

    res = client.get(f"/api/code/resolve-path?name=myrepo&parent={tmp_path}")
    assert res.status_code == 200
    data = res.json()
    assert "path" in data
    assert data["path"] == str(tmp_path / "myrepo")


def test_resolve_path_multiple(tmp_path):
    """同名多个目录 → 返回 matches 列表"""
    (tmp_path / "myrepo").mkdir()
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "myrepo").mkdir()

    res = client.get(f"/api/code/resolve-path?name=myrepo&parent={tmp_path}")
    assert res.status_code == 200
    data = res.json()
    assert "matches" in data
    assert len(data["matches"]) == 2
    assert str(tmp_path / "myrepo") in data["matches"]
    assert str(tmp_path / "sub" / "myrepo") in data["matches"]


def test_resolve_path_not_found(tmp_path):
    """无匹配 → 404"""
    res = client.get(f"/api/code/resolve-path?name=missing&parent={tmp_path}")
    assert res.status_code == 404


def test_resolve_path_skips_hidden(tmp_path):
    """隐藏目录不被算入"""
    (tmp_path / ".hiddenrepo").mkdir()
    res = client.get(f"/api/code/resolve-path?name=.hiddenrepo&parent={tmp_path}")
    assert res.status_code == 404


def test_resolve_path_depth_limit(tmp_path):
    """超过 3 层的不算入"""
    deep = tmp_path / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    (deep / "target").mkdir()
    res = client.get(f"/api/code/resolve-path?name=target&parent={tmp_path}")
    assert res.status_code == 404


def test_resolve_path_invalid_parent(tmp_path):
    """parent 不存在 → 400"""
    fake = tmp_path / "no-such-dir"
    res = client.get(f"/api/code/resolve-path?name=x&parent={fake}")
    assert res.status_code == 400


# ── /api/code/open-in-finder ───────────────────────────────────

# 测试 fixture：macOS 的 tmp_path 在 /private/var/... 下，会被 denylist 误伤。
# 用环境变量显式跳过黑名单，.ssh 黑名单测试单独 unset 后注入真实 denylist 项测。
@pytest.fixture(autouse=True)
def _skip_denylist_in_tests(monkeypatch):
    monkeypatch.setenv("EMAIL_WIKI_SKIP_PATH_DENYLIST", "1")


def test_open_in_finder_darwin(tmp_path, monkeypatch):
    """macOS → 调 subprocess.Popen(['open', path])"""
    target = tmp_path / "mydir"
    target.mkdir()
    monkeypatch.setattr("platform.system", lambda: "Darwin")

    with patch("code_routes.subprocess.Popen") as mock_popen:
        res = client.post("/api/code/open-in-finder", json={"path": str(target)})
        assert res.status_code == 200
        data = res.json()
        assert data["opened"] is True
        assert data["path"] == str(target)
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert args[0] == "open"
        assert str(target) in args


def test_open_in_finder_windows(tmp_path, monkeypatch):
    """Windows → 调 explorer"""
    target = tmp_path / "mydir"
    target.mkdir()
    monkeypatch.setattr("platform.system", lambda: "Windows")

    with patch("code_routes.subprocess.Popen") as mock_popen:
        res = client.post("/api/code/open-in-finder", json={"path": str(target)})
        assert res.status_code == 200
        args = mock_popen.call_args[0][0]
        assert args[0] == "explorer"


def test_open_in_finder_linux(tmp_path, monkeypatch):
    """Linux → 调 xdg-open"""
    target = tmp_path / "mydir"
    target.mkdir()
    monkeypatch.setattr("platform.system", lambda: "Linux")

    with patch("code_routes.subprocess.Popen") as mock_popen:
        res = client.post("/api/code/open-in-finder", json={"path": str(target)})
        assert res.status_code == 200
        args = mock_popen.call_args[0][0]
        assert args[0] == "xdg-open"


def test_open_in_finder_path_invalid(tmp_path, monkeypatch):
    """路径不存在 → 400"""
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    fake = tmp_path / "no-such-dir"
    res = client.post("/api/code/open-in-finder", json={"path": str(fake)})
    assert res.status_code == 400


def test_open_in_finder_blacklist_ssh(tmp_path, monkeypatch):
    """~/.ssh 拒绝 → 403（注入 denylist 项以避免依赖真实 ~/.ssh）"""
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    fake_ssh = tmp_path / ".ssh"
    fake_ssh.mkdir()

    # 关闭 fixture 的环境变量跳过，恢复 denylist 校验
    monkeypatch.delenv("EMAIL_WIKI_SKIP_PATH_DENYLIST", raising=False)

    import code_routes
    monkeypatch.setattr(
        code_routes,
        "_OPEN_DENY_PREFIXES",
        code_routes._OPEN_DENY_PREFIXES + (str(fake_ssh),),
    )

    res = client.post("/api/code/open-in-finder", json={"path": str(fake_ssh)})
    assert res.status_code == 403


def test_open_in_finder_blacklist_etc(tmp_path, monkeypatch):
    """/etc 系统目录 → 403（macOS 上 /etc 是 /private/etc 的 symlink，denylist 必命中）"""
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.delenv("EMAIL_WIKI_SKIP_PATH_DENYLIST", raising=False)
    res = client.post("/api/code/open-in-finder", json={"path": "/etc"})
    assert res.status_code == 403


def test_open_in_finder_unsupported_os(tmp_path, monkeypatch):
    """未知系统 → 返回 skipped: True"""
    target = tmp_path / "mydir"
    target.mkdir()
    monkeypatch.setattr("platform.system", lambda: "Plan9")

    res = client.post("/api/code/open-in-finder", json={"path": str(target)})
    assert res.status_code == 200
    data = res.json()
    assert data["skipped"] is True
    assert "Plan9" in data["reason"]


def test_open_in_finder_missing_path():
    """payload 没 path → 400"""
    res = client.post("/api/code/open-in-finder", json={})
    assert res.status_code == 400


def test_open_in_finder_command_not_found(tmp_path, monkeypatch):
    """系统命令不存在 → skipped: True（最小化 Linux 环境）"""
    target = tmp_path / "mydir"
    target.mkdir()
    monkeypatch.setattr("platform.system", lambda: "Linux")

    with patch("code_routes.subprocess.Popen", side_effect=FileNotFoundError):
        res = client.post("/api/code/open-in-finder", json={"path": str(target)})
        assert res.status_code == 200
        data = res.json()
        assert data["skipped"] is True
        assert "未找到命令" in data["reason"]
