# 可配置排除规则 Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 将代码索引的文件排除规则从硬编码改为用户可配置，通过 UI 管理，扫描时实时读取。

**Architecture:** 新增 `code_skip_rules.py` 模块管理配置读写，存储到独立的 `data/code_skip_rules.json`。后端新增 3 个 API，前端在代码知识库 Tab 新增设置面板。`scan_directory()` 改为从配置文件读取排除规则。

**Tech Stack:** Python, FastAPI, JSON 配置, Tailwind CSS

---

### Task 1: 创建 code_skip_rules.py 模块

**Objective:** 实现排除规则的读写、默认规则生成

**Files:**
- Create: `backend/code_skip_rules.py`

**Step 1: 创建模块**

```python
"""代码知识库 — 可配置排除规则管理"""

import os
import json
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "data", "code_skip_rules.json")


def build_default_skip_rules() -> dict:
    """构建默认排除规则（合并所有项目类型的规则）"""
    return {
        "skip_dirs": [
            # 版本控制
            {"name": ".git", "category": "版本控制"},
            {"name": ".svn", "category": "版本控制"},
            {"name": ".hg", "category": "版本控制"},
            # 依赖
            {"name": "node_modules", "category": "依赖"},
            {"name": "Pods", "category": "依赖"},
            {"name": "Carthage", "category": "依赖"},
            {"name": ".build", "category": "依赖"},
            {"name": "vendor", "category": "依赖"},
            {"name": "bundle", "category": "依赖"},
            {"name": "bower_components", "category": "依赖"},
            # 构建产物
            {"name": "build", "category": "构建产物"},
            {"name": "dist", "category": "构建产物"},
            {"name": "DerivedData", "category": "构建产物"},
            {"name": "target", "category": "构建产物"},
            {"name": "out", "category": "构建产物"},
            # IDE
            {"name": ".idea", "category": "IDE"},
            {"name": ".vscode", "category": "IDE"},
            {"name": ".xcodeproj", "category": "IDE"},
            {"name": ".xcworkspace", "category": "IDE"},
            # 资源
            {"name": ".xcassets", "category": "资源"},
            {"name": "Assets.xcassets", "category": "资源"},
            {"name": ".lproj", "category": "资源"},
            {"name": "Resource", "category": "资源"},
            # 缓存
            {"name": "__pycache__", "category": "缓存"},
            {"name": ".mypy_cache", "category": "缓存"},
            {"name": ".pytest_cache", "category": "缓存"},
            {"name": ".ruff_cache", "category": "缓存"},
            {"name": ".gradle", "category": "缓存"},
            {"name": ".dart_tool", "category": "缓存"},
            {"name": ".packages", "category": "缓存"},
            {"name": ".next", "category": "缓存"},
            {"name": ".nuxt", "category": "缓存"},
            {"name": ".cache", "category": "缓存"},
            {"name": "coverage", "category": "缓存"},
            {"name": ".nyc_output", "category": "缓存"},
            # 虚拟环境
            {"name": "venv", "category": "虚拟环境"},
            {"name": ".venv", "category": "虚拟环境"},
            {"name": "virtualenv", "category": "虚拟环境"},
            {"name": "env", "category": "虚拟环境"},
            {"name": ".tox", "category": "虚拟环境"},
            # 第三方/自动生成
            {"name": "third", "category": "第三方"},
            {"name": "third_party", "category": "第三方"},
            {"name": "lottie", "category": "第三方"},
            {"name": "keystore", "category": "第三方"},
            {"name": "gradleScripts", "category": "第三方"},
            {"name": "buildSrc", "category": "第三方"},
            {"name": ".ios", "category": "第三方"},
            {"name": ".android", "category": "第三方"},
            {"name": "ohosApp", "category": "第三方"},
        ],
        "skip_exts": [
            # 图片
            {"name": ".png", "category": "图片"},
            {"name": ".jpg", "category": "图片"},
            {"name": ".jpeg", "category": "图片"},
            {"name": ".gif", "category": "图片"},
            {"name": ".ico", "category": "图片"},
            {"name": ".svg", "category": "图片"},
            # 字体
            {"name": ".woff", "category": "字体"},
            {"name": ".woff2", "category": "字体"},
            {"name": ".ttf", "category": "字体"},
            {"name": ".eot", "category": "字体"},
            # iOS/Mac 资源
            {"name": ".strings", "category": "iOS/Mac资源"},
            {"name": ".plist", "category": "iOS/Mac资源"},
            {"name": ".storyboard", "category": "iOS/Mac资源"},
            {"name": ".xib", "category": "iOS/Mac资源"},
            # Android 资源
            {"name": ".xml", "category": "Android资源"},
            {"name": ".pro", "category": "Android资源"},
            # 配置/数据
            {"name": ".json", "category": "配置/数据"},
        ],
    }


def get_skip_rules() -> dict:
    """读取排除规则，文件不存在则自动写入默认规则"""
    if not os.path.exists(CONFIG_PATH):
        default = build_default_skip_rules()
        save_skip_rules(default)
        return default
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        default = build_default_skip_rules()
        save_skip_rules(default)
        return default


def save_skip_rules(rules: dict):
    """保存排除规则到文件"""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(rules, f, indent=2, ensure_ascii=False)


def reset_skip_rules() -> dict:
    """恢复默认规则"""
    default = build_default_skip_rules()
    save_skip_rules(default)
    return default


def get_skip_dirs() -> set[str]:
    """返回 skip_dirs 的 name 集合，供 scan_directory 直接使用"""
    rules = get_skip_rules()
    return {item["name"] for item in rules.get("skip_dirs", [])}


def get_skip_exts() -> set[str]:
    """返回 skip_exts 的 name 集合，供 scan_directory 直接使用"""
    rules = get_skip_rules()
    return {item["name"] for item in rules.get("skip_exts", [])}
```

