# 目录选择增强（Folder Picker）设计

> 日期：2026-06-10
> 作者：柳哥
> 状态：待 review

## 背景

扫描新仓库 tab（`frontend/tabs/code-repos.html`）当前有三种方式输入路径：

1. 手贴绝对路径
2. 点快捷入口（Desktop/Documents/MailProject，从 `/api/user/home` 动态取 home）
3. 点 📂 按钮 → 后端 `/api/code/browse` 弹内嵌"目录浏览器"（带上级/进入按钮）

第三种**能用但啰嗦**，要逐级点"进入"才能找到目标仓库。柳哥希望：
- 优先走系统原生文件夹选择弹窗（一次到位）
- macOS 上能直接"在 Finder 中打开"

## 目标

新增两个能力：
- **📁 选择** 按钮：浏览器能力探测，Chrome/Edge 走 `showDirectoryPicker`，Safari/Firefox 降级到 `<input type="file" webkitdirectory>`，都不支持时降级到现有目录浏览器
- **🔍 Finder** 按钮：把当前路径在系统文件管理器中打开（macOS `open` / Windows `explorer` / Linux `xdg-open`）

不影响现有功能。`index-old.html`（旧备份）、`data/code_repos.json`（已索引路径）、`docs/*.md`（文档示例）**不动**。

## 设计

### 1. 架构

```
[📁 选择] 按钮
    │
    ▼
codePickFolder()
    │
    ├─ window.showDirectoryPicker 可用? (Chrome 86+/Edge)
    │   → 调原生选择器 → dirHandle.name
    │   → GET /api/code/resolve-path?name=<dirName> 拿真实绝对路径
    │   → 唯一命中 → codeSelectDir
    │   → 多匹配 → 弹层让用户选
    │   → 零命中 → 报错 "在 home 下找不到该目录"
    │
    ├─ 隐藏的 <input type="file" webkitdirectory> 触发点击
    │   → files[0].webkitRelativePath 第一段 = 目录名
    │   → 同样走 /api/code/resolve-path
    │
    └─ 都不支持? → codeBrowseFolder() 兜底

[🔍 Finder] 按钮
    │
    ▼
codeOpenInFinder()
    → POST /api/code/open-in-finder { path }
    → macOS  → subprocess.Popen(["open", path])
    → Windows → subprocess.Popen(["explorer", path])
    → Linux  → subprocess.Popen(["xdg-open", path])
    → 后端校验：路径存在 + 是目录 + 不在黑名单
```

### 2. 前端改动

**文件**：`frontend/tabs/code-repos.html`（仅此一个）

**位置**：在路径输入框旁的"📂 浏览目录"按钮**右侧**新增两个按钮：

```html
<div class="flex gap-1 mb-2">
    <input id="codeRepoPath" type="text" placeholder="..." class="input flex-1" oninput="codeAutoFillName(this.value)">
    <button onclick="codePickFolder()" class="btn btn-secondary shrink-0" title="选择目录（系统原生）">📁</button>
    <button onclick="codeOpenInFinder()" class="btn btn-secondary shrink-0" title="在系统文件管理器中打开">🔍</button>
    <button onclick="codeBrowseFolder()" class="btn btn-secondary shrink-0" title="浏览目录">📂</button>
</div>
```

> 三按钮排排坐，从左到右：选 → 开 Finder → 浏览。原有 📂 行为完全不变。

**新增 JS**：

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

