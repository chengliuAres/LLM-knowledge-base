"""代码知识库的可配置排除规则

- 配置文件: data/code_skip_rules.json
- 格式: {"skip_dirs": [{"name": ..., "category": ...}], "skip_exts": [...]}
- 首次加载时若文件不存在，自动写入 build_default_skip_rules() 的结果
"""

import os
import json
import subprocess

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
    """返回目录名集合（忽略 category），含勾选的 gitignore 目录"""
    rules = get_skip_rules()
    dirs = {d["name"] for d in rules.get("skip_dirs", [])}
    # 合并勾选的 gitignore 目录
    for g in rules.get("gitignore_selections", []):
        if g.get("selected", True):
            dirs.add(g["name"])
    return dirs


def get_skip_exts() -> set[str]:
    """返回扩展名集合（忽略 category）"""
    return {d["name"] for d in get_skip_rules().get("skip_exts", [])}


# ── .gitignore 解析 ──────────────────────────────────────────────

def parse_gitignore_dirs(repo_path: str) -> list[str]:
    """从 .gitignore 提取可排除的条目

    提取规则：
    - 以 / 结尾 → 目录，去掉 /
    - 不含 * ? [ 通配符 → 精确名称（目录或文件均可）
    - 嵌套路径（如 a/b）→ 提取顶层目录 a + 完整路径 a/b
    跳过：注释行、空行、取反（!）行、通配符模式
    """
    gitignore_path = os.path.join(repo_path, ".gitignore")
    if not os.path.isfile(gitignore_path):
        return []

    entries = []
    try:
        with open(gitignore_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                entry = line.strip()
                if not entry or entry.startswith("#") or entry.startswith("!"):
                    continue
                # 跳过含通配符的模式
                if "*" in entry or "?" in entry or "[" in entry:
                    continue
                # 去掉尾部 / 和开头 /
                if entry.endswith("/"):
                    entry = entry.rstrip("/")
                if entry.startswith("/"):
                    entry = entry.lstrip("/")
                if not entry:
                    continue
                entries.append(entry)
                # 嵌套路径 → 额外提取顶层目录
                if "/" in entry:
                    top = entry.split("/")[0]
                    if top and top not in entries:
                        entries.append(top)
    except OSError:
        pass

    # 去重保序
    seen = set()
    result = []
    for d in entries:
        if d not in seen:
            seen.add(d)
            result.append(d)
    return result


def open_config_in_finder():
    """在 Finder 中打开配置文件所在目录并选中文件"""
    if not os.path.exists(CONFIG_PATH):
        save_skip_rules(build_default_skip_rules())
    subprocess.run(["open", "-R", CONFIG_PATH], check=False)
