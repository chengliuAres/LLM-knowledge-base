"""代码仓库配置管理 - code_repos.json 读写 + 增量扫描支持"""

import os
import json
import threading
from pathlib import Path
from typing import Optional

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "data", "code_repos.json")

# 扫描锁 (防止同仓库并发扫描)
_scan_locks: dict[str, threading.Lock] = {}
_global_lock = threading.Lock()


def _get_lock(repo_name: str) -> threading.Lock:
    """获取仓库级别的扫描锁"""
    with _global_lock:
        if repo_name not in _scan_locks:
            _scan_locks[repo_name] = threading.Lock()
        return _scan_locks[repo_name]


def load_config() -> dict:
    """加载配置文件

    Returns:
        {"repos": {"name": {repo_config...}}, "file_mtimes": {"name": {rel_path: mtime}}}
    """
    if not os.path.exists(CONFIG_PATH):
        return {"repos": {}, "file_mtimes": {}}

    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # 兼容旧格式
            if "repos" not in data:
                data["repos"] = {}
            if "file_mtimes" not in data:
                data["file_mtimes"] = {}
            return data
    except (json.JSONDecodeError, OSError):
        return {"repos": {}, "file_mtimes": {}}


def save_config(config: dict):
    """保存配置文件"""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_repo_config(repo_name: str) -> Optional[dict]:
    """获取单个仓库配置"""
    config = load_config()
    return config["repos"].get(repo_name)


def list_repos() -> list[dict]:
    """列出所有已配置的仓库"""
    config = load_config()
    repos = []
    for name, repo in config["repos"].items():
        repos.append({
            "name": name,
            "project_type": repo.get("project_type", ""),
            "repo_path": repo.get("repo_path", ""),
            "languages": repo.get("languages", []),
            "total_files": repo.get("total_files", 0),
            "total_chunks": repo.get("total_chunks", 0),
            "last_scanned": repo.get("last_scanned", ""),
        })
    return repos


def register_repo(
    repo_name: str,
    repo_path: str,
    project_type: str,
    languages: list[str],
    stats: dict,
):
    """注册/更新仓库配置 (扫描完成后调用)"""
    from datetime import datetime

    config = load_config()
    config["repos"][repo_name] = {
        "repo_name": repo_name,
        "repo_path": os.path.abspath(repo_path),
        "project_type": project_type,
        "languages": languages,
        "total_files": stats.get("total_files", 0),
        "total_chunks": stats.get("total_chunks", 0),
        "by_language": stats.get("by_language", {}),
        "by_chunk_type": stats.get("by_chunk_type", {}),
        "last_scanned": datetime.now().isoformat(),
    }
    save_config(config)


def remove_repo(repo_name: str) -> bool:
    """删除仓库配置"""
    config = load_config()
    if repo_name not in config["repos"]:
        return False

    del config["repos"][repo_name]
    # 同时清理 mtime 记录
    config["file_mtimes"].pop(repo_name, None)
    save_config(config)
    return True


def get_file_mtimes(repo_name: str) -> dict[str, float]:
    """获取仓库的文件 mtime 记录"""
    config = load_config()
    return config["file_mtimes"].get(repo_name, {})


def update_file_mtimes(repo_name: str, mtimes: dict[str, float]):
    """更新仓库的文件 mtime 记录"""
    config = load_config()
    config["file_mtimes"][repo_name] = mtimes
    save_config(config)


def compute_incremental(
    repo_name: str,
    scanned_files: list[dict],
) -> dict[str, list]:
    """计算增量差异

    Args:
        repo_name: 仓库名
        scanned_files: scan_directory 返回的文件列表

    Returns:
        {
            "added": [file_info, ...],      # 新增文件
            "updated": [file_info, ...],    # mtime 变化的文件
            "deleted": [rel_path_str, ...], # 已删除的文件路径
            "skipped": [file_info, ...],    # 未变化的文件
        }
    """
    old_mtimes = get_file_mtimes(repo_name)
    new_mtimes = {f['rel_path']: f['mtime'] for f in scanned_files}

    added = []
    updated = []
    skipped = []

    for f in scanned_files:
        rel = f['rel_path']
        if rel not in old_mtimes:
            added.append(f)
        elif old_mtimes[rel] != f['mtime']:
            updated.append(f)
        else:
            skipped.append(f)

    # 找已删除的文件
    new_paths = set(new_mtimes.keys())
    deleted = [rel for rel in old_mtimes if rel not in new_paths]

    return {
        "added": added,
        "updated": updated,
        "deleted": deleted,
        "skipped": skipped,
    }


def try_acquire_scan_lock(repo_name: str) -> bool:
    """尝试获取扫描锁 (非阻塞)"""
    lock = _get_lock(repo_name)
    return lock.acquire(blocking=False)


def release_scan_lock(repo_name: str):
    """释放扫描锁"""
    lock = _get_lock(repo_name)
    try:
        lock.release()
    except RuntimeError:
        pass
