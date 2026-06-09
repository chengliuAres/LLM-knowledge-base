# 两级 Tab 重构实现计划

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 将 6 个平级 tab 的单文件前端重构为左侧 Sidebar 导航的两级 tab SPA，分为「文档知识管理」和「代码知识库」两大模块，同步升级深色主题。

**Architecture:** 自顶向下脚手架 — 先搭导航壳 + 路由 + 深色主题基础设施，再逐个迁移现有 tab 内容到独立 HTML 文件，最后改造后端支持代码 LanceDB inspect。

**Tech Stack:** FastAPI + Tailwind CDN + Vanilla JS（无框架）+ Fira Code/Sans 字体

**设计文档:** `docs/superpowers/specs/2026-06-09-two-level-tabs-redesign.md`

---

## Phase 1: 导航壳 + 路由 + 深色主题基础设施

### Task 1.1: 创建深色主题 CSS 设计令牌

**Objective:** 建立全局深色主题样式，所有 tab 共享。

**Files:**
- Create: `frontend/css/theme.css`

**Step 1: 创建 theme.css**

```css
/* frontend/css/theme.css — 深色 Slate 主题设计令牌 */
:root {
  --color-primary: #1E293B;
  --color-background: #0F172A;
  --color-foreground: #F8FAFC;
  --color-accent: #22C55E;
  --color-muted: #64748B;
  --color-border: #334155;
  --color-destructive: #EF4444;
  --color-ring: #1E293B;
  --font-sans: 'Fira Sans', system-ui, sans-serif;
  --font-mono: 'Fira Code', ui-monospace, monospace;
}

body {
  font-family: var(--font-sans);
  background: var(--color-background);
  color: var(--color-foreground);
}

code, .mono { font-family: var(--font-mono); }

/* Sidebar */
.sidebar { ... }
.sidebar-item { ... }
.sidebar-item.active { ... }
.sidebar-group-label { ... }

/* 卡片/面板 */
.panel { background: var(--color-primary); border: 1px solid var(--color-border); border-radius: 0.75rem; }
.panel-header { ... }

/* Tab 子导航 */
.subtab-btn { ... }
.subtab-btn.active { ... }

/* 按钮 */
.btn-accent { background: var(--color-accent); color: #0F172A; }
.btn-secondary { background: var(--color-border); color: var(--color-foreground); }
.btn-danger { background: var(--color-destructive); color: white; }

/* 输入框 */
.input { background: var(--color-background); border: 1px solid var(--color-border); color: var(--color-foreground); }

/* 表格 */
.table-row:hover { background: var(--color-primary); }

/* 滚动条 */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-thumb { background: var(--color-border); border-radius: 3px; }

/* 动效 */
.transition-smooth { transition: all 150ms ease-out; }
```

**Step 2: 验证**
- 文件存在且无语法错误

**Step 3: Commit**
```bash
git add frontend/css/theme.css
git commit -m "feat: 深色主题 CSS 设计令牌"
```

---

### Task 1.2: 创建路由模块

**Objective:** 实现 hash 路由 + 页面 fetch 加载。

**Files:**
- Create: `frontend/js/router.js`

**Step 1: 创建 router.js**

核心逻辑：
- 监听 `hashchange` 事件
- 解析 hash（`#doc/upload` → `{section: 'doc', tab: 'upload'}`）
- fetch 对应的 `tabs/doc-upload.html` 文件
- 注入到 `#content-area` 容器
- 更新 Sidebar 高亮状态
- 加载完成后执行 tab 特有的初始化函数（如果存在）
- **Tailwind CDN 兼容**：Tailwind CDN v3.4+ 使用 MutationObserver 自动检测动态注入的 DOM 节点，
  但为确保可靠性，`navigate()` 注入 innerHTML 后应调用 `window.tailwind?.refresh()` 强制重新扫描。
  若 `window.tailwind` 不存在（CDN 未暴露），回退到在 `index.html` 的 `<head>` 中添加
  `<script src="https://cdn.tailwindcss.com"></script>` 的 `data-classes` safelist。
