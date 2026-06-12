"""Skill 接入子页 — 后端 API 单测"""
import io
import os
import sys
import zipfile

import pytest
from fastapi.testclient import TestClient

# 允许从 backend/ 根目录 import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import app

client = TestClient(app)


def test_skill_raw_returns_content():
    """GET /api/skill/raw 应返回 SKILL.md 文本 + 元信息"""
    resp = client.get("/api/skill/raw")
    assert resp.status_code == 200
    data = resp.json()
    assert "content" in data
    assert "size" in data
    assert "files" in data
    assert data["size"] > 10000, "SKILL.md 实际 ~28KB，不能太小"
    assert "code_search" in data["content"], "内容应含 MCP tool 关键字"


def test_skill_info_files_listed():
    """GET /api/skill/info 应列出文件清单"""
    resp = client.get("/api/skill/info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["file_count"] >= 3, "应含 README + SKILL + scripts/kb_api.py"
    names = [f["name"] for f in data["files"]]
    assert "SKILL.md" in names
    assert any("kb_api.py" in n for n in names)


def test_skill_download_zip_structure():
    """GET /api/skill/download 返回 zip，根目录应是 code-search/"""
    resp = client.get("/api/skill/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"

    # 解压 zip 验证结构
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()
    assert any(n.startswith("code-search/") for n in names), \
        f"zip 根目录应为 code-search/，实际: {names[:3]}"
    assert "code-search/SKILL.md" in names
    assert "code-search/scripts/kb_api.py" in names


def test_skill_commands_parses_kb_api():
    """GET /api/skill/commands 应解析 kb_api.py 的 argparse subcommands"""
    resp = client.get("/api/skill/commands")
    assert resp.status_code == 200
    data = resp.json()
    assert "commands" in data
    assert isinstance(data["commands"], list)
    assert len(data["commands"]) >= 3, "kb_api.py 至少有 5 个 subcommand (search/chat/trace/file/repos)"
    names = [c["name"] for c in data["commands"]]
    # 必含 search / trace
    assert "search" in names, f"应含 search 子命令，实际 names: {names}"
    assert "trace" in names, f"应含 trace 子命令，实际 names: {names}"
    # 每条 command 应有 name 字段（可无 help）
    for c in data["commands"]:
        assert "name" in c
        assert isinstance(c["name"], str)
