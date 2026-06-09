"""代码知识库的可配置排除规则

- 配置文件: data/code_skip_rules.json
- 格式: {"skip_dirs": [{"name": ..., "category": ...}], "skip_exts": [...]}
- 首次加载时若文件不存在，自动写入 build_default_skip_rules() 的结果
"""

import os
import json

# 项目根目录 + 配置文件路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
CONFIG_PATH = os.path.join(DATA_DIR, "code_skip_rules.json")


# ── 默认规则（按分类） ────────────────────────────────────────────

_DEFAULT_SKIP_DIRS: list[dict] = [
    # 版本控制
    *({"name": n, "category": "版本控制"} for n in [".git", ".svn", ".hg"]),
    # 依赖
    *({"name": n, "category": "依赖"} for n in
      ["node_modules", "Pods", "Carthage", ".build", "vendor", "bundle", "bower_components"]),
    # 构建产物
    *({"name": n, "category": "构建产物"} for n in
      ["build", "dist", "DerivedData", "target", "out"]),
    # IDE
    *({"name": n, "category": "IDE"} for n in
      [".idea", ".vscode", ".xcodeproj", ".xcworkspace"]),
    # 资源
    *({"name": n, "category": "资源"} for n in
      [".xcassets", "Assets.xcassets", ".lproj", "Resource"]),
    # 缓存
    *({"name": n, "category": "缓存"} for n in
      ["__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
       ".gradle", ".dart_tool", ".packages", ".next", ".nuxt",
       ".cache", "coverage", ".nyc_output"]),
    # 虚拟环境
    *({"name": n, "category": "虚拟环境"} for n in
      ["venv", ".venv", "virtualenv", "env", ".tox"]),
    # 第三方
    *({"name": n, "category": "第三方"} for n in
      ["third", "third_party", "lottie", "keystore", "gradleScripts",
       "buildSrc", ".ios", ".android", "ohosApp"]),
]

_DEFAULT_SKIP_EXTS: list[dict] = [
    # 图片
    *({"name": n, "category": "图片"} for n in
      [".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg"]),
    # 字体
    *({"name": n, "category": "字体"} for n in
      [".woff", ".woff2", ".ttf", ".eot"]),
    # iOS/Mac 资源
    *({"name": n, "category": "iOS/Mac资源"} for n in
      [".strings", ".plist", ".storyboard", ".xib"]),
    # Android 资源
    *({"name": n, "category": "Android资源"} for n in [".xml", ".pro"]),
    # 配置/数据
    *({"name": n, "category": "配置/数据"} for n in [".json"]),
]


def build_default_skip_rules() -> dict:
    """返回完整的默认规则 dict"""
    return {
        "skip_dirs": [dict(item) for item in _DEFAULT_SKIP_DIRS],
        "skip_exts": [dict(item) for item in _DEFAULT_SKIP_EXTS],
    }


# ── 读写 ────────────────────────────────────────────────────────

def get_skip_rules() -> dict:
    """读取配置文件；不存在或损坏则自动写入默认并返回"""
    if not os.path.exists(CONFIG_PATH):
        rules = build_default_skip_rules()
        save_skip_rules(rules)
        return rules

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 防御缺失 key
        if "skip_dirs" not in data or "skip_exts" not in data:
            raise ValueError("missing required keys")
        return data
    except (json.JSONDecodeError, ValueError, OSError):
        rules = build_default_skip_rules()
        save_skip_rules(rules)
        return rules


def save_skip_rules(rules: dict) -> None:
    """写入配置文件（校验每项必须含 name 和 category）"""
    for item in rules.get("skip_dirs", []) + rules.get("skip_exts", []):
        if not isinstance(item, dict) or "name" not in item or "category" not in item:
            raise ValueError(f"规则项必须含 name 和 category: {item}")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(rules, f, indent=2, ensure_ascii=False)


def reset_skip_rules() -> dict:
    """恢复默认规则（写入文件 + 返回）"""
    rules = build_default_skip_rules()
    save_skip_rules(rules)
    return rules


# ── 便捷访问 ────────────────────────────────────────────────────

def get_skip_dirs() -> set[str]:
    """返回目录名集合（忽略 category）"""
    return {d["name"] for d in get_skip_rules().get("skip_dirs", [])}


def get_skip_exts() -> set[str]:
    """返回扩展名集合（忽略 category）"""
    return {d["name"] for d in get_skip_rules().get("skip_exts", [])}