```javascript
// frontend/js/router.js
const Router = {
  routes: {
    'doc/upload':    { file: 'tabs/doc-upload.html',    title: '文档管理', init: 'initDocUpload' },
    'doc/email':     { file: 'tabs/doc-email.html',     title: '邮件导入', init: 'initDocEmail' },
    'doc/chat':      { file: 'tabs/doc-chat.html',      title: '智能问答', init: 'initDocChat' },
    'doc/dashboard': { file: 'tabs/doc-dashboard.html', title: '看板',     init: 'initDocDashboard' },
    'doc/lancedb':   { file: 'tabs/doc-lancedb.html',   title: 'LanceDB 内部', init: 'initDocLancedb' },
    'code/repos':    { file: 'tabs/code-repos.html',    title: '仓库扫描', init: 'initCodeRepos' },
    'code/search':   { file: 'tabs/code-search.html',   title: '代码搜索', init: 'initCodeSearch' },
    'code/chat':     { file: 'tabs/code-chat.html',     title: '代码问答', init: 'initCodeChat' },
    'code/dashboard':{ file: 'tabs/code-dashboard.html',title: '看板',     init: 'initCodeDashboard' },
    'code/lancedb':  { file: 'tabs/code-lancedb.html',  title: 'LanceDB 内部', init: 'initCodeLancedb' },
  },

  defaultRoute: 'doc/upload',

  async navigate(hash) {
    const route = this.routes[hash];
    if (!route) { location.hash = this.defaultRoute; return; }

    // 更新 Sidebar 高亮
    document.querySelectorAll('.sidebar-item').forEach(el => {
      el.classList.toggle('active', el.dataset.route === hash);
    });

    // fetch 并注入
    const contentArea = document.getElementById('content-area');
    try {
      const resp = await fetch(route.file);
      if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
      contentArea.innerHTML = await resp.text();

      // Tailwind CDN: 强制重新扫描动态注入的类名
      if (window.tailwind && window.tailwind.refresh) {
        window.tailwind.refresh();
      }

      // 执行初始化函数
      if (typeof window[route.init] === 'function') {
        window[route.init]();
      }
    } catch (err) {
      contentArea.innerHTML = `<div class="p-6 text-red-400">加载失败: ${err.message}</div>`;
    }
  },

  init() {
    window.addEventListener('hashchange', () => this.navigate(location.hash.slice(1)));
    const hash = location.hash.slice(1) || this.defaultRoute;
    if (!location.hash) location.hash = hash;
    this.navigate(hash);
  }
};
```

**Step 3: 验证**
- 文件存在且 JS 无语法错误

**Step 4: Commit**
```bash
git add frontend/js/router.js
git commit -m "feat: hash 路由模块 — Sidebar 切换 + 页面 fetch 加载"
```

---

### Task 1.3: 创建公共工具模块

**Objective:** 提取公共工具函数，所有 tab 共享。

**Files:**
- Create: `frontend/js/shared.js`

**Step 1: 从现有 index.html 提取公共函数**

从当前 index.html 中提取：
- `escapeHtml()` — HTML 转义
- `formatBytes()` — 字节格式化
- `formatDuration()` — 时长格式化
- `renderStepTracker()` — StepTracker 渲染
- `renderMatchReasons()` — 匹配原因渲染
- `renderVectorHeatmap16()` — 向量热力图
- `toggleStepCard()` — 步骤卡片折叠/展开
- API 调用封装（fetch wrapper with error handling）

**具体提取清单（从 index.html `<script>` 部分）：**

```javascript
// frontend/js/shared.js

// ── HTML 工具 ──
function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

// ── 格式化 ──
function formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024, sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function formatDuration(ms) {
  if (ms < 1000) return ms.toFixed(0) + 'ms';
  return (ms / 1000).toFixed(2) + 's';
}

// ── API 封装 ──
async function apiFetch(url, options = {}) {
  const resp = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || `HTTP ${resp.status}`);
  }
  return resp.json();
}

// ── StepTracker 渲染 ──
function renderStepTracker(steps, containerId) { /* 从现有代码提取 */ }
function toggleStepCard(stepId) { /* 从现有代码提取 */ }
function renderMatchReasons(reasons) { /* 从现有代码提取 */ }
function renderVectorHeatmap16(vec) { /* 从现有代码提取 */ }

// ── 通知 ──
function showToast(msg, type = 'info') { /* 轻量 toast 实现 */ }
```

