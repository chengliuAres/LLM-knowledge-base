# Agent 接入页 — Skill 集成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在侧栏原「🔌 MCP 接入」tab 内（改名「🤖 Agent 接入」）加「Skill 接入」互斥大 tab，Skill 侧 4 个子 tab（安装指南 / SKILL.md 预览 / 脚本能力清单 / 下载 zip），后端新增 3 个 API 让前端能读 SKILL.md / 列 zip 元信息 / 下载 zip。

**Architecture:** TDD 风格，从后端 3 个 API 起步（每个 API 先写测试再写实现），再切到前端 — code-mcp.html 改最小（h2 标题 + 顶层 2-tab 按钮 + 包裹原内容），新 tab HTML/JS 独立文件。所有改动限定在 8 个文件内，~520 行净增。

**Tech Stack:** FastAPI / Pydantic v1 / zipfile / vanilla HTML + Tailwind runtime / 原生 JS（无构建步骤）

---

## Task 1：后端 `code_skill_routes.py` — `/api/skill/raw`

**Files:**
- Create: `backend/code_skill_routes.py`
- Test: `backend/tests/test_skill_routes.py`

- [ ] **Step 1：写失败测试**

新建 `backend/tests/test_skill_routes.py`：

```python
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
```

- [ ] **Step 2：跑测试确认失败**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_skill_routes.py -v`
Expected: `ModuleNotFoundError: No module named 'code_skill_routes'`

- [ ] **Step 3：写最小实现**

新建 `backend/code_skill_routes.py`：

```python
"""Skill 接入子页 — 后端 API (FastAPI router)"""
import io
import os
import zipfile

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter()

# export/skill/ 是项目根的相对路径（main.py 启动时 cwd = backend/，所以是 ../export/skill）
EXPORT_DIR = os.path.join(os.path.dirname(__file__), "..", "export", "skill")


def _list_export_files() -> list:
    """列出 export/skill/ 下所有文件 + 大小（相对 EXPORT_DIR）"""
    if not os.path.isdir(EXPORT_DIR):
        return []
    out = []
    for root, _, files in os.walk(EXPORT_DIR):
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, EXPORT_DIR)
            out.append({"name": rel, "size": os.path.getsize(full)})
    return out


@router.get("/api/skill/raw")
def get_skill_raw():
    """返回 SKILL.md 文本 + 元信息"""
    path = os.path.join(EXPORT_DIR, "SKILL.md")
    if not os.path.exists(path):
        return {"error": "SKILL.md missing", "path": path}
    content = open(path, encoding="utf-8").read()
    return {
        "content": content,
        "size": len(content),
        "files": _list_export_files(),
    }


@router.get("/api/skill/info")
def get_skill_info():
    """zip 元信息：大小、文件数、清单"""
    files = _list_export_files()
    total_size = sum(f["size"] for f in files)
    return {"file_count": len(files), "total_size": total_size, "files": files}


@router.get("/api/skill/download")
def download_skill():
    """打包 export/skill/ 为 zip，根目录重命名 code-search/"""
    if not os.path.isdir(EXPORT_DIR):
        return {"error": f"{EXPORT_DIR} not found"}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(EXPORT_DIR):
            for f in files:
                src = os.path.join(root, f)
                arc = os.path.join("code-search", os.path.relpath(src, EXPORT_DIR))
                zf.write(src, arc)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="code-search.zip"'},
    )
```

- [ ] **Step 4：注册 router 到 main.py**

修改 `backend/main.py`，在 import 区和 `app.include_router` 块附近加 1 行：

```python
from code_skill_routes import router as skill_router
# ... 找到其他 include_router 调用附近 ...
app.include_router(skill_router)
```

具体位置：搜 `app.include_router`，**最后一行**后加 `app.include_router(skill_router)`。

- [ ] **Step 5：跑测试确认通过**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_skill_routes.py -v`
Expected: `3 passed`

- [ ] **Step 6：端到端 curl 验证**

