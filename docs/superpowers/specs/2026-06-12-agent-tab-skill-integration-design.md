# Agent 接入页 — Skill 集成子页设计

> 2026-06-12 柳哥提需求：在 `code-mcp.html`（侧栏原名「🔌 MCP 接入」）的同一 tab 内，新增「Skill 接入」板块。本 spec 描述如何**最小改动**地实现。
>
> 主题：把 `export/skill/` 现有产物暴露到前端，让用户能浏览 SKILL.md / 脚本能力 / 一键下载 zip 装到 `~/.agents/skills/code-search/`。

## 背景与目标

- **现状**：`export/skill/` 已有完整 skill 资产（`SKILL.md` 28KB + `scripts/kb_api.py` 9KB），但**前端没有展示入口**——只在 `code-mcp.html` 的 AI 视角子 tab 里随手提了一句
- **目标**：在 Agent 接入 tab（侧栏原「🔌 MCP 接入」改名）内加 1 个**顶层互斥大 tab**——「MCP 接入 / Skill 接入」——Skill 侧给 4 个子 tab：安装指南 / SKILL.md 预览 / 脚本能力清单 / 下载 zip
- **不做**：不动 MCP 侧、不动 `kb_api.py` 实现、不改 SKILL.md frontmatter、不动后端现有 MCP server

## 范围边界

| 在范围 | 不在范围 |
|--------|---------|
| 侧栏 tab 标题 `🔌 MCP 接入` → `🤖 Agent 接入` | `code-mcp.html` MCP 侧 5 个子 tab 内容 |
| 顶层 2-tab 切换 JS | `kb_api.py` 实现 |
| 新建 `code-skill.html` + `code-skill.js` | SKILL.md 任何内容 |
| 后端 1 个新文件 + 1 个新 router | 任何后端 MCP 改造 |
| zip 打包（内存流，根目录 `code-search/`）| 写文件系统到 `~/.agents/skills/` |

## 减法笔记

按 `rules/development/coding-design-principles.md` 的 Q1/Q2/Q3 三问审视：

- **Q1（合并路径）**：用户最初问"skill 接入板块要包括什么"，答"只装本项目 Skill（单向）"——这就**否定了**做"Skill 浏览/管理/启停"的全量插件中心方案，**消除一个并发路径**（不只是给用户少选项，是根本不实现）
- **Q2（找权威入口）**：`export/skill/` 已经是 SSOT。后端 zip 打包 + 前端展示都从这里读，**不复制、不缓存**（前端懒加载仅在浏览器内存里暂存）
- **Q3（质疑历史）**：
  - 一开始误以为 `code-kb`（frontmatter name）和 `code-search`（文件夹名）是双命名要统一——经柳哥澄清，**用户视角下这个 skill 就叫 `code-search`**，但 SKILL.md 里的 `name: code-kb` **不归我管**——不动它
  - 一开始想提"改 `name: code-kb` → `name: code-search`"被柳哥打回——**不擅自改**现状
  - 整个 brainstorm 过程中**两次**被柳哥纠正"不对"——`mcp-skill` 这个名字根本不存在，是 AI 自作主张的延伸

## 架构

```
🤖 Agent 接入 (侧栏 tab 改名)
│
├── 顶层互斥大 tab (新 JS 函数 switchAgentTab)
│   ├── [MCP 接入]  ← 原 5 个子 tab 收纳到 #agent-mcp-side，0 改动
│   └── [Skill 接入] ← 新建 #agent-skill-side，含 4 个子 tab
│       ├── 📦 安装指南 (fetch /api/skill/raw，读 README.md 的"加载方式"段)
│       ├── 📄 SKILL.md 预览 (fetch /api/skill/raw，自实现 ~30 行 markdown 渲染)
│       ├── 🛠 脚本能力清单 (后端 ast 解析 kb_api.py 的 argparse subcommands)
│       └── ⬇️ 下载 zip (fetch /api/skill/download，浏览器下载 code-search.zip)
│
└── 后端新增 1 个文件 backend/code_skill_routes.py
    ├── GET /api/skill/raw      → SKILL.md 文本 + 元信息
    ├── GET /api/skill/info     → zip 元信息（大小/文件数/清单）
    └── GET /api/skill/download → application/zip 字节流
```