**Step 2: 从 index.html 中删除已提取的函数**

**Step 3: 验证**
- 文件存在且 JS 无语法错误

**Step 4: Commit**
```bash
git add frontend/js/shared.js
git commit -m "feat: 公共工具模块 — escapeHtml, API 封装, StepTracker 渲染"
```

---

### Task 1.4: 创建 Sidebar 导航壳

**Objective:** 创建新的 index.html，包含 Sidebar 导航 + 内容区占位。

**Files:**
- Modify: `frontend/index.html`（重写为导航壳）

**Step 1: 重写 index.html**

结构：
```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>Email Wiki — 知识库管理</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600&family=Fira+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="css/theme.css">
</head>
<body class="flex h-screen overflow-hidden">
  <!-- Sidebar -->
  <aside class="sidebar w-56 flex-shrink-0 flex flex-col border-r border-[var(--color-border)]">
    <div class="p-4 border-b border-[var(--color-border)]">
      <h1 class="text-sm font-semibold">📚 Email Wiki</h1>
      <span class="text-[10px] text-[var(--color-muted)] mono">v2.0</span>
    </div>
    <nav class="flex-1 py-2 overflow-y-auto">
      <!-- 文档知识管理 -->
      <div class="sidebar-group-label px-4 py-1 text-[10px] uppercase tracking-wider text-[var(--color-muted)]">文档知识管理</div>
      <a href="#doc/upload"    class="sidebar-item" data-route="doc/upload">📄 文档管理</a>
      <a href="#doc/email"     class="sidebar-item" data-route="doc/email">📧 邮件导入</a>
      <a href="#doc/chat"      class="sidebar-item" data-route="doc/chat">💬 智能问答</a>
      <a href="#doc/dashboard" class="sidebar-item" data-route="doc/dashboard">📊 看板</a>
      <a href="#doc/lancedb"   class="sidebar-item" data-route="doc/lancedb">🗄️ LanceDB 内部</a>
      <!-- 分隔线 -->
      <div class="h-px bg-[var(--color-border)] mx-4 my-2"></div>
      <!-- 代码知识库 -->
      <div class="sidebar-group-label px-4 py-1 text-[10px] uppercase tracking-wider text-[var(--color-muted)]">代码知识库</div>
      <a href="#code/repos"     class="sidebar-item" data-route="code/repos">📂 仓库扫描</a>
      <a href="#code/search"    class="sidebar-item" data-route="code/search">🔍 代码搜索</a>
      <a href="#code/chat"      class="sidebar-item" data-route="code/chat">💬 代码问答</a>
      <a href="#code/dashboard" class="sidebar-item" data-route="code/dashboard">📊 看板</a>
      <a href="#code/lancedb"   class="sidebar-item" data-route="code/lancedb">🗄️ LanceDB 内部</a>
    </nav>
  </aside>

  <!-- 内容区 -->
  <main id="content-area" class="flex-1 overflow-y-auto">
    <!-- 由 router.js 动态加载 -->
  </main>

  <script src="js/shared.js"></script>
  <script src="js/router.js"></script>
  <script>Router.init();</script>
</body>
</html>
```

**Step 2: 验证**
- 浏览器打开 `http://localhost:8000` 能看到 Sidebar
- 点击 Sidebar 项能切换（内容区暂时空白）

**Step 3: Commit**
```bash
git add frontend/index.html
git commit -m "feat: Sidebar 导航壳 — 两级 tab 结构 + 深色主题"
```

---

## Phase 2: 迁移文档知识管理的 5 个 tab

每个 Task 将现有 tab 面板的 HTML+JS 提取到独立文件，适配深色主题。