```bash
cd backend && source venv/bin/activate
# 启动服务（如果还没启）
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 &
sleep 3

# 验证 raw
curl -fsS http://localhost:8000/api/skill/raw | python3 -c "import json, sys; d=json.load(sys.stdin); print('size:', d['size']); print('files:', len(d['files']))"
# 期望输出：size: 28254，files: 3

# 验证 info
curl -fsS http://localhost:8000/api/skill/info | python3 -c "import json, sys; d=json.load(sys.stdin); print('count:', d['file_count']); print('total_size:', d['total_size'])"
# 期望输出：count: 3, total_size: ~38KB

# 验证 download
curl -fsS -o /tmp/cs.zip http://localhost:8000/api/skill/download
unzip -l /tmp/cs.zip
# 期望输出：code-search/SKILL.md, code-search/README.md, code-search/scripts/kb_api.py

# 关掉服务
kill %1
```

- [ ] **Step 7：commit**

```bash
git -C .claude/worktrees/feat+skill-integration-tab add backend/code_skill_routes.py backend/tests/test_skill_routes.py backend/main.py
git -C .claude/worktrees/feat+skill-integration-tab commit -m "feat(skill): 后端 /api/skill/{raw,info,download} 三件套"
```

---

## Task 2：后端 `code_skill_routes.py` — `/api/skill/commands`（ast 解析 kb_api.py）

**Files:**
- Modify: `backend/code_skill_routes.py`
- Modify: `backend/tests/test_skill_routes.py`

- [ ] **Step 1：写失败测试**

在 `backend/tests/test_skill_routes.py` 末尾追加：

```python
def test_skill_commands_parses_kb_api():
    """GET /api/skill/commands 应解析 kb_api.py 的 argparse subcommands"""
    resp = client.get("/api/skill/commands")
    assert resp.status_code == 200
    data = resp.json()
    assert "commands" in data
    assert len(data["commands"]) >= 3, "kb_api.py 至少有 search/chat/trace/file/repos 5 个 subcommand"
    names = [c["name"] for c in data["commands"]]
    assert "search" in names
    assert "trace" in names
```

- [ ] **Step 2：跑测试确认失败**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_skill_routes.py::test_skill_commands_parses_kb_api -v`
Expected: `404 Not Found`（端点还没注册）

- [ ] **Step 3：实现 `/api/skill/commands`**

在 `backend/code_skill_routes.py` 顶部加 import + 末尾加新端点：

```python
import ast  # 顶部新增
```

在文件末尾追加：

```python
def _parse_kb_api_commands() -> list:
    """用 ast 解析 kb_api.py 的 argparse subparsers/add_parser 节点"""
    py_path = os.path.join(EXPORT_DIR, "scripts", "kb_api.py")
    if not os.path.exists(py_path):
        return []
    try:
        source = open(py_path, encoding="utf-8").read()
        tree = ast.parse(source)
    except SyntaxError:
        return []
    commands = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # 匹配 subparsers.add_parser("xxx", help="yyy")
            if (isinstance(node.func, ast.Attribute)
                    and node.func.attr == "add_parser"
                    and node.args and isinstance(node.args[0], ast.Constant)):
                name = node.args[0].value
                help_text = ""
                for kw in node.keywords:
                    if kw.arg == "help" and isinstance(kw.value, ast.Constant):
                        help_text = kw.value.value
                commands.append({"name": name, "help": help_text})
    return commands


@router.get("/api/skill/commands")
def get_skill_commands():
    """解析 kb_api.py 的 argparse subcommands，返回 [{name, help}]"""
    return {"commands": _parse_kb_api_commands()}