**Step 2: 验证模块可导入**

Run: `cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend && source venv/bin/activate && python3 -c "from code_skip_rules import get_skip_rules, get_skip_dirs, get_skip_exts; r = get_skip_rules(); print(f'dirs: {len(r[\"skip_dirs\"])}, exts: {len(r[\"skip_exts\"])}'); print(f'skip_dirs set: {len(get_skip_dirs())}'); print(f'skip_exts set: {len(get_skip_exts())}')"`

Expected: 输出 dirs: 44, exts: 16, skip_dirs set: 44, skip_exts set: 16

**Step 3: Commit**

```bash
git add backend/code_skip_rules.py
git commit -m "feat: 新增 code_skip_rules 模块 — 可配置排除规则管理"
```

---

### Task 2: 修改 code_parser.py — scan_directory 从配置读取

**Objective:** 让 scan_directory 从 code_skip_rules.json 读取排除规则

**Files:**
- Modify: `backend/code_parser.py`

**Step 1: 添加 import**

在 `code_parser.py` 顶部添加：
```python
from code_skip_rules import get_skip_dirs, get_skip_exts
```

**Step 2: 修改 scan_directory 函数**

将第 546-556 行的硬编码逻辑替换为从配置读取：

```python
    # 从配置文件读取排除规则
    effective_skip_dirs = get_skip_dirs()
    effective_skip_exts = get_skip_exts()
    if skip_dirs:
        effective_skip_dirs |= skip_dirs
    if skip_extensions:
        effective_skip_exts |= skip_extensions
```

**Step 3: 删除不再使用的硬编码常量**

删除 `DEFAULT_SKIP_DIRS`（70-86行）、`DEFAULT_SKIP_EXTS`（88-102行）、`UNIVERSAL_SKIP_DIRS`（105-118行）三个字典。

**Step 4: 验证**

Run: `cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend && source venv/bin/activate && python3 -c "from code_parser import scan_directory; print('import ok')"`

Expected: `import ok`

**Step 5: Commit**

```bash
git add backend/code_parser.py
git commit -m "refactor: scan_directory 从 code_skip_rules 读取排除规则，移除硬编码常量"
```

---

### Task 3: 后端 API — 添加 skip-rules 路由

**Objective:** 实现 GET/PUT/POST 三个接口

**Files:**
- Modify: `backend/code_routes.py`

**Step 1: 添加 import**

在 `code_routes.py` 顶部添加：
```python
from code_skip_rules import get_skip_rules, save_skip_rules, reset_skip_rules
```

**Step 2: 添加请求模型**

在 TraceRequest 之后添加：
```python
class SkipRulesRequest(BaseModel):
    skip_dirs: list[dict]  # [{"name": ".git", "category": "版本控制"}, ...]
    skip_exts: list[dict]  # [{"name": ".png", "category": "图片"}, ...]
```

**Step 3: 添加三个路由**