**Init 函数合约：** 每个 tab 文件必须在全局 `window` 上导出初始化函数，函数名与 router.js 路由表严格一致：
- `doc-upload.html` → `window.initDocUpload`
- `doc-email.html` → `window.initDocEmail`
- `doc-chat.html` → `window.initDocChat`
- `doc-dashboard.html` → `window.initDocDashboard`
- `doc-lancedb.html` → `window.initDocLancedb`

**向后兼容策略：** Phase 2 期间，保留旧的 `index.html` 作为 `index-old.html` 备份。
每迁移一个 tab，验证该 tab 通过新路由可访问后再继续下一个。
Phase 2 全部完成后，删除 `index-old.html`。

### Task 2.1: 迁移文档管理 tab

**Objective:** 提取 `panel-upload` 到 `tabs/doc-upload.html`。

**Files:**
- Create: `frontend/tabs/doc-upload.html`
- 从 `frontend/index.html` 提取：`panel-upload` 的 HTML + 相关 JS（loadDocuments, handleSearch, setupDragDrop 等）

**Step 1: 提取**
- 从 index.html 第 41-152 行提取 HTML 面板
- 从 `<script>` 部分提取相关 JS 函数
- 适配深色主题 class（bg-white → panel，text-gray-xxx → 对应深色变量）
- 定义 `initDocUpload()` 初始化函数

**Step 2: 验证**
- 浏览器 `#doc/upload` 能正确显示文档管理界面
- 上传、搜索、删除功能正常

**Step 3: Commit**
```bash
git add frontend/tabs/doc-upload.html
git commit -m "feat: 迁移文档管理 tab 到独立文件"
```

---

### Task 2.2: 迁移邮件导入 tab

**Objective:** 提取 `panel-email` 到 `tabs/doc-email.html`。

**Files:**
- Create: `frontend/tabs/doc-email.html`
- 从 `frontend/index.html` 第 153-199 行提取

**Step 1: 提取 + 适配深色主题**

**Step 2: 验证**
- `#doc/email` 能正确显示邮件列表和导入功能

**Step 3: Commit**
```bash
git add frontend/tabs/doc-email.html
git commit -m "feat: 迁移邮件导入 tab 到独立文件"
```

---

### Task 2.3: 迁移智能问答 tab

**Objective:** 提取 `panel-chat` 到 `tabs/doc-chat.html`。

**Files:**
- Create: `frontend/tabs/doc-chat.html`
- 从 `frontend/index.html` 第 200-225 行提取

**Step 1: 提取 + 适配深色主题**

**Step 2: 验证**
- `#doc/chat` 能正确显示问答界面，流式回答正常

**Step 3: Commit**
```bash
git add frontend/tabs/doc-chat.html
git commit -m "feat: 迁移智能问答 tab 到独立文件"
```

---

### Task 2.4: 迁移文档看板 tab

**Objective:** 提取 `panel-dashboard` 到 `tabs/doc-dashboard.html`。

**Files:**
- Create: `frontend/tabs/doc-dashboard.html`
- 从 `frontend/index.html` 第 226-349 行提取

**Step 1: 提取 + 适配深色主题 + 图表颜色适配**

**Step 2: 验证**
- `#doc/dashboard` 能正确显示统计数据和图表

**Step 3: Commit**
```bash
git add frontend/tabs/doc-dashboard.html
git commit -m "feat: 迁移文档看板 tab 到独立文件"
```

---

### Task 2.5: 迁移文档 LanceDB 内部 tab

**Objective:** 提取 `panel-lancedb` 到 `tabs/doc-lancedb.html`。

**Files:**
- Create: `frontend/tabs/doc-lancedb.html`
- 从 `frontend/index.html` 第 352-556 行提取

**Step 1: 提取 + 适配深色主题 + 原理演示部分**

**Step 2: 验证**
- `#doc/lancedb` 能正确显示表概览、数据浏览、原理演示