```

- [ ] **Step 4：跑测试确认通过**

Run: `cd backend && source venv/bin/activate && python -m pytest tests/test_skill_routes.py -v`
Expected: `4 passed`

- [ ] **Step 5：curl 验证**

```bash
cd backend && source venv/bin/activate
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 &
sleep 3
curl -fsS http://localhost:8000/api/skill/commands | python3 -m json.tool
# 期望输出：commands 列表含 search/chat/trace/file/repos 等
kill %1
```

- [ ] **Step 6：commit**

```bash
git -C .claude/worktrees/feat+skill-integration-tab add backend/code_skill_routes.py backend/tests/test_skill_routes.py
git -C .claude/worktrees/feat+skill-integration-tab commit -m "feat(skill): /api/skill/commands ast 解析 kb_api.py subcommands"
```

---

## Task 3：前端 — `code-mcp.html` 改名 + 加顶层 2-tab 切换

**Files:**
- Modify: `frontend/tabs/code-mcp.html`
- Modify: `frontend/js/code-mcp.js`

- [ ] **Step 1：手动 baseline（浏览器现状）**

打开浏览器访问 `localhost:8000/#code-mcp`，确认：
- 侧栏显示「🔌 MCP 接入」
- 进入 tab 后顶部显示「🔌 MCP 接入」大标题
- 5 个子 tab 正常切换

- [ ] **Step 2：改 h2 标题 + 改侧栏入口**

打开 `frontend/tabs/code-mcp.html`，**第 4 行**：
```html
<!-- 原 -->
<h2 class="text-lg font-semibold text-white">🔌 MCP 接入</h2>
<!-- 改 -->
<h2 class="text-lg font-semibold text-white">🤖 Agent 接入</h2>
```

侧栏入口在 `frontend/index.html` 里搜 `MCP 接入`：

```bash
grep -n "MCP 接入" frontend/index.html
```

把所有匹配项改成「🤖 Agent 接入」（**只改 sidebar tab 的文字**，**别动 router 配置**，因为 router 仍然把 `#code-mcp` 当 hash key）

- [ ] **Step 3：加顶层 2-tab 切换按钮**

在 `frontend/tabs/code-mcp.html` 第 4 行（h2 之后）插入：

```html
<!-- 顶层 2-tab 切换：MCP 接入 / Skill 接入 -->
<div class="flex flex-wrap gap-2 border-b pb-3" style="border-color: var(--color-border);">
  <button id="agent-tab-mcp" class="agent-tab-btn active px-3 py-1.5 rounded text-sm font-medium transition-colors whitespace-nowrap"
    style="background: var(--color-accent); color: var(--color-on-primary);" onclick="switchAgentTab('mcp')">🔌 MCP 接入</button>
  <button id="agent-tab-skill" class="agent-tab-btn px-3 py-1.5 rounded text-sm font-medium transition-colors whitespace-nowrap"
    style="color: var(--color-muted);" onclick="switchAgentTab('skill')">📦 Skill 接入</button>
</div>
```

- [ ] **Step 4：把原 5 子 tab 包裹到 `<div id="agent-mcp-side">`**

在 `code-mcp.html` 第 21 行（`<!-- 内容区：接入指南 -->` 之前）插入：
```html
<div id="agent-mcp-side">
```

在文件最末尾 `</div>` 之前（第 359 行的 `<!-- Toast -->` 之前）插入：
```html
</div><!-- /agent-mcp-side -->
```

- [ ] **Step 5：在 code-mcp.html 末尾加 `switchAgentTab` 函数**

在文件最末尾 `</div>` 之后追加（在最后那个 `<script>` 之后）：

```html
<script>
function switchAgentTab(name) {
  var sides = { mcp: 'agent-mcp-side', skill: 'agent-skill-side' };
  var btns = { mcp: 'agent-tab-mcp', skill: 'agent-tab-skill' };
  Object.keys(sides).forEach(function(k) {
    var side = document.getElementById(sides[k]);
    if (side) side.classList.toggle('hidden', k !== name);
    var btn = document.getElementById(btns[k]);
    if (btn) {
      btn.classList.toggle('active', k === name);
      btn.style.background = (k === name) ? 'var(--color-accent)' : '';
      btn.style.color = (k === name) ? 'var(--color-on-primary)' : 'var(--color-muted)';
    }
  });
  if (name === 'skill') {
    // 懒加载 skill 侧
    var skillSide = document.getElementById('agent-skill-side');
    if (skillSide && skillSide.children.length === 0) {
      fetch('tabs/code-skill.html').then(function(r) { return r.text(); }).then(function(html) {
        skillSide.innerHTML = html;
        if (typeof window.initSkillTab === 'function') window.initSkillTab();
      });
    } else if (typeof window.initSkillTab === 'function') {
      window.initSkillTab();
    }
  }
}
</script>
```