```python
@router.get("/skip-rules")
async def api_get_skip_rules():
    """获取当前排除规则"""
    return get_skip_rules()


@router.put("/skip-rules")
async def api_save_skip_rules(req: SkipRulesRequest):
    """保存排除规则"""
    rules = {"skip_dirs": req.skip_dirs, "skip_exts": req.skip_exts}
    save_skip_rules(rules)
    return {"status": "ok", "message": "规则已保存"}


@router.post("/skip-rules/reset")
async def api_reset_skip_rules():
    """恢复默认排除规则"""
    rules = reset_skip_rules()
    return {"status": "ok", "message": "已恢复默认规则", "rules": rules}
```

**Step 4: 验证接口**

Run:
```bash
curl -s http://localhost:8000/api/code/skip-rules | python3 -m json.tool | head -20
```

Expected: 返回包含 skip_dirs 和 skip_exts 的 JSON

**Step 5: Commit**

```bash
git add backend/code_routes.py
git commit -m "feat: 新增 skip-rules API — GET/PUT/reset 三个接口"
```

---

### Task 4: 前端 — 代码知识库 Tab 新增「仓库设置」按钮

**Objective:** 在代码知识库操作区新增设置入口

**Files:**
- Modify: `frontend/index.html`

**Step 1: 找到代码知识库 Tab 的操作区**

在代码知识库 Tab 的扫描表单附近，添加一个齿轮按钮。

**Step 2: 添加按钮**

在扫描按钮旁边添加：
```html
<button onclick="openSkipRulesModal()" class="px-3 py-2 bg-gray-100 text-gray-600 rounded-md hover:bg-gray-200 text-sm" title="排除规则设置">⚙️ 排除规则</button>
```

**Step 3: Commit**

```bash
git add frontend/index.html
git commit -m "feat: 代码知识库 Tab 新增排除规则设置按钮"
```

---

### Task 5: 前端 — 排除规则设置模态框

**Objective:** 实现规则编辑的模态框 UI

**Files:**
- Modify: `frontend/index.html`

**Step 1: 添加模态框 HTML**

在 `</body>` 之前添加模态框结构（两个表格区域 + 操作按钮）。

**Step 2: 添加 JavaScript 函数**

- `openSkipRulesModal()` — 打开模态框，加载规则
- `loadSkipRules()` — 调用 GET 接口，渲染表格
- `renderSkipTable(containerId, items, type)` — 渲染分组表格
- `addSkipRule(type)` — 添加规则
- `removeSkipRule(type, index)` — 删除规则
- `saveSkipRules()` — 调用 PUT 接口保存
- `resetSkipRules()` — 调用 reset 接口恢复默认

**Step 3: 验证**

浏览器打开 http://localhost:8000，切换到代码知识库 Tab，点击「排除规则」按钮，确认模态框正常显示。

**Step 4: Commit**

```bash
git add frontend/index.html
git commit -m "feat: 排除规则设置模态框 — 分组表格 UI + 增删改查"
```

---

### Task 6: 验证 — 完整流程测试

**Objective:** 验证端到端流程：编辑规则 → 保存 → 扫描确认生效

**Step 1: 启动服务**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo && ./start.sh
```

**Step 2: 浏览器验证**

1. 打开 http://localhost:8000
2. 切换到代码知识库 Tab
3. 点击「排除规则」按钮
4. 确认默认规则与原硬编码一致
5. 添加一个测试规则（如排除 `.md` 扩展名）
6. 保存，刷新页面确认持久化
7. 点击「恢复默认」确认回到初始状态

**Step 3: API 验证**

```bash
# 读取规则
curl -s http://localhost:8000/api/code/skip-rules | python3 -m json.tool | wc -l

# 保存规则（添加 .md 到排除列表）
curl -s -X PUT http://localhost:8000/api/code/skip-rules \
  -H "Content-Type: application/json" \
  -d '{"skip_dirs": [{"name": ".git", "category": "版本控制"}], "skip_exts": [{"name": ".md", "category": "文档"}]}' | python3 -m json.tool

# 确认已保存
curl -s http://localhost:8000/api/code/skip-rules | python3 -m json.tool

# 恢复默认
curl -s -X POST http://localhost:8000/api/code/skip-rules/reset | python3 -m json.tool | head -5
```

**Step 4: Commit**

```bash
git add -A
git commit -m "test: 排除规则完整流程验证通过"
```
