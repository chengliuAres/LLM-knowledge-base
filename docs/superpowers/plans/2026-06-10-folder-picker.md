# Folder Picker 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在扫描新仓库 tab 加 "📁 选择" 和 "🔍 Finder" 两个按钮，浏览器能力探测后走系统原生文件夹选择器或降级到 webkitdirectory，并支持在系统文件管理器（Finder/Explorer/xdg-open）中打开路径。

**Architecture:** 前端加按钮 + JS 能力探测分支；后端新增两个 endpoint：`/api/code/resolve-path`（按名字反查真实路径，限深 3 层）和 `/api/code/open-in-finder`（跨平台调用系统命令 + 路径黑名单校验）。现有 `/api/user/home` 和 `/api/code/browse` 行为完全保留。

**Tech Stack:** Python FastAPI（后端）、原生 JavaScript（前端）、pytest + httpx TestClient（测试）

---

## 文件结构

| 操作 | 路径 | 职责 |
|------|------|------|
| 改 | `backend/code_routes.py` | 新增 `/resolve-path` 和 `/open-in-finder` 两个 endpoint |
| 新建 | `backend/tests/test_folder_picker.py` | 两个 endpoint 的单元/集成测试 |
| 改 | `frontend/tabs/code-repos.html` | 新增两个按钮 + `codePickFolder()` / `codeOpenInFinder()` JS |
| 不动 | `frontend/index-old.html` | 历史备份 |
| 不动 | `data/code_repos.json` | 已索引路径 |
| 不动 | `docs/*.md` | 文档示例 |

---

## Task 1: 后端 `/api/code/resolve-path` 端点 + 测试（TDD）

**Files:**
- Create: `backend/tests/test_folder_picker.py`
- Modify: `backend/code_routes.py`（在文件末尾追加 endpoint）

- [ ] **Step 1: 写失败的测试 `test_resolve_path_unique`**

在 `backend/tests/test_folder_picker.py` 写入：

```python
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
```

- [ ] **Step 2: 跑测试，预期失败（endpoint 还没实现）**

Run: `cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend && python3 -m pytest tests/test_folder_picker.py::test_resolve_path_unique -v`
Expected: FAIL with `404 Not Found` 或 `405 Method Not Allowed`

- [ ] **Step 3: 实现 `/api/code/resolve-path` endpoint**

在 `backend/code_routes.py` **文件末尾**追加：

```python
import platform
import subprocess
from typing import List, Optional


# ── GET /api/code/resolve-path ─────────────────────────────────

@router.get("/resolve-path")
async def resolve_path(name: str, parent: Optional[str] = None):
    """在 parent 下找名为 name 的子目录。

    - 唯一命中：返回 {"path": "..."}
    - 多匹配：返回 {"matches": [...]}（最多 20 个）
    - 无匹配：404
    - parent 无效：400
    """
    search_root = os.path.abspath(parent) if parent else os.path.expanduser("~")
    if not os.path.isdir(search_root):
        raise HTTPException(400, detail=f"搜索根目录不存在: {search_root}")

    # 跳过这些大目录避免扫得慢
    SKIP_DIRS = {".git", "node_modules", "venv", "__pycache__", "Library", "Applications"}

    matches: List[str] = []
    search_root = search_root.rstrip(os.sep)
    root_depth = search_root.count(os.sep)
    MAX_DEPTH = 3

    for dirpath, dirnames, _ in os.walk(search_root):
        # 过滤隐藏目录和大目录
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS]
        if name in dirnames:
            matches.append(os.path.join(dirpath, name))
        # 限深
        cur_depth = dirpath.count(os.sep) - root_depth
        if cur_depth >= MAX_DEPTH:
            dirnames[:] = []

    if len(matches) == 0:
        raise HTTPException(404, detail=f"在 {search_root} 下未找到目录: {name}")
    if len(matches) == 1:
        return {"path": matches[0]}
    return {"matches": matches[:20]}
```

- [ ] **Step 4: 跑测试，预期通过**