// 📁 选择：能力探测
async function codePickFolder() {
    // A. 优先 showDirectoryPicker
    if (window.showDirectoryPicker) {
        try {
            const dir = await window.showDirectoryPicker();
            const name = dir.name;
            // 浏览器不暴露绝对路径 → 走后端反查
            const path = await __resolvePathByName(name);
            codeSelectDir(path, name);
            return;
        } catch (e) {
            if (e.name === 'AbortError') return;  // 用户取消
            console.warn('showDirectoryPicker 失败, 降级:', e);
        }
    }
    // B. 降级 webkitdirectory
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
    const res = await fetch(`/api/code/resolve-path?name=${encodeURIComponent(name)}&parent=${encodeURIComponent(home)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '反查失败');
    if (data.matches && data.matches.length > 1) {
        // 多匹配 → 用 prompt 简化（生产可换 UI 弹层）
        const choice = prompt(`找到 ${data.matches.length} 个同名目录，请选择（输入序号）:\n` +
            data.matches.map((p, i) => `${i + 1}. ${p}`).join('\n'));
        const idx = parseInt(choice, 10) - 1;
        if (isNaN(idx) || !data.matches[idx]) throw new Error('无效选择');
        return data.matches[idx];
    }
    return data.path;
}

// 🔍 Finder
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
        // 非 macOS 系统上后端可能不执行只返回路径，提示用户手动复制
        if (data.skipped) {
            // 复制到剪贴板
            await navigator.clipboard.writeText(data.path);
            alert(`已复制路径到剪贴板: ${data.path}\n(${data.reason})`);
        }
    } catch (e) {
        alert('打开失败: ' + e.message);
    }
}
```

**暴露到 window**（在文件末尾 `window.xxx = xxx` 区追加）：
```js
window.codePickFolder = codePickFolder;
window.codeOpenInFinder = codeOpenInFinder;
```

### 3. 后端改动

**文件**：`backend/code_routes.py`（追加两个 endpoint，不动现有代码）

**A. `GET /api/code/resolve-path`**

```python
@router.get("/resolve-path")
async def resolve_path(name: str, parent: str | None = None):
    """在 parent 下找名为 name 的子目录。
    唯一命中 → { path }
    多匹配   → { matches: [...] }
    无匹配   → 404
    """
    search_root = os.path.abspath(parent) if parent else os.path.expanduser("~")
    if not os.path.isdir(search_root):
        raise HTTPException(400, detail=f"搜索根目录不存在: {search_root}")

    matches = []
    # 限深 3 层，避免巨型 home 卡死
    search_depth = 3
    search_root_depth = search_root.rstrip(os.sep).count(os.sep)

    for dirpath, dirnames, _ in os.walk(search_root):
        # 跳过隐藏目录和常见大目录
        dirnames[:] = [d for d in dirnames
                       if not d.startswith('.')
                       and d not in ('node_modules', 'venv', '__pycache__', 'Library', 'Applications')]
        if name in dirnames:
            matches.append(os.path.join(dirpath, name))
        # 限深
        cur_depth = dirpath.count(os.sep) - search_root_depth
        if cur_depth >= search_depth:
            dirnames[:] = []

    if len(matches) == 0:
        raise HTTPException(404, detail=f"在 {search_root} 下未找到目录: {name}")
    if len(matches) == 1:
        return {"path": matches[0]}
    return {"matches": matches[:20]}  # 最多返回 20 个防爆
```

**B. `POST /api/code/open-in-finder`**

```python
import platform
import subprocess

# 黑名单：危险目录禁止打开
_OPEN_DENY_PREFIXES = (
    os.path.expanduser("~/.ssh"),
    "/etc", "/var", "/usr", "/bin", "/sbin",
    "/System", "/Library/Apple", "/private",
)

@router.post("/open-in-finder")
async def open_in_finder(payload: dict):
    """在系统文件管理器中打开指定路径。"""
    path = (payload or {}).get("path", "").strip()
    if not path:
        raise HTTPException(400, detail="path 必填")
    path = os.path.abspath(path)
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

### 4. 不做的事

- ❌ Electron / Tauri 化（成本太高，不在范围内）
- ❌ 改 `index-old.html`（历史备份，不加载）
- ❌ 改 `data/code_repos.json` 里的旧路径（换电脑用户重新扫即可）
- ❌ 改 `docs/*.md` 里的示例（文档示例不影响运行）
- ❌ 改现有 `codeBrowseFolder()` 行为（保留兜底）

### 5. 测试

**后端**（`backend/tests/test_folder_picker.py`，新文件）：

| 用例 | 验证点 |
|------|--------|
| `test_resolve_path_unique` | 单个匹配 → 返回 `{path}` |
| `test_resolve_path_multiple` | 同名多目录 → 返回 `{matches: [...]}`，截断到 20 |
| `test_resolve_path_not_found` | 无匹配 → 404 |
| `test_resolve_path_skips_hidden` | `.git` 等隐藏目录不被算入 |
| `test_resolve_path_depth_limit` | 超过 3 层的不算入 |
| `test_resolve_path_parent_invalid` | parent 不存在 → 400 |
| `test_open_in_finder_darwin` | mock subprocess.Popen，验证调用 `["open", path]` |
| `test_open_in_finder_windows` | mock 后验证 `["explorer", path]` |
| `test_open_in_finder_path_invalid` | 路径不存在 → 400 |
| `test_open_in_finder_blacklist` | `~/.ssh` → 403 |
| `test_open_in_finder_unsupported_os` | 未知 system → 返回 `{skipped: True}` |

**手动验证**（记录到 `docs/CHANGELOG.md` 或 PR 描述）：

- Chrome 弹原生选择器，选完路径自动填入 + 仓库名自动填入
- Safari 走 webkitdirectory，降级体验正常
- macOS 点 🔍 Finder 真的在 Finder 中打开
- 路径输入 `~/.ssh` → 后端拒绝 + 前端报错
- 同名多目录场景，弹序号选择正常

### 6. 文件清单

| 操作 | 路径 |
|------|------|
| 改 | `frontend/tabs/code-repos.html`（+ ~60 行 JS，+ 2 个按钮） |
| 改 | `backend/code_routes.py`（+ 2 个 endpoint，~50 行） |
| 新建 | `backend/tests/test_folder_picker.py`（~100 行） |
| 不动 | `frontend/index-old.html`、`data/code_repos.json`、`docs/*.md` |

### 7. 风险 & 兜底

| 风险 | 兜底 |
|------|------|
| `showDirectoryPicker` 需要用户手势触发 | `codePickFolder` 直接由 onclick 触发，满足要求 |
| 用户取消选择 | 捕获 `AbortError` 静默返回 |
| webkitdirectory 拿不到绝对路径 | 走后端反查；多匹配用 prompt 简化（生产可换 UI 弹层） |
| 反查时 home 太大扫得慢 | 限深 3 层 + 跳过大目录（`node_modules`/`venv`/`Library` 等） |
| `open` 命令在某些 Linux 上没装 | 捕获 `FileNotFoundError` → 返回 `{skipped: True}`，前端复制路径到剪贴板 |
| 跨域 | 都在同源，不涉及 |