**Step 3: Commit**
```bash
git add frontend/tabs/doc-lancedb.html
git commit -m "feat: 迁移文档 LanceDB 内部 tab 到独立文件"
```

---

### Task 2.6: 清理 index.html 中已迁移的代码

**Objective:** 从 index.html 中删除已迁移到独立文件的 HTML 和 JS 代码。

**Files:**
- Modify: `frontend/index.html`

**注意：日志面板保留。** 当前 index.html 包含日志抽屉（log-panel），支持 `/api/logs/tail` 轮询。
迁移时需将日志面板整合到新的 index.html 导航壳中（作为全局浮层，不受 tab 切换影响）。
如果日志面板代码与 tab 面板耦合，需先解耦再迁移。

**Step 1: 删除**
- 删除所有 `panel-*` 的 HTML
- 删除已提取到 shared.js 的 JS 函数
- 删除已提取到各 tab 文件的 JS 函数

**Step 2: 验证**
- 所有 5 个文档 tab 通过路由加载正常工作

**Step 3: Commit**
```bash
git add frontend/index.html
git commit -m "refactor: 清理 index.html 中已迁移的文档 tab 代码"
```

---

## Phase 3: 迁移代码知识库的 5 个 tab
**Init 函数合约：**
- `code-repos.html` → `window.initCodeRepos`
- `code-search.html` → `window.initCodeSearch`
- `code-chat.html` → `window.initCodeChat`
- `code-dashboard.html` → `window.initCodeDashboard`
- `code-lancedb.html` → `window.initCodeLancedb`


### Task 3.1: 迁移仓库扫描 tab

**Objective:** 提取代码知识库的仓库管理部分到 `tabs/code-repos.html`。

**Files:**
- Create: `frontend/tabs/code-repos.html`
- 从 `frontend/index.html` 第 1629-1695 行提取（仓库管理左侧栏）

**Step 1: 提取 + 适配深色主题**

**Step 2: 验证**
- `#code/repos` 能正确显示仓库扫描和列表

**Step 3: Commit**
```bash
git add frontend/tabs/code-repos.html
git commit -m "feat: 迁移仓库扫描 tab 到独立文件"
```

---

### Task 3.2: 创建代码搜索 tab

**Objective:** 从现有 codekb 面板提取搜索功能到 `tabs/code-search.html`。

**Files:**
- Create: `frontend/tabs/code-search.html`
- 从 `frontend/index.html` 第 1697-1715 行提取（搜索区 + 结果区）

**Step 1: 提取 + 适配深色主题**

**Step 2: 验证**
- `#code/search` 混合搜索/语义搜索/关键词搜索正常

**Step 3: Commit**
```bash
git add frontend/tabs/code-search.html
git commit -m "feat: 创建代码搜索 tab"
```

---

### Task 3.3: 创建代码问答 tab

**Objective:** 从现有 codekb 面板提取问答功能到 `tabs/code-chat.html`。

**Files:**
- Create: `frontend/tabs/code-chat.html`
- 从 `frontend/index.html` 第 1717-1725 行提取

**Step 1: 提取 + 适配深色主题**

**Step 2: 验证**
- `#code/chat` 代码问答正常

**Step 3: Commit**
```bash
git add frontend/tabs/code-chat.html
git commit -m "feat: 创建代码问答 tab"
```

---

### Task 3.4: 创建代码看板 tab

**Objective:** 新建代码知识库看板，包含语言分布、仓库明细等新增内容。

**Files:**
- Create: `frontend/tabs/code-dashboard.html`

**Step 1: 创建看板**

内容：
- 概览卡片：仓库数、代码块数、语言数、Chunk 类型数
- 语言分布标签云
- 仓库明细表
- Chunk 类型分布
- 性能指标：Code LanceDB 磁盘、代码搜索耗时、仓库扫描耗时、代码问答耗时
- 图表：耗时趋势 + Step 拆解
- 数据存储目录

数据来源：`GET /api/code/dashboard`（Phase 4 Task 4.4 新增）

**Step 2: 验证**
- `#code/dashboard` 能正确显示统计数据