## 组件 / 接口

### 前端

**`frontend/tabs/code-mcp.html`**（改 1 个 h2 + 加 1 个大 tab 切换 + 包裹原内容）
- 顶部加 2 个按钮 `[MCP 接入] [Skill 接入]`，onclick 调 `switchAgentTab('mcp'|'skill')`
- 原 5 个子 tab 全部包进 `<div id="agent-mcp-side">`（**0 业务内容改动**）
- Skill 侧的 HTML 容器**不在这里**——`tabs/code-skill.html` 是独立 tab，由 router 懒加载，与现有 10 个 tab 模式一致

**`frontend/tabs/code-skill.html`**（新，4 子 tab 内容 + 容器）
- 4 个 `<div class="skill-tab-content">` 子 tab 容器
- 一段内联 `<script>` 调后端 /api/skill/raw 渲染 markdown
- 1 个 `switchSkillTab()` 函数

**`frontend/js/code-skill.js`**（新）
- `switchSkillTab(name)` — 子 tab 切换
- `loadSkillMd()` — 拉 /api/skill/raw 并 markdown 渲染
- `renderMarkdown(text)` — ~30 行自实现（标题/列表/代码块/段落/链接）
- `loadSkillInfo()` — 拉 /api/skill/info 展示 zip 元信息
- `downloadSkill()` — 触发浏览器下载 `/api/skill/download`

**`frontend/index.html`**（2 处改）
- `__TAB_VERSION` 从 `24` → `25`
- `<script src="js/code-skill.js?v=1">`（在 `code-mcp.js` 之后）

### 后端

**`backend/code_skill_routes.py`**（新，~80 行）
```python
"""Skill 接入子页 — 后端 API"""
import io
import os
import ast
import zipfile
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter()
EXPORT_DIR = "export/skill"


@router.get("/api/skill/raw")
def get_skill_raw():
    """返回 SKILL.md 文本 + 元信息"""
    path = os.path.join(EXPORT_DIR, "SKILL.md")
    if not os.path.exists(path):
        return {"error": "SKILL.md missing", "path": path}, 500
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
        return {"error": f"{EXPORT_DIR} not found"}, 500

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


@router.get("/api/skill/commands")
def get_skill_commands():
    """用 ast 解析 kb_api.py 的 argparse subcommands，列出 5 个子命令"""
    py_path = os.path.join(EXPORT_DIR, "scripts", "kb_api.py")
    if not os.path.exists(py_path):
        return {"commands": [], "error": "kb_api.py missing"}
    try:
        tree = ast.parse(open(py_path, encoding="utf-8").read())
        # ... 提取 argparse subparsers/add_parser 节点 ...
    except SyntaxError:
        return {"commands": [], "error": "kb_api.py 语法错误"}
```

**`backend/main.py`**（1 行改）
```python
from code_skill_routes import router as skill_router
app.include_router(skill_router)
```

## 数据流

### 子 tab 1（安装指南）— 静态卡片
- 启动时把硬编码的 4 个安装命令（Claude Code / Cursor / CodeMaker / OpenCode）渲染到 HTML
- **不调后端**，**不读 README.md**——避免循环依赖
- 命令内容**直接写死在** `code-skill.html` 里（与 README.md 同步靠人 review）

### 子 tab 2（SKILL.md 预览）— 懒加载
1. 用户首次切到子 tab 2 → `loadSkillMd()` 触发
2. `fetch GET /api/skill/raw` → 后端读 `export/skill/SKILL.md` → 返回 `{content, size, files}`
3. 前端调 `renderMarkdown(content)` → 注入 `#skill-md-preview` 容器
4. 缓存到 `window.__skillMdCache`，切走再切回不重拉

### 子 tab 3（脚本能力清单）— 懒加载
1. 首次切到子 tab 3 → `loadSkillCommands()` 触发
2. `fetch GET /api/skill/commands` → 后端 `ast.parse(kb_api.py)` → 提取 `parser.add_parser(...)` 节点 → 返回 `[{name, args, help}]`
3. 渲染成表格：子命令 / 参数 / 调用的后端端点 / 何时用