⚠️ **等等**——`switchAgentTab` 调 `fetch('tabs/code-skill.html')` 是设计成"懒加载"，但**这个文件还不存在**（Task 4 才创建）。先写 TODO 占位也跑不通——`code-skill.html` 缺失时 fetch 会 404。

**修正**：把"懒加载 skill 侧"那段**先注释掉**或**降级为 window.__skillSideLoaded 判断**——本次改动只完成"MCP 侧 0 业务内容改动 + 顶层 2-tab 切换 UI"，skill 侧 HTML 由 Task 4 直接放在 `code-mcp.html` 末尾的 `<div id="agent-skill-side" class="hidden"></div>` 占位容器里（**不走 fetch**）。

**最终版**（`switchAgentTab` 函数，只做 UI 切换，不调 fetch）：

```html
<script>
function switchAgentTab(name) {
  var sides = { mcp: 'agent-mcp-side', skill: 'agent-skill-side' };
  var btns = { mcp: 'agent-tab-mcp', skill: 'agent-tab-skill' };
  Object.keys(sides).forEach(function(k) {
    var side = document.getElementById(sides[k]);
    if (side) side.classList.toggle('hidden', k !== name);
    var btn = document.getElementById(btns[k]);
    if (btn) {
      btn.classList.toggle('active', k === name);
      btn.style.background = (k === name) ? 'var(--color-accent)' : '';
      btn.style.color = (k === name) ? 'var(--color-on-primary)' : 'var(--color-muted)';
    }
  });
  if (name === 'skill' && typeof window.initSkillTab === 'function') {
    window.initSkillTab();
  }
}
</script>
```

并且在 `code-mcp.html` 末尾加 skill 侧占位容器（在 `</div><!-- /agent-mcp-side -->` 之后）：

```html
<div id="agent-skill-side" class="hidden">
  <!-- Task 4 填充：code-skill.html 内的内容会由 code-skill.js 渲染到这里 -->
</div>
```

⚠️ **再次决策点**：Task 4 应该用 (a) 内联静态内容写在 code-mcp.html，还是 (b) fetch 懒加载 code-skill.html？

- **(a) 内联**：code-mcp.html 仍可能 ~500 行，但**避免 fetch + 0 业务损失**（前端路由是 router.js 控制的，#code-mcp 进 tab 时 router 会 fetch `tabs/code-mcp.html` 整文件作为 tab 内容——所以"懒加载"已经发生了一次）
- **(b) fetch 懒加载**：符合 spec 原始意图，但 fetch 失败时用户体验差（404 后看到空容器）

**默认选 (a) 内联**——`code-skill.html` 这个独立 tab HTML **本次用不到**（它是为"未来如果切到顶级 tab"留的后路），把 skill 侧 HTML 直接写在 `code-mcp.html` 末尾的 `<div id="agent-skill-side">` 里。

- [ ] **Step 6：浏览器手测 MCP 侧不破**

1. 启动后端（`./start.sh`）
2. 硬刷 `localhost:8000/#code-mcp`（Cmd+Shift+R）
3. 确认：
   - 侧栏显示「🤖 Agent 接入」
   - 顶部大标题「🤖 Agent 接入」
   - 顶层 2-tab 按钮「MCP 接入」（高亮）/「Skill 接入」（灰色）
   - 点「MCP 接入」→ 显示原 5 子 tab（**全部正常**）
   - 点「Skill 接入」→ 显示空白占位（"Task 4 填充"）——**这是预期**

- [ ] **Step 7：commit**

```bash
git -C .claude/worktrees/feat+skill-integration-tab add frontend/tabs/code-mcp.html frontend/index.html
git -C .claude/worktrees/feat+skill-integration-tab commit -m "feat(agent-tab): 侧栏改名 + 顶层 2-tab 切换 (MCP/Skill)"
```

