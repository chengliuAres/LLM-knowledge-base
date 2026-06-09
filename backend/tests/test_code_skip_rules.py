"""code_skip_rules 模块测试

覆盖：
- build_default_skip_rules() 返回完整默认规则（合并所有项目类型）
- get_skip_rules() 文件不存在时自动写入默认；存在时直接返回
- save_skip_rules() / reset_skip_rules() 写文件行为
- get_skip_dirs() / get_skip_exts() 返回 set[str]

使用临时目录隔离 data/，不污染真实配置。
"""

import os
import json
import pytest
import importlib

# 模块在 backend/ 目录下，需要把 backend/ 加入 sys.path
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    """用 tmp_path 替换 data/ 目录，避免污染真实配置"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    config_path = data_dir / "code_skip_rules.json"

    # 必须在 import module 之前设置，否则模块加载时已绑定常量
    monkeypatch.setenv("EMAIL_WIKI_DATA_DIR", str(data_dir))
    yield data_dir, config_path


@pytest.fixture
def fresh_module(isolated_data_dir, monkeypatch):
    """重新加载 code_skip_rules，确保读取的是临时配置路径"""
    import code_skip_rules
    importlib.reload(code_skip_rules)
    # 重置模块里的路径常量指向 tmp
    data_dir, config_path = isolated_data_dir
    monkeypatch.setattr(code_skip_rules, "PROJECT_ROOT", str(data_dir.parent))
    monkeypatch.setattr(code_skip_rules, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(code_skip_rules, "DATA_DIR", str(data_dir))
    return code_skip_rules


def test_build_default_skip_rules_returns_full_structure(fresh_module):
    """build_default_skip_rules 返回的 dict 包含 skip_dirs (list[dict]) 和 skip_exts (list[dict])"""
    rules = fresh_module.build_default_skip_rules()
    assert "skip_dirs" in rules
    assert "skip_exts" in rules
    assert isinstance(rules["skip_dirs"], list)
    assert isinstance(rules["skip_exts"], list)
    # 每个元素都是 {"name": ..., "category": ...}
    for d in rules["skip_dirs"]:
        assert "name" in d and "category" in d
    for d in rules["skip_exts"]:
        assert "name" in d and "category" in d


def test_build_default_skip_rules_contains_categorized_items(fresh_module):
    """默认规则包含各分类的关键项"""
    rules = fresh_module.build_default_skip_rules()
    dir_names = {d["name"] for d in rules["skip_dirs"]}
    ext_names = {d["name"] for d in rules["skip_exts"]}

    # 关键目录
    assert ".git" in dir_names
    assert "node_modules" in dir_names
    assert "build" in dir_names
    assert ".gradle" in dir_names
    assert "venv" in dir_names or ".venv" in dir_names

    # 关键扩展名
    assert ".png" in ext_names
    assert ".json" in ext_names
    assert ".strings" in ext_names
    assert ".xml" in ext_names


def test_get_skip_rules_creates_file_if_missing(fresh_module, isolated_data_dir):
    """get_skip_rules: 文件不存在时自动写入默认规则"""
    data_dir, config_path = isolated_data_dir
    assert not config_path.exists()

    rules = fresh_module.get_skip_rules()
    # 返回结构正确
    assert "skip_dirs" in rules and "skip_exts" in rules
    # 文件已创建
    assert config_path.exists()
    # 文件内容是合法 JSON
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data == rules


def test_get_skip_rules_returns_existing(fresh_module, isolated_data_dir):
    """get_skip_rules: 文件存在时直接返回（不覆盖）"""
    data_dir, config_path = isolated_data_dir
    custom = {
        "skip_dirs": [{"name": "my_custom_dir", "category": "自定义"}],
        "skip_exts": [{"name": ".myext", "category": "自定义"}],
    }
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(custom, f, ensure_ascii=False)

    rules = fresh_module.get_skip_rules()
    assert rules == custom
    # 不应被默认覆盖
    assert rules["skip_dirs"][0]["name"] == "my_custom_dir"


def test_save_skip_rules_writes_to_file(fresh_module, isolated_data_dir):
    """save_skip_rules: 写入到配置文件"""
    data_dir, config_path = isolated_data_dir
    new_rules = {
        "skip_dirs": [{"name": "abc", "category": "测试"}],
        "skip_exts": [{"name": ".xyz", "category": "测试"}],
    }
    fresh_module.save_skip_rules(new_rules)
    assert config_path.exists()
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data == new_rules


def test_reset_skip_rules_restores_default(fresh_module, isolated_data_dir):
    """reset_skip_rules: 清空自定义，恢复默认"""
    data_dir, config_path = isolated_data_dir
    # 先写自定义
    custom = {
        "skip_dirs": [{"name": "xxx", "category": "x"}],
        "skip_exts": [{"name": ".yyy", "category": "x"}],
    }
    fresh_module.save_skip_rules(custom)

    # reset 应返回默认
    default = fresh_module.reset_skip_rules()
    assert default == fresh_module.build_default_skip_rules()
    # 磁盘上也应写入默认
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data == default


def test_get_skip_dirs_returns_set_of_names(fresh_module):
    """get_skip_dirs: 返回目录名 set（忽略 category）"""
    dirs = fresh_module.get_skip_dirs()
    assert isinstance(dirs, set)
    # 至少包含几个核心项
    assert ".git" in dirs
    assert "node_modules" in dirs


def test_get_skip_exts_returns_set_of_names(fresh_module):
    """get_skip_exts: 返回扩展名 set"""
    exts = fresh_module.get_skip_exts()
    assert isinstance(exts, set)
    assert ".png" in exts
    assert ".json" in exts


def test_get_skip_dirs_reflects_saved_changes(fresh_module):
    """save 后再 get，新规则立即生效（读的是磁盘文件）"""
    fresh_module.save_skip_rules({
        "skip_dirs": [{"name": "my_dir_xyz", "category": "test"}],
        "skip_exts": [{"name": ".myext_xyz", "category": "test"}],
    })
    assert "my_dir_xyz" in fresh_module.get_skip_dirs()
    assert ".myext_xyz" in fresh_module.get_skip_exts()