### 子 tab 4（下载 zip）— 懒加载
1. 首次切到子 tab 4 → `loadSkillInfo()` 触发
2. `fetch GET /api/skill/info` → 展示 zip 大小、文件数、清单
3. 用户点「⬇️ 下载」按钮 → `<a href="/api/skill/download" download>` 直接触发浏览器下载

## 错误处理

| 场景 | 后端响应 | 前端展示 |
|------|---------|---------|
| `EXPORT_DIR` 不存在 | 500 `{error: "export/skill not found"}` | "❌ skill 源目录不存在" |
| `SKILL.md` 缺失 | 500 `{error: "SKILL.md missing"}` | "❌ SKILL.md 缺失" |
| `kb_api.py` 缺失 | 200 + `commands: []` | "⚠️ kb_api.py 缺失" |
| `kb_api.py` 语法错误 | 200 + `commands: []`, `error` | "⚠️ 解析失败，显示源码" + 折叠 raw |
| zip 打包失败 | 500 | 通用错误 toast |
| 浏览器 fetch 失败 | — | "❌ 网络异常" + 重试按钮 |
| zip 0 文件 | 200 | "⚠️ zip 内 0 个文件" |

## 测试 / 验证

按 `rules/development/coding-design-principles.md` 反例存档 4 的教训——"改完跑通完整链路再 push"：

### 后端单测（`backend/tests/test_skill_routes.py`，3 个 case）
1. `test_skill_raw_returns_content` — mock `export/skill/SKILL.md`，断言 content/size 正确
2. `test_skill_info_files_listed` — 断言 files 数组非空、含 SKILL.md 和 scripts/kb_api.py
3. `test_skill_download_zip_structure` — 下载 zip → `zipfile.ZipFile` 打开 → 断言 entry 含 `code-search/SKILL.md`

### 端到端 curl 验证（不走浏览器）
```bash
curl -fsS http://localhost:8000/api/skill/raw | jq '.content | length'
# 断言 > 10000（SKILL.md 实际 28KB）

curl -fsS http://localhost:8000/api/skill/info | jq '.file_count'
# 断言 >= 3（README + SKILL + scripts/kb_api.py）

curl -fsS -o /tmp/cs.zip http://localhost:8000/api/skill/download
unzip -l /tmp/cs.zip
# 断言第一个 entry 是 code-search/SKILL.md
```

### 前端浏览器手测
1. 打开 `localhost:8000/#code-mcp` → 顶部应看到「🤖 Agent 接入」+ 2 个大 tab
2. 默认显示 MCP 侧（5 子 tab 都不破）→ 切到 Skill 侧 → 4 子 tab 都正常
3. 切到子 tab 4 → 点下载 → 浏览器下载 `code-search.zip`
4. 双击解压到 `~/.agents/skills/code-search/` → 重启 Claude Code → 输入"搜一下邮件发送" → AI 提示用 `code_search`
5. **硬刷一次**（Cmd+Shift+R）确认 `__TAB_VERSION=25` 生效

### 回归检查
```bash
cd backend && source venv/bin/activate
python -m pytest tests/test_skill_routes.py -v   # 3 passed
python -c "import ast; ast.parse(open('scripts/kb_api.py').read())"  # 不破现有
curl -fsS http://localhost:8000/api/code/stats | head -1   # MCP 端点不破
```

## 文件改动清单

| # | 文件 | 改动类型 | 预计行数 |
|---|------|---------|---------|
| 1 | `frontend/tabs/code-mcp.html` | 改 | +20 / -0 |
| 2 | `frontend/tabs/code-skill.html` | 新 | +150 |
| 3 | `frontend/js/code-skill.js` | 新 | +200 |
| 4 | `frontend/js/code-mcp.js` | 改 | +10（switchAgentTab） |
| 5 | `frontend/index.html` | 改 | +2（版本号 + 1 行 script） |
| 6 | `backend/code_skill_routes.py` | 新 | +80 |
| 7 | `backend/main.py` | 改 | +2（import + include_router） |
| 8 | `backend/tests/test_skill_routes.py` | 新 | +60 |
| **合计** | | | **+524 行** |

## 来源

> 来源：2026-06-12 柳哥在 `feat+skill-integration-tab` worktree 提需求"在 mcp 接入 tab 里面再加一个 skill 接入，该页面分为 mcp 接入与 skill 接入两种方式"