---

## Task 4：前端 — Skill 侧 4 子 tab 内容

**Files:**
- Modify: `frontend/tabs/code-mcp.html`（在末尾 `<div id="agent-skill-side">` 里塞内容）
- Create: `frontend/js/code-skill.js`

- [ ] **Step 1：写 code-skill.js（4 子 tab 切换 + 懒加载函数）**

新建 `frontend/js/code-skill.js`：

```javascript
/**
 * Skill 接入子页 — 4 子 tab 切换 + 数据加载
 * 由 code-mcp.html 的 switchAgentTab('skill') 触发
 */
(function () {
  var cache = { md: null, info: null, commands: null };

  window.switchSkillTab = function (name) {
    document.querySelectorAll('.skill-tab-btn').forEach(function (btn) {
      var isActive = btn.dataset.skillTab === name;
      btn.classList.toggle('active', isActive);
      btn.style.background = isActive ? 'var(--color-accent)' : '';
      btn.style.color = isActive ? 'var(--color-on-primary)' : 'var(--color-muted)';
    });
    document.querySelectorAll('.skill-tab-content').forEach(function (el) {
      el.classList.toggle('hidden', el.id !== 'skill-tab-' + name);
    });
    if (name === 'md' && !cache.md) loadSkillMd();
    if (name === 'commands' && !cache.commands) loadSkillCommands();
    if (name === 'download' && !cache.info) loadSkillInfo();
  };

  window.initSkillTab = function () {
    // 默认切到第 1 个子 tab (安装指南)
    if (!document.querySelector('.skill-tab-content:not(.hidden)')) {
      window.switchSkillTab('install');
    }
  };

  function loadSkillMd() {
    fetch('/api/skill/raw').then(function (r) { return r.json(); }).then(function (data) {
      cache.md = data;
      var el = document.getElementById('skill-md-content');
      if (el) el.innerHTML = renderMarkdown(data.content);
    }).catch(function (e) {
      var el = document.getElementById('skill-md-content');
      if (el) el.innerHTML = '<div style="color:#EF4444;">❌ 加载失败: ' + e + '</div>';
    });
  }

  function loadSkillCommands() {
    fetch('/api/skill/commands').then(function (r) { return r.json(); }).then(function (data) {
      cache.commands = data;
      var el = document.getElementById('skill-commands-content');
      if (el) renderCommandsTable(el, data.commands || []);
    }).catch(function (e) {
      var el = document.getElementById('skill-commands-content');
      if (el) el.innerHTML = '<div style="color:#EF4444;">❌ 加载失败: ' + e + '</div>';
    });
  }

  function loadSkillInfo() {
    fetch('/api/skill/info').then(function (r) { return r.json(); }).then(function (data) {
      cache.info = data;
      var el = document.getElementById('skill-info-content');
      if (el) renderSkillInfo(el, data);
    }).catch(function (e) {
      var el = document.getElementById('skill-info-content');
      if (el) el.innerHTML = '<div style="color:#EF4444;">❌ 加载失败: ' + e + '</div>';
    });
  }

  function renderSkillInfo(el, data) {
    var filesHtml = (data.files || []).map(function (f) {
      return '<li><code>' + f.name + '</code> <span style="color:var(--color-muted);">(' + formatSize(f.size) + ')</span></li>';
    }).join('');
    el.innerHTML =
      '<div class="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">' +
        '<div class="rounded p-3" style="background:var(--color-surface);"><div class="text-xs" style="color:var(--color-muted);">文件数</div><div class="text-lg font-semibold">' + data.file_count + '</div></div>' +
        '<div class="rounded p-3" style="background:var(--color-surface);"><div class="text-xs" style="color:var(--color-muted);">总大小</div><div class="text-lg font-semibold">' + formatSize(data.total_size) + '</div></div>' +
        '<div class="rounded p-3" style="background:var(--color-surface);"><div class="text-xs" style="color:var(--color-muted);">根目录</div><div class="text-lg font-semibold font-mono">code-search/</div></div>' +
      '</div>' +
      '<div class="rounded p-3 mb-4" style="background:var(--color-surface);"><div class="text-xs mb-2" style="color:var(--color-muted);">文件清单</div><ul class="text-sm space-y-1">' + filesHtml + '</ul></div>' +
      '<a href="/api/skill/download" download="code-search.zip" ' +
         'class="inline-block px-5 py-2.5 rounded text-sm font-medium transition-colors" ' +
         'style="background:var(--color-accent); color:var(--color-on-primary);" ' +
         'onmouseover="this.style.opacity=0.85" onmouseout="this.style.opacity=1">⬇️ 下载 code-search.zip</a>';
  }

  function renderCommandsTable(el, commands) {
    if (commands.length === 0) {
      el.innerHTML = '<div style="color:var(--color-muted);">⚠️ 暂未解析到子命令</div>';
      return;
    }
    var rows = commands.map(function (c) {
      return '<tr><td class="px-3 py-2 font-mono">' + c.name + '</td><td class="px-3 py-2 text-sm" style="color:var(--color-muted);">' + (c.help || '—') + '</td></tr>';
    }).join('');
    el.innerHTML =
      '<table class="w-full text-sm" style="border-collapse:collapse;">' +
        '<thead><tr style="background:var(--color-surface);">' +
          '<th class="px-3 py-2 text-left">子命令</th><th class="px-3 py-2 text-left">说明</th>' +
        '</tr></thead>' +
        '<tbody>' + rows + '</tbody>' +
      '</table>';
  }

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1024 / 1024).toFixed(2) + ' MB';
  }

  // 极简 markdown 渲染（~30 行，仅支持本 SKILL.md 用到的语法）
  function renderMarkdown(text) {
    var html = text
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/```(\w*)\n([\s\S]*?)```/g, function (_, lang, code) {
        return '<pre style="background:var(--color-background); padding:8px; border-radius:4px; overflow:auto;"><code>' + code.trim() + '</code></pre>';
      })
      .replace(/^### (.+)$/gm, '<h3 style="color:var(--color-accent); margin:12px 0 6px;">$1</h3>')
      .replace(/^## (.+)$/gm, '<h2 style="color:white; margin:16px 0 8px;">$1</h2>')
      .replace(/^# (.+)$/gm, '<h1 style="color:white; margin:20px 0 10px;">$1</h1>')
      .replace(/`([^`]+)`/g, '<code style="background:var(--color-background); padding:1px 4px; border-radius:2px;">$1</code>')
      .replace(/^\- (.+)$/gm, '<li>$1</li>')
      .replace(/(<li>.*<\/li>\n?)+/g, function (block) { return '<ul style="margin:6px 0 6px 20px;">' + block + '</ul>'; })
      .replace(/\n\n/g, '</p><p style="margin:8px 0;">')
      .replace(/^/, '<p style="margin:8px 0;">')
      .replace(/$/, '</p>');
    return html;
  }
})();
```

- [ ] **Step 2：登记到 index.html**

修改 `frontend/index.html`：
- `__TAB_VERSION` 从 `24` → `25`
- 在 `<script src="js/code-mcp.js?v=1"></script>` 之后加：`<script src="js/code-skill.js?v=1"></script>`

- [ ] **Step 3：在 code-mcp.html 末尾填 skill 侧 4 子 tab 内容**

在 `code-mcp.html` 末尾 `<div id="agent-skill-side" class="hidden">` 里替换为：

```html
<div id="agent-skill-side" class="hidden space-y-4">
  <h2 class="text-lg font-semibold text-white pt-3">📦 Skill 接入</h2>
  <p class="text-sm" style="color:var(--color-muted);">
    code-search skill 是 email-wiki-demo 给 AI Agent 用的使用说明书。装上后 AI 知道怎么调 MCP 的 5 个 tools（code_search / code_chat / code_trace / code_file_context / code_list_repos）。
  </p>

  <!-- 子 tab 切换 -->
  <div class="flex flex-wrap gap-2 border-b pb-3" style="border-color:var(--color-border);">
    <button class="skill-tab-btn active px-3 py-1.5 rounded text-sm font-medium transition-colors whitespace-nowrap"
      data-skill-tab="install" style="background:var(--color-accent); color:var(--color-on-primary);" onclick="switchSkillTab('install')">📦 安装指南</button>
    <button class="skill-tab-btn px-3 py-1.5 rounded text-sm font-medium transition-colors whitespace-nowrap"
      data-skill-tab="md" style="color:var(--color-muted);" onclick="switchSkillTab('md')">📄 SKILL.md 预览</button>
    <button class="skill-tab-btn px-3 py-1.5 rounded text-sm font-medium transition-colors whitespace-nowrap"
      data-skill-tab="commands" style="color:var(--color-muted);" onclick="switchSkillTab('commands')">🛠 脚本能力清单</button>
    <button class="skill-tab-btn px-3 py-1.5 rounded text-sm font-medium transition-colors whitespace-nowrap"
      data-skill-tab="download" style="color:var(--color-muted);" onclick="switchSkillTab('download')">⬇️ 下载</button>
  </div>

  <!-- 子 tab 1: 安装指南 -->
  <div id="skill-tab-install" class="skill-tab-content space-y-3">
    <div class="rounded-lg p-4" style="background:var(--color-surface);">
      <div class="text-sm font-semibold mb-2" style="color:#22C55E;">🤖 Claude Code</div>
      <div class="rounded p-2 font-mono text-xs" style="background:var(--color-background);">
        mkdir -p ~/.agents/skills/code-search &amp;&amp; unzip ~/Downloads/code-search.zip -d ~/.agents/skills/
      </div>
    </div>
    <div class="rounded-lg p-4" style="background:var(--color-surface);">
      <div class="text-sm font-semibold mb-2" style="color:#3B82F6;">✏️ Cursor</div>
      <div class="rounded p-2 font-mono text-xs" style="background:var(--color-background);">
        mkdir -p ~/.cursor/skills/code-search &amp;&amp; unzip ~/Downloads/code-search.zip -d ~/.cursor/skills/
      </div>
    </div>
    <div class="rounded-lg p-4" style="background:var(--color-surface);">
      <div class="text-sm font-semibold mb-2" style="color:#F59E0B;">🔧 CodeMaker / OpenCode</div>
      <div class="rounded p-2 font-mono text-xs" style="background:var(--color-background);">
        # CodeMaker<br>
        mkdir -p ~/.codemaker/skills/code-search &amp;&amp; unzip ~/Downloads/code-search.zip -d ~/.codemaker/skills/<br>
        # OpenCode<br>
        mkdir -p ~/.config/opencode/skill/code-search &amp;&amp; unzip ~/Downloads/code-search.zip -d ~/.config/opencode/skill/
      </div>
    </div>
  </div>

  <!-- 子 tab 2: SKILL.md 预览 -->
  <div id="skill-tab-md" class="skill-tab-content hidden">
    <div id="skill-md-content" class="rounded-lg p-4 text-sm" style="background:var(--color-surface);">
      <div style="color:var(--color-muted);">⏳ 加载中…</div>
    </div>
  </div>

  <!-- 子 tab 3: 脚本能力清单 -->
  <div id="skill-tab-commands" class="skill-tab-content hidden">
    <div id="skill-commands-content" class="rounded-lg p-4" style="background:var(--color-surface);">
      <div style="color:var(--color-muted);">⏳ 加载中…</div>
    </div>
  </div>

  <!-- 子 tab 4: 下载 zip -->
  <div id="skill-tab-download" class="skill-tab-content hidden">
    <div id="skill-info-content">
      <div style="color:var(--color-muted);">⏳ 加载中…</div>
    </div>
  </div>