**Step 3: Commit**
```bash
git add frontend/tabs/code-dashboard.html
git commit -m "feat: 创建代码看板 tab — 语言分布 + 仓库明细 + 性能指标"
```

---

### Task 3.5: 创建代码 LanceDB 内部 tab（含原理演示）

**Objective:** 新建代码 LanceDB 内部 tab，包含表概览、数据浏览、原理演示。

**Files:**
- Create: `frontend/tabs/code-lancedb.html`

**Step 1: 创建 tab**

内容：
- 表概览：schema、行数、版本、fragments、indices（调 `/api/code/lancedb/inspect`）
- 数据浏览：分页浏览代码 chunks（调 `/api/code/lancedb/rows`）
- 原理演示：
  - 存入演示：输入代码 → tree-sitter AST 分块 → embedding → 展示向量（调 `/api/code/lancedb/demo/insert`）
  - 搜索演示：输入查询 → 查询翻译 → 三路搜索 → RRF 融合（调 `/api/code/lancedb/demo/search`）

**硬约束：** Embedding 模型信息从后端 API 动态读取，禁止前端硬编码。

**Step 2: 验证**
- `#code/lancedb` 能正确显示（API 端点在 Phase 4 实现，此阶段可先 stub）

**Step 3: Commit**
```bash
git add frontend/tabs/code-lancedb.html
git commit -m "feat: 创建代码 LanceDB 内部 tab — 含原理演示"
```

---

### Task 3.6: 清理 index.html 中已迁移的代码知识库代码

**Objective:** 从 index.html 中删除已迁移的代码知识库 HTML 和 JS。

**Files:**
- Modify: `frontend/index.html`

**Step 1: 删除 `panel-codekb` 相关代码**

**Step 2: 验证**
- 所有 10 个 tab 通过路由加载正常

**Step 3: Commit**
```bash
git add frontend/index.html
git commit -m "refactor: 清理 index.html 中已迁移的代码知识库代码"
```

---

## Phase 4: 后端改造

### Task 4.1: 参数化 lancedb_inspect.py

**Objective:** 让 inspect 模块支持 doc/code 两种 LanceDB。

**Files:**
- Modify: `backend/lancedb_inspect.py`

**Step 1: 添加 db_type 参数**

给以下函数加 `db_type: str = "doc"` 参数：
- `inspect_overview(db_type)`
- `list_rows(db_type, ...)`
- `demo_insert(db_type, ...)`
- `demo_search(db_type, ...)`

内部逻辑：
- `db_type="doc"` → `from db import get_table` + `from embedder import ...`（现有行为）
- `db_type="code"` → `from code_db import get_table` + `from code_embedder import ...`

**demo_insert 和 demo_search 的代码分支逻辑：**

`demo_insert(db_type="code")` 需要实现：
- 输入代码文本 → 用 `code_parser.py` 的 tree-sitter AST 解析
- 按 function/class/method 分块（而非段落分块）
- 用 `code_embedder.py` 的模型 embedding（从 `get_code_model_info()` 读取模型名和维度）
- 展示分块结果和向量

`demo_search(db_type="code")` 需要实现：
- 输入查询 → 调用 `query_translator.py` 翻译（中文→英文关键词）
- 三路搜索：FTS5 关键词 + 向量语义 + symbol LIKE
- RRF 融合排序
- 展示每一步的中间结果

这些逻辑当前不存在于 `lancedb_inspect.py`，需要新增。不能简单地参数化现有函数。

**Step 2: 验证**
- `GET /api/lancedb/inspect` 返回文档 LanceDB 数据（向后兼容）
- `GET /api/lancedb/inspect?db_type=code` 返回代码 LanceDB 数据

**Step 3: Commit**
```bash
git add backend/lancedb_inspect.py
git commit -m "feat: lancedb_inspect 参数化 — 支持 doc/code 两种 LanceDB"
```

---

### Task 4.2: code_routes.py 新增 LanceDB inspect 端点

**Objective:** 为代码 LanceDB 内部 tab 提供 API。

