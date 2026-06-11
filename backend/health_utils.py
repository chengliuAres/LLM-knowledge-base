"""系统健康检查工具模块。

仅使用标准库（os, shutil, datetime），所有函数吞掉异常并返回错误 dict。
"""

import os
import shutil
from datetime import datetime

# 项目根目录：health_utils.py 在 backend/ 下，根目录是上一级
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check_lancedb_status(db_path=None) -> dict:
    """检查 LanceDB 目录状态。

    Returns:
        dict: 包含 status/message/tables 字段
            - status: "ok" / "warning" / "error"
            - message: 状态描述
            - tables: 已检测到的表名列表（按子目录推断）
    """
    if db_path is None:
        db_path = os.path.join(_PROJECT_ROOT, "data", "lancedb")
    result = {
        "status": "error",
        "message": "",
        "tables": [],
    }
    try:
        if not os.path.exists(db_path):
            result["status"] = "warning"
            result["message"] = f"LanceDB 路径不存在: {db_path}"
            return result

        if not os.path.isdir(db_path):
            result["status"] = "error"
            result["message"] = f"路径不是目录: {db_path}"
            return result

        # LanceDB 以子目录形式组织表
        tables = [
            name
            for name in os.listdir(db_path)
            if os.path.isdir(os.path.join(db_path, name)) and not name.startswith(".")
        ]
        result["tables"] = sorted(tables)
        result["status"] = "ok" if tables else "warning"
        result["message"] = (
            f"已发现 {len(tables)} 张表" if tables else "目录存在但未发现表"
        )
        return result
    except Exception as exc:  # noqa: BLE001
        result["message"] = f"检查 LanceDB 时出错: {exc}"
        return result


def check_model_status() -> dict:
    """检查 embedding 模型状态（仅做目录存在性探测，不真正加载模型）。

    Returns:
        dict: 包含 status/model_name/dimension 字段
            - status: "ok" / "warning" / "error"
            - model_name: 期望的模型名（BAAI/bge-base-zh-v1.5）
            - dimension: 向量维度（768）
    """
    result = {
        "status": "error",
        "model_name": "BAAI/bge-base-zh-v1.5",
        "dimension": 768,
    }
    try:
        # 模型根目录在项目根的 models/ 下，按 HuggingFace 缓存布局查找
        candidates = [
            os.path.join(_PROJECT_ROOT, "models", "models--BAAI--bge-base-zh-v1.5"),
            os.path.join(_PROJECT_ROOT, "models", "BAAI", "bge-base-zh-v1.5"),
        ]
        for candidate in candidates:
            if os.path.isdir(candidate):
                result["status"] = "ok"
                result["message"] = f"模型目录已就绪: {candidate}"
                return result

        # 未命中本地目录，但模型可能在首次使用时下载，标记为 warning
        result["status"] = "warning"
        result["message"] = "未发现本地模型目录，首次使用时会自动下载"
        return result
    except Exception as exc:  # noqa: BLE001
        result["message"] = f"检查模型状态时出错: {exc}"
        return result


def check_disk_usage(path=None) -> dict:
    """检查指定路径所在磁盘的使用情况。

    Returns:
        dict: 包含 status/total_mb/used_mb/free_mb/usage_percent 字段
    """
    result = {
        "status": "error",
        "total_mb": 0,
        "used_mb": 0,
        "free_mb": 0,
        "usage_percent": 0,
    }
    try:
        if path is None:
            path = os.path.join(_PROJECT_ROOT, "data")
        target = path if os.path.isabs(path) else os.path.abspath(path)
        if not os.path.exists(target):
            result["status"] = "warning"
            result["message"] = f"路径不存在: {path}"
            return result

        usage = shutil.disk_usage(target)
        total_mb = round(usage.total / (1024 * 1024), 2)
        used_mb = round(usage.used / (1024 * 1024), 2)
        free_mb = round(usage.free / (1024 * 1024), 2)
        usage_percent = round(usage.used / usage.total * 100, 2) if usage.total else 0.0

        if usage_percent >= 90:
            status = "error"
            message = f"磁盘空间严重不足（{usage_percent:.1f}%）"
        elif usage_percent >= 75:
            status = "warning"
            message = f"磁盘空间偏紧（{usage_percent:.1f}%）"
        else:
            status = "ok"
            message = f"磁盘空间正常（{usage_percent:.1f}%）"

        result.update(
            {
                "status": status,
                "message": message,
                "total_mb": total_mb,
                "used_mb": used_mb,
                "free_mb": free_mb,
                "usage_percent": usage_percent,
            }
        )
        return result
    except Exception as exc:  # noqa: BLE001
        result["message"] = f"检查磁盘时出错: {exc}"
        return result


def get_system_health() -> dict:
    """聚合所有健康检查项，并给出整体状态。

    Returns:
        dict: 包含 overall/timestamp/checks 字段
            - overall: "healthy" / "degraded" / "unhealthy"
            - timestamp: ISO 格式时间戳
            - checks: {"lancedb": ..., "model": ..., "disk": ...}
    """
    checks = {}
    for name, fn in [
        ("lancedb", check_lancedb_status),
        ("model", check_model_status),
        ("disk", check_disk_usage),
    ]:
        try:
            checks[name] = fn()
        except Exception as exc:  # noqa: BLE001
            checks[name] = {"status": "error", "message": f"检查异常: {exc}"}

    statuses = [checks[k].get("status") for k in ("lancedb", "model", "disk")]
    if "error" in statuses:
        overall = "unhealthy"
    elif "warning" in statuses:
        overall = "degraded"
    else:
        overall = "healthy"

    return {
        "overall": overall,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "checks": checks,
    }
