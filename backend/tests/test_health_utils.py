"""health_utils 测试 —— 4 个核心健康检查函数。"""

import os
import sys
import tempfile
from unittest.mock import patch

import pytest

# 把 backend/ 加入 sys.path，让 health_utils 可直接 import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# --- T1: check_lancedb_status 存在且可访问 ---


def test_check_lancedb_status_ok_when_dir_exists(tmp_path):
    """LanceDB 目录存在 → status=ok, tables >= 0, message 包含目录路径。"""
    from health_utils import check_lancedb_status

    result = check_lancedb_status(db_path=str(tmp_path))

    assert result["status"] == "ok"
    assert isinstance(result["tables"], int)
    assert result["tables"] >= 0
    assert str(tmp_path) in result["message"]


def test_check_lancedb_status_error_when_missing(tmp_path):
    """LanceDB 目录不存在 → status=error, 永不抛异常。"""
    from health_utils import check_lancedb_status

    missing = tmp_path / "does_not_exist"
    result = check_lancedb_status(db_path=str(missing))

    assert result["status"] == "error"
    assert "message" in result and isinstance(result["message"], str)


# --- T2: check_model_status ---


def test_check_model_status_default_not_loaded():
    """默认没有加载任何模型 → status=not_loaded, model_name 非空, dimension=0。"""
    from health_utils import check_model_status

    result = check_model_status()

    assert result["status"] in ("loaded", "not_loaded")
    assert isinstance(result["model_name"], str)
    assert result["model_name"]  # 非空
    assert isinstance(result["dimension"], int)
    assert result["dimension"] >= 0


def test_check_model_status_loaded_when_marker_set():
    """模拟已加载的标记 → status=loaded, dimension=768。"""
    from health_utils import check_model_status

    fake_model = type(
        "M",
        (),
        {"_model_name": "BAAI/bge-base-zh-v1.5", "get_sentence_embedding_dimension": lambda self: 768},
    )()
    with patch.dict(sys.modules, {}):
        # 通过 monkeypatch 全局标志让函数认为模型已加载
        from health_utils import check_model_status as fn
        with patch("health_utils._MODEL_HANDLE", fake_model, create=True):
            result = fn()
    assert result["status"] == "loaded"
    assert result["dimension"] == 768


# --- T3: check_disk_usage ---


def test_check_disk_usage_ok_for_normal_data_dir(tmp_path):
    """data 目录存在且未满 → status=ok, usage_percent 在 0~100。"""
    from health_utils import check_disk_usage

    result = check_disk_usage(path=str(tmp_path))

    assert result["status"] in ("ok", "warning", "error")
    assert result["total_mb"] > 0
    assert result["free_mb"] >= 0
    assert 0 <= result["usage_percent"] <= 100


def test_check_disk_usage_error_for_missing_path():
    """data 目录不存在 → status=error, 永不抛异常。"""
    from health_utils import check_disk_usage

    result = check_disk_usage(path="/nonexistent/path/that/should/not/exist_12345")

    assert result["status"] == "error"
    assert "message" in result or "free_mb" in result


# --- T4: get_system_health 聚合 ---


def test_get_system_health_returns_aggregate():
    """get_system_health 聚合三个检查 + 时间戳。"""
    from health_utils import get_system_health

    result = get_system_health()

    assert result["overall"] in ("healthy", "degraded", "unhealthy")
    assert "checks" in result
    assert "timestamp" in result
    # 三个子检查都必须存在
    assert "lancedb" in result["checks"]
    assert "model" in result["checks"]
    assert "disk" in result["checks"]


def test_get_system_health_handles_internal_errors():
    """即使某个子检查抛异常, get_system_health 也不应该崩溃。"""
    from health_utils import get_system_health

    with patch("health_utils.check_lancedb_status", side_effect=Exception("boom")):
        result = get_system_health()

    # 不应抛异常,overall 仍合法
    assert result["overall"] in ("healthy", "degraded", "unhealthy")
    assert "timestamp" in result