Run: `cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend && python3 -m pytest tests/test_folder_picker.py::test_resolve_path_unique -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo
git add backend/code_routes.py backend/tests/test_folder_picker.py
git commit -m "feat(code-routes): 新增 /api/code/resolve-path 按名字反查真实路径"
```

---

## Task 2: `/api/code/resolve-path` 多匹配 / 无匹配 / 隐藏目录 / 限深 / 无效 parent 测试

**Files:**
- Modify: `backend/tests/test_folder_picker.py`

- [ ] **Step 1: 追加测试**

在 `test_resolve_path_unique` 后面追加：

```python
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


def test_resolve_path_not_found(tmp_path):
    """无匹配 → 404"""
    (tmp_path / "other").mkdir()
    res = client.get(f"/api/code/resolve-path?name=missing&parent={tmp_path}")
    assert res.status_code == 404


def test_resolve_path_skips_hidden(tmp_path):
    """隐藏目录不被算入"""
    (tmp_path / ".hiddenrepo").mkdir()
    res = client.get(f"/api/code/resolve-path?name=hiddenrepo&parent={tmp_path}")
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
```

- [ ] **Step 2: 跑全部 resolve-path 测试**

Run: `cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend && python3 -m pytest tests/test_folder_picker.py -v -k resolve_path`
Expected: 全部 6 个 PASS

- [ ] **Step 3: 提交**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo
git add backend/tests/test_folder_picker.py
git commit -m "test(code-routes): 补全 resolve-path 多匹配/无匹配/隐藏/限深/无效 parent 用例"
```

---

## Task 3: 后端 `/api/code/open-in-finder` 端点 + 测试（TDD）

**Files:**
- Modify: `backend/tests/test_folder_picker.py`
- Modify: `backend/code_routes.py`

- [ ] **Step 1: 写失败的测试**

在 `test_folder_picker.py` 追加：

```python
from unittest.mock import patch, MagicMock


# ── /api/code/open-in-finder ───────────────────────────────────

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
    """~/.ssh 拒绝 → 403"""
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    fake_ssh = tmp_path / ".ssh"
    fake_ssh.mkdir()
    res = client.post("/api/code/open-in-finder", json={"path": str(fake_ssh)})
    assert res.status_code == 403


def test_open_in_finder_blacklist_etc(tmp_path, monkeypatch):
    """/etc 系统目录 → 403"""
    monkeypatch.setattr("platform.system", lambda: "Darwin")
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
```

- [ ] **Step 2: 跑测试，预期失败（endpoint 还没实现）**

Run: `cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend && python3 -m pytest tests/test_folder_picker.py -v -k open_in_finder`
Expected: 全部 FAIL（404 Not Found）

- [ ] **Step 3: 实现 `/api/code/open-in-finder` endpoint**

在 `backend/code_routes.py` 末尾追加：

```python
# 黑名单：危险目录禁止打开
_OPEN_DENY_PREFIXES = (
    os.path.expanduser("~/.ssh"),
    "/etc", "/var", "/usr", "/bin", "/sbin",
    "/System", "/Library/Apple", "/private",
)


@router.post("/open-in-finder")
async def open_in_finder(payload: dict):
    """在系统文件管理器中打开指定路径。

    - macOS: open
    - Windows: explorer
    - Linux: xdg-open
    - 未知系统 / 命令缺失: 返回 {skipped: True} 让前端兜底
    """
    raw = (payload or {}).get("path", "")
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(400, detail="path 必填且为非空字符串")

    path = os.path.abspath(raw.strip())
    if not os.path.isdir(path):
        raise HTTPException(400, detail=f"不是有效目录: {path}")

    for deny in _OPEN_DENY_PREFIXES:
        if path.startswith(deny):
            raise HTTPException(403, detail=f"禁止访问: {deny}")

    system = platform.system()
    if system == "Darwin":
        cmd = ["open", path]
    elif system == "Windows":
        cmd = ["explorer", path]
    elif system == "Linux":
        cmd = ["xdg-open", path]
    else:
        return {"path": path, "skipped": True, "reason": f"不支持的系统: {system}"}

    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        return {"path": path, "skipped": True, "reason": f"未找到命令: {cmd[0]}"}
    return {"path": path, "opened": True}