</div>
```

- [ ] **Step 4：浏览器手测 4 个子 tab**

硬刷 `localhost:8000/#code-mcp`：
- 顶层点「Skill 接入」→ 默认进子 tab 1（安装指南）→ 看到 3 个工具的安装命令卡片
- 点「📄 SKILL.md 预览」→ 看到渲染后的 markdown（前 5 个 H2 标题、`code_search` 等 inline code）
- 点「🛠 脚本能力清单」→ 看到子命令表格（search/chat/trace/file/repos）
- 点「⬇️ 下载」→ 看到 3 个统计卡片 + 文件清单 + 下载按钮
- 点下载按钮 → 浏览器下载 `code-search.zip` → 双击解压验证含 `code-search/SKILL.md`

- [ ] **Step 5：commit**

```bash
git -C .claude/worktrees/feat+skill-integration-tab add frontend/tabs/code-mcp.html frontend/js/code-skill.js frontend/index.html
git -C .claude/worktrees/feat+skill-integration-tab commit -m "feat(agent-tab): Skill 侧 4 子 tab (安装/SKILL预览/脚本/下载) 完整内容"
```

---

## Task 5：回归测试 + 完整链路验证

**Files:**
- 不改代码，只验证

- [ ] **Step 1：后端单测全跑**

```bash
cd backend && source venv/bin/activate
python -m pytest tests/test_skill_routes.py -v
# 期望：4 passed
```

