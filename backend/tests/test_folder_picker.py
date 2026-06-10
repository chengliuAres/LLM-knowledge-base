"""folder picker endpoints 测试

覆盖：
- /api/code/resolve-path：唯一命中 / 多匹配 / 无匹配 / 隐藏目录跳过 / 限深 / 无效 parent
- /api/code/open-in-finder：macOS/Windows/Linux 调用 / 路径不存在 / 黑名单 / 未知系统

使用临时目录隔离文件系统。
"""

import os
import sys
from pathlib import Path

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