```

- [ ] **Step 4: 跑全部 open-in-finder 测试**

Run: `cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend && python3 -m pytest tests/test_folder_picker.py -v -k open_in_finder`
Expected: 全部 8 个 PASS

- [ ] **Step 5: 跑全量测试确认无回归**

Run: `cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend && python3 -m pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 6: 提交**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo
git add backend/code_routes.py backend/tests/test_folder_picker.py
git commit -m "feat(code-routes): 新增 /api/code/open-in-finder 跨平台唤起系统文件管理器"
```

---

## Task 4: 前端 — 新增"📁 选择"和"🔍 Finder"按钮 + JS 函数

**Files:**
- Modify: `frontend/tabs/code-repos.html`

- [ ] **Step 1: 改 HTML，把路径输入框右边的按钮从 1 个变 3 个**

定位到 `code-repos.html:10-13`（包含 `id="codeRepoPath"` 那段），替换为：

```html
                <div class="flex gap-1 mb-2">
                    <input id="codeRepoPath" type="text" placeholder="粘贴路径或点下方快捷入口" class="input flex-1" oninput="codeAutoFillName(this.value)">
                    <button onclick="codePickFolder()" class="btn btn-secondary shrink-0" title="选择目录（系统原生）">📁</button>
                    <button onclick="codeOpenInFinder()" class="btn btn-secondary shrink-0" title="在系统文件管理器中打开">🔍</button>
                    <button onclick="codeBrowseFolder()" class="btn btn-secondary shrink-0" title="浏览目录">📂</button>
                </div>
```

- [ ] **Step 2: 在 `__ensureWebkitInput` 紧邻处（`codeLoadDirs` 函数后面）追加 `codePickFolder` 和 `codeOpenInFinder`**

定位到 `code-repos.html` 的 `codeSelectDir` 函数后面（line 482 附近），追加：

```js
// 隐藏的 webkitdirectory input（页面加载时插入一次）
let __webkitInput = null;
function __ensureWebkitInput() {
    if (__webkitInput) return __webkitInput;
    __webkitInput = document.createElement('input');
    __webkitInput.type = 'file';
    __webkitInput.webkitdirectory = true;
    __webkitInput.style.display = 'none';
    document.body.appendChild(__webkitInput);
    return __webkitInput;
}

// 📁 选择：能力探测（showDirectoryPicker → webkitdirectory → 现有目录浏览器）
async function codePickFolder() {
    // A. 优先 showDirectoryPicker（Chrome 86+ / Edge）
    if (window.showDirectoryPicker) {
        try {
            const dir = await window.showDirectoryPicker();
            const name = dir.name;
            const path = await __resolvePathByName(name);
            codeSelectDir(path, name);
            return;
        } catch (e) {
            if (e.name === 'AbortError') return;  // 用户取消
            console.warn('showDirectoryPicker 失败, 降级:', e);
        }
    }
    // B. 降级 webkitdirectory（Safari / Firefox）
    const input = __ensureWebkitInput();
    input.value = '';  // 允许重复选同一目录
    input.onchange = async () => {
        const file = input.files[0];
        if (!file) return;
        const name = file.webkitRelativePath.split('/')[0];
        try {
            const path = await __resolvePathByName(name);
            codeSelectDir(path, name);
        } catch (e) {
            alert('选择目录失败: ' + e.message);
        }
    };
    input.click();
}

// 通过名字反查真实路径（同名多个时弹层让用户选）
async function __resolvePathByName(name) {
    const home = window.__USER_HOME || '';
    const url = `/api/code/resolve-path?name=${encodeURIComponent(name)}&parent=${encodeURIComponent(home)}`;
    const res = await fetch(url);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '反查失败');
    if (data.matches && data.matches.length > 1) {
        const choice = prompt(`找到 ${data.matches.length} 个同名目录，请选择（输入序号）:\n` +
            data.matches.map((p, i) => `${i + 1}. ${p}`).join('\n'));
        const idx = parseInt(choice, 10) - 1;
        if (isNaN(idx) || !data.matches[idx]) throw new Error('无效选择');
        return data.matches[idx];
    }
    return data.path;
}