- [ ] **Step 2：MCP 端点不破**

```bash
curl -fsS http://localhost:8000/api/code/stats | head -1
# 期望：返回 JSON（不破）
curl -fsS http://localhost:8000/api/code/repos | head -1
# 期望：返回 JSON
```

- [ ] **Step 3：端到端 4 个 skill API 全跑**

```bash
# 启动
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 &
sleep 3

# 4 个端点
for ep in raw info commands download; do
  echo "=== /api/skill/$ep ==="
  case $ep in
    download) curl -fsS -o /tmp/cs.zip http://localhost:8000/api/skill/$ep && unzip -l /tmp/cs.zip | head -10 ;;
    *) curl -fsS http://localhost:8000/api/skill/$ep | python3 -c "import json,sys; d=json.load(sys.stdin); print('keys:', list(d.keys()))" ;;
  esac
done

kill %1
```

- [ ] **Step 4：浏览器最终手测（5 项）**

1. `localhost:8000/#code-mcp` → 硬刷 → 侧栏显示「🤖 Agent 接入」
2. 顶部大标题「🤖 Agent 接入」+ 2 个大 tab 按钮
3. 点「MCP 接入」→ 5 个子 tab 全部正常（0 业务回归）
4. 点「Skill 接入」→ 4 个子 tab 全部正常
5. 切到子 tab 4 → 点下载 → 下载文件可双击解压 → `code-search/SKILL.md` 可打开