**Files:**
- Modify: `backend/code_routes.py`

**Step 1: 新增端点**

```python
@router.get("/lancedb/inspect")
async def code_lancedb_inspect():
    """代码 LanceDB 表概览"""
    return lancedb_inspect.inspect_overview(db_type="code")

@router.get("/lancedb/rows")
async def code_lancedb_rows(...):
    """代码 LanceDB 数据浏览"""
    return lancedb_inspect.list_rows(db_type="code", ...)

@router.post("/lancedb/demo/insert")
async def code_lancedb_demo_insert(...):
    """代码存入演示 — tree-sitter AST 分块流程"""
    return lancedb_inspect.demo_insert(db_type="code", ...)

@router.post("/lancedb/demo/search")
async def code_lancedb_demo_search(...):
    """代码搜索演示 — 查询翻译+三路搜索+RRF"""
    return lancedb_inspect.demo_search(db_type="code", ...)
```

**Step 2: 验证**
- `curl localhost:8000/api/code/lancedb/inspect` 返回代码 LanceDB 概览
- 原理演示端点返回正确的步骤数据

**Step 3: Commit**
```bash
git add backend/code_routes.py
git commit -m "feat: 代码 LanceDB inspect/demo API 端点"
```

---

### Task 4.3: /api/stats 支持按 db_type 分别查询

**Objective:** 让看板能分别获取文档和代码的统计数据（含性能指标）。

**Files:**
- Modify: `backend/main.py`

**Step 1: 修改 stats 端点**

```python
@app.get("/api/stats")
async def stats(db_type: str = ""):
    """获取统计信息，支持 ?db_type=doc 或 ?db_type=code"""
    result = {}
    if not db_type or db_type == "doc":
        result["documents"] = get_stats()
        result["emails"] = get_email_stats()
        result["embedder"] = get_model_info()
        # 文档性能指标
        result.setdefault("performance", {})
        result["performance"]["lancedb_disk_bytes"] = metrics_db.get_disk_usage(DOC_LANCEDB_PATH)
        result["performance"]["search"] = metrics_db.get_summary("search")
        result["performance"]["insert"] = metrics_db.get_insert_throughput()
    if not db_type or db_type == "code":
        from code_db import get_stats as get_code_stats
        from code_embedder import get_code_model_info
        result["code"] = get_code_stats()
        result["code"]["code_embedder"] = get_code_model_info()
        # 代码性能指标
        result.setdefault("performance", {})
        result["performance"]["code_lancedb_disk_bytes"] = metrics_db.get_disk_usage(CODE_LANCEDB_PATH)
        result["performance"]["code_search"] = metrics_db.get_summary("code_search")
        result["performance"]["code_chat"] = metrics_db.get_summary("code_chat")
        result["performance"]["code_trace"] = metrics_db.get_summary("code_trace")
    return result
```

**Step 2: 验证**
- `GET /api/stats` 返回全部（向后兼容）
- `GET /api/stats?db_type=doc` 只返回文档相关（含性能指标）
- `GET /api/stats?db_type=code` 只返回代码相关（含性能指标）

**Step 3: Commit**
```bash
git add backend/main.py
git commit -m "feat: /api/stats 支持按 db_type 分别查询 + 性能指标拆分"
```

---

### Task 4.4: 代码看板后端 API 补充

**Objective:** 为代码看板提供语言分布、仓库明细、Chunk 类型分布等专用数据。

**Files:**
- Modify: `backend/code_routes.py`

**Step 1: 新增 `/api/code/dashboard` 端点**

```python
@router.get("/dashboard")
async def code_dashboard():
    """代码看板专用数据"""
    from code_db import get_stats
    from code_config import list_repos
    from code_embedder import get_code_model_info

    stats = get_stats()
    repos = list_repos()
    embedder = get_code_model_info()

    return {
        "total_chunks": stats["total_chunks"],
        "total_repos": stats["total_repos"],
        "total_languages": len(stats.get("by_language", {})),
        "total_chunk_types": len(stats.get("by_chunk_type", {})),
        "by_language": stats.get("by_language", {}),
        "by_chunk_type": stats.get("by_chunk_type", {}),
        "repos": [{"name": r["name"], "project_type": r.get("project_type", ""),
                   "chunks": stats.get("by_repo", {}).get(r["name"], 0),
                   "languages": r.get("languages", []),
                   "last_scanned": r.get("last_scanned")} for r in repos],
        "embedder": embedder,
    }
```