// 🔍 Finder：在系统文件管理器中打开当前路径
async function codeOpenInFinder() {
    const path = document.getElementById('codeRepoPath').value.trim();
    if (!path) { alert('请先输入路径'); return; }
    try {
        const res = await fetch('/api/code/open-in-finder', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail);
        if (data.skipped) {
            // 非 macOS 或命令缺失 → 复制到剪贴板兜底
            if (navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(data.path);
            }
            alert(`已复制路径到剪贴板: ${data.path}\n(${data.reason})`);
        }
    } catch (e) {
        alert('打开失败: ' + e.message);
    }
}
```

- [ ] **Step 3: 把新函数挂到 window**

定位到 `code-repos.html` 的 `window.codeBrowseFolder = codeBrowseFolder;` 那行（line 824 附近），在它前面追加：

```js
window.codePickFolder = codePickFolder;
window.codeOpenInFinder = codeOpenInFinder;
```

- [ ] **Step 4: 浏览器手动验证（用 Chrome devtools 跑后端 + 打开前端）**

Run:
```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend && python3 main.py
```
然后访问 `http://localhost:8000`，切到"代码仓库"tab：
- 点 "📁 选择" 按钮 → 应弹系统原生选择器
- 选一个目录后 → 路径自动填入 + 仓库名自动填入
- 点 "🔍 Finder" 按钮 → 应在 macOS Finder 中打开
- 在 Chrome devtools console 检查：无报错

- [ ] **Step 5: 提交**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo
git add frontend/tabs/code-repos.html
git commit -m "feat(code-repos): 新增 📁 选择 / 🔍 Finder 按钮，能力探测 + 系统文件管理器唤起"
```

---

## Task 5: 最终全量验证 + 文档更新

**Files:**
- Modify: `docs/CHANGELOG.md`（如不存在则新建）

- [ ] **Step 1: 跑后端全量测试**

Run: `cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend && python3 -m pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 2: 启动后端，curl 测两个新 endpoint**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/backend && python3 main.py &
sleep 3
curl -s 'http://localhost:8000/api/code/resolve-path?name=backend&parent=/Users/admin/Desktop/AI产出/email-wiki-demo' | python3 -m json.tool
curl -s -X POST 'http://localhost:8000/api/code/open-in-finder' -H 'Content-Type: application/json' -d '{"path":"/Users/admin/Desktop/AI产出/email-wiki-demo"}' | python3 -m json.tool
kill %1
```
Expected: 两个都返回 200 + 合理 JSON

- [ ] **Step 3: 更新 CHANGELOG**

在 `docs/CHANGELOG.md` 顶部追加：

```markdown
## 2026-06-10

### feat(code-repos): 目录选择增强

- 新增 📁 选择按钮：Chrome/Edge 走 showDirectoryPicker，Safari/Firefox 降级 webkitdirectory，无支持时降级到现有目录浏览器
- 新增 🔍 Finder 按钮：在系统文件管理器中打开当前路径（macOS open / Windows explorer / Linux xdg-open）
- 后端新增 `/api/code/resolve-path`（按名字反查真实路径，限深 3 层，跳过隐藏和大目录）
- 后端新增 `/api/code/open-in-finder`（跨平台唤起 + 路径黑名单校验）
- 原有 `codeBrowseFolder()` 行为完全保留作为兜底
```

- [ ] **Step 4: 提交**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo
git add docs/CHANGELOG.md
git commit -m "docs: CHANGELOG 记录目录选择增强功能"
```

---

## Self-Review

| 检查项 | 结果 |
|------|------|
| Spec 覆盖 | §1-§5 全部对应到 Task 1-5 |
| 占位符 | 无 TBD/TODO，所有代码块完整 |
| 类型一致 | `codePickFolder` / `codeOpenInFinder` / `__resolvePathByName` 在 Task 4 定义并在 Task 4 挂到 window，Task 1-3 不引用 |
| 限深常量 | Task 1 用 `MAX_DEPTH = 3`，Task 2 测试也是 3 层 → 一致 |
| 黑名单 | Task 3 `OPEN_DENY_PREFIXES` 与 spec §3.B 完全一致 |