- [ ] **Step 5：commit（如有 changelog 文档更新）**

```bash
# 仅在 CHANGELOG.md 或 README.md 写 changelog 时需要
git -C .claude/worktrees/feat+skill-integration-tab add CHANGELOG.md  # 或相关
git -C .claude/worktrees/feat+skill-integration-tab commit -m "docs: Agent 接入页 Skill 集成 changelog"
```

---

## 总结

| # | 任务 | 改动文件 | 净增行 |
|---|------|---------|--------|
| 1 | 后端 raw/info/download | `code_skill_routes.py` (新) + `test_skill_routes.py` (新) + `main.py` (1 行) | ~140 |
| 2 | 后端 commands (ast) | `code_skill_routes.py` (改) + `test_skill_routes.py` (改) | ~40 |
| 3 | 顶层 2-tab 切换 | `code-mcp.html` (改) + `index.html` (改) | ~30 |
| 4 | Skill 侧 4 子 tab | `code-skill.js` (新) + `code-mcp.html` (改) + `index.html` (改) | ~250 |
| 5 | 回归 + 验证 | — | 0 |
| **合计** | | **6 个文件** | **~460 行** |

**完成标准**：
- [ ] 4 个后端 API 单测全过
- [ ] 端到端 curl 4 端点全过
- [ ] 浏览器 5 项手测全过
- [ ] MCP 侧 0 业务回归
- [ ] 0 个**已知**死代码 / 0 个 TODO 残留