**Step 2: 验证**
- `curl localhost:8000/api/code/dashboard` 返回完整看板数据

**Step 3: Commit**
```bash
git add backend/code_routes.py
git commit -m "feat: 代码看板后端 API — 语言分布 + 仓库明细 + Chunk 类型"
```

---

## Phase 5: 深色主题细节打磨

### Task 5.1: 全局深色主题适配

**Objective:** 确保所有 tab 在深色主题下视觉一致。

**Files:**
- Modify: `frontend/css/theme.css`
- Modify: 各 `frontend/tabs/*.html`

**Step 1: 检查并修复**
- 所有表格、表单、按钮、卡片的深色适配
- Chart.js 深色适配：在各 dashboard tab 的 `initDocDashboard()`/`initCodeDashboard()` 中设置全局默认值：
  ```javascript
  Chart.defaults.color = '#94A3B8';        // 标签文字
  Chart.defaults.borderColor = '#334155';  // 网格线
  Chart.defaults.backgroundColor = 'transparent';
  ```
- 代码块和 monospace 元素的深色适配
- Canvas 元素在 tab 切换后需调用 `chart.resize()` 确保尺寸正确

**Step 2: 验证**
- 浏览器逐个 tab 检查视觉一致性

**Step 3: Commit**
```bash
git add frontend/
git commit -m "style: 全局深色主题适配完成"
```

---

### Task 5.2: CSS 动效增强

**Objective:** 添加页面切换和交互的 CSS 动效。

**Files:**
- Modify: `frontend/css/theme.css`

**Step 1: 添加动效**
- 内容区切换：fade-in 200ms（`@keyframes fadeIn`）
- 按钮 hover/active：scale 微动 100ms
- 卡片出现：slide-up 200ms
- 加载状态：骨架屏 pulse 动画

**Step 2: 验证**
- tab 切换有平滑过渡

**Step 3: Commit**
```bash
git add frontend/
git commit -m "style: Sidebar 交互动效 — hover/active/fade-in"
```

---

### Task 5.3: 响应式适配

**Objective:** 确保在不同屏幕宽度下可用。

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/css/theme.css`

**Step 1: 添加响应式**
- `< 768px`：Sidebar 折叠为图标模式（只显示图标，hover 展开文字）
- `768px - 1024px`：Sidebar 缩窄
- `> 1024px`：正常显示

**Step 2: 验证**
- 浏览器调整窗口大小，布局自适应

**Step 3: Commit**
```bash
git add frontend/
git commit -m "style: 响应式适配 — Sidebar 折叠/缩窄/正常"
```

---

## 验证清单

完成后逐项验证：

- [ ] Sidebar 10 个 tab 全部可点击切换
- [ ] 文档管理：上传、搜索、删除正常
- [ ] 邮件导入：列表、导入正常
- [ ] 智能问答：流式回答正常
- [ ] 文档看板：统计数据、图表正常（Chart.js 深色适配）
- [ ] 文档 LanceDB：表概览、数据浏览、原理演示正常
- [ ] 仓库扫描：扫描、列表、删除正常
- [ ] 代码搜索：混合/语义/关键词搜索正常
- [ ] 代码问答：流式回答正常
- [ ] 代码看板：语言分布、仓库明细、性能指标正常
- [ ] 代码 LanceDB：表概览、数据浏览、原理演示正常（模型信息动态读取）
- [ ] 日志面板：全局浮层正常工作
- [ ] 深色主题视觉一致
- [ ] URL hash 可收藏、刷新不丢状态
- [ ] 响应式布局正常
- [ ] Tailwind CDN 动态注入的类名生效
