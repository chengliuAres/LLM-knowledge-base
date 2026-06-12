# 代码知识库「技术架构」tab 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在侧边栏加一个「技术架构」tab（`#code/arch`），用 Mermaid 流程图 + 关键模块详解 + 原理演示三件套，把代码知识库的扫描/搜索/MCP/设计决策/演示讲透。

**Architecture:**
- 新建 `frontend/tabs/code-arch.html`（1 个 tab + 5 分区折叠 + 内嵌 Mermaid + 演示逻辑）
- 下载 Mermaid 10.x minified 到 `frontend/vendor/js/mermaid.min.js`（跟 `tailwindcss.js` 同款本地运行时）
- 后端新增 1 个端点 `POST /api/code/arch/hybrid-demo`（绕开 `search_code` 顶层封装，直接调底层 3 方法）
- 路由 + 侧边栏 + `__TAB_VERSION` 4 处小改

**Tech Stack:**
- 前端：纯 HTML + JS + Mermaid 10.x（无构建步骤）
- 后端：FastAPI + 现有 `code_search.py` / `code_db.py` 模块级函数复用
- vendor 化：Mermaid 10.x minified（MIT，~3.3MB；含全图表类型；vendor 不入库，clone 后需手动下载）

**Reference:**
- Spec：`.claude/worktrees/arch-tab/docs/superpowers/specs/2026-06-12-arch-tab-design.md`
- `frontend/tabs/code-lancedb.html`（C 区演示卡同款样式参考）
- `backend/code_routes.py:1221` `demo_insert`（同款 Sandbox 演示端点）
- `backend/code_routes.py:1322` `demo_search`（同款搜索演示端点）
- `backend/code_search.py:320` `search_code`（**不要调**，用底层函数）
- `backend/code_search.py:266` `_keyword_search_dual`（演示 3 调这个）
- `frontend/index.html:314` `__TAB_VERSION`（bump 24→25）
- `frontend/js/router.js:14-24` 路由表（追加 1 行）

---

## 文件结构

| 路径 | 操作 | 职责 |
|------|------|------|
| `frontend/vendor/js/mermaid.min.js` | 下载 | Mermaid vendor 运行时（~3.3MB；含全图表类型）|
| `frontend/tabs/code-arch.html` | 新建 | 主 tab 文件（5 分区 + Mermaid + 演示 + 内嵌 script）|
| `frontend/js/router.js:24` | 修改 | 加 `code/arch` 路由 1 行 |
| `frontend/index.html:50` | 修改 | 加侧边栏项 1 行 |
| `frontend/index.html:212-217` | 修改 | 加 mermaid vendor script + initMermaid 块 |
| `frontend/index.html:314` | 修改 | `__TAB_VERSION` 24→25 |
| `backend/code_routes.py` | 修改 | 加 `POST /api/code/arch/hybrid-demo` 端点 |
| `CLAUDE.md:140-164` | 修改 | 决策表加 1 行"混搜架构重构" |

---

## Task 1: 下载 Mermaid vendor

**Files:**
- Create: `frontend/vendor/js/mermaid.min.js`

- [ ] **Step 1: 下载 Mermaid 10.x minified 到 vendor 目录**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/.claude/worktrees/arch-tab
mkdir -p frontend/vendor/js
curl -sL https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js \
  -o frontend/vendor/js/mermaid.min.js
```

- [ ] **Step 2: 验证文件存在 + 大小 + 首行**

```bash
ls -la frontend/vendor/js/mermaid.min.js
head -c 200 frontend/vendor/js/mermaid.min.js
```

Expected: 文件约 **3.3MB**（Mermaid 10.x minified 完整版，含 flowchart/sequence/gantt/class/state/er/pie 等全图表类型；**不是早期估算的 200-300KB**，那个数字严重低估）。首行包含 `mermaid` / UMD wrapper 关键字

- [ ] **Step 3: 验证 MIT 协议声明**

```bash
grep -c "MIT License\|@license" frontend/vendor/js/mermaid.min.js
```

Expected: ≥ 1

- [ ] **Step 4: 不 commit（vendor 文件应该在 .gitignore 里或者单独管理，先看下）**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/.claude/worktrees/arch-tab
cat .gitignore 2>/dev/null | grep -i vendor
git check-ignore frontend/vendor/js/mermaid.min.js && echo "IGNORED" || echo "NOT IGNORED"
```

如果 `NOT IGNORED`：
- 选项 A：把 `frontend/vendor/js/mermaid.min.js` 加入 `.gitignore`（**不推荐**，vendor 化就是要在 git 里管理）
- 选项 B：commit 进 git（Mermaid 是 MIT，可入库；参考 `frontend/vendor/js/tailwindcss.js` 是否入库）

```bash
ls -la frontend/vendor/js/tailwindcss.js
git ls-files frontend/vendor/js/tailwindcss.js
```

如果 `tailwindcss.js` 也在 git 里跟踪 → 选项 B 跟进；如果 ignore → 选项 A 跟进。

- [ ] **Step 5: Commit（按 .gitignore 调查结果）**

如果 vendor 在 git 跟踪：
```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/.claude/worktrees/arch-tab
git add frontend/vendor/js/mermaid.min.js
git commit -m "chore(vendor): Mermaid 10.x minified for code-arch tab

MIT 协议；~3.3MB；与 tailwindcss.js 同款不入库本地运行时

⚠️ 全新 clone 后 mermaid.min.js 跟 tailwindcss.js 都会丢，需手动下载（项目级约定）"
```

否则跳过 commit，文件不进 git。

---

## Task 2: index.html 加 vendor 资源 + bump `__TAB_VERSION`

**Files:**
- Modify: `frontend/index.html:212-217`（追加 mermaid vendor script）
- Modify: `frontend/index.html:314`（`__TAB_VERSION` 24→25）

- [ ] **Step 1: 定位 `index.html` 关键行（验证当前真实行号）**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/.claude/worktrees/arch-tab
grep -n "router.js\|__TAB_VERSION\|tailwindcss" frontend/index.html
```

Expected: 找到 3 处位置（CSS 引用、JS 引用、版本号），行号以实际输出为准

- [ ] **Step 2: 加 mermaid vendor script（router.js 之后）**

找到 router.js 引用那行（`<script src=".../router.js">`），在它之后追加：

```html
    <!-- Mermaid vendor（技术架构 tab 用） -->
    <script src="vendor/js/mermaid.min.js"></script>
    <script>
        window.initMermaid = function() {
            if (window.mermaid) {
                window.mermaid.initialize({
                    startOnLoad: false,
                    theme: 'dark',
                    securityLevel: 'loose',
                    themeVariables: { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' },
                });
            }
        };
        if (window.mermaid) { initMermaid(); }
        else { document.addEventListener('DOMContentLoaded', initMermaid); }
    </script>
```

⚠️ **不要替换** 原有 router.js 那行，**只在它之后追加**。

- [ ] **Step 3: bump `__TAB_VERSION` 24→25**

找到 `window.__TAB_VERSION = '24';`，改成 `'25'`。

- [ ] **Step 4: 验证改动**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/.claude/worktrees/arch-tab
grep -n "mermaid.min.js\|__TAB_VERSION" frontend/index.html
```

Expected: 看到 2 处新增 + 1 处版本号变更

- [ ] **Step 5: 手动浏览器验证 vendor 加载**

启动 `cd backend && source venv/bin/activate && python3 -m uvicorn main:app --reload`，浏览器打开 `http://localhost:8000`，F12 Console 跑 `window.mermaid` —— 应返回 Mermaid 对象。

- [ ] **Step 6: Commit**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/.claude/worktrees/arch-tab
git add frontend/index.html
git commit -m "feat(frontend): 加 Mermaid vendor + bump __TAB_VERSION=25

vendor 化 Mermaid 10.x 用于 code-arch tab 流程图渲染
bump __TAB_VERSION=25（router cache-bust 必做）"
```

---

## Task 3: router.js 加路由 + index.html 加侧边栏项

**Files:**
- Modify: `frontend/js/router.js:24`（追加 1 行）
- Modify: `frontend/index.html:50`（追加 1 行）

- [ ] **Step 1: 定位当前真实行号**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/.claude/worktrees/arch-tab
grep -n "code/mcp\|code/lancedb" frontend/js/router.js
grep -n "code/mcp\|code/lancedb" frontend/index.html
```

- [ ] **Step 2: router.js 追加路由**

在 `"code/mcp"` 路由行之后追加：

```js
  "code/arch":      { file: "tabs/code-arch.html",      title: "技术架构",     init: "initCodeArch" },
```

- [ ] **Step 3: index.html 加侧边栏项**

在 `🔌 <span>MCP 接入</span>` 那行之后追加：

```html
                <a class="sidebar-item" data-route="code/arch" href="#code/arch">🧭 <span>技术架构</span></a>
```

⚠️ 缩进要对齐侧边栏其他项（参照同行写法）。

- [ ] **Step 4: 验证**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/.claude/worktrees/arch-tab
grep -n "code/arch\|code/mcp" frontend/js/router.js frontend/index.html
```

Expected: 4 处（router.js 1 + index.html 侧边栏 1 + 隐含路由触发 + sidebar 渲染）

- [ ] **Step 5: 浏览器验证（路由可达，但 tab 文件还不存在，会报 404）**

硬刷新浏览器，访问 `http://localhost:8000/#code/arch` —— 应看到 404 提示（Mermaid vendor 已经在，路由可达，但 tab 文件还没建）。

- [ ] **Step 6: Commit**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/.claude/worktrees/arch-tab
git add frontend/js/router.js frontend/index.html
git commit -m "feat(frontend): 加 code/arch 路由 + 侧边栏项

侧边栏代码知识库组最后一项：🧭 技术架构
路由 init 函数 initCodeArch 在 code-arch.html 里实现"
```

---

## Task 4: 创建 code-arch.html 骨架（A 区占位）

**Files:**
- Create: `frontend/tabs/code-arch.html`

- [ ] **Step 1: 创建骨架文件**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/.claude/worktrees/arch-tab
touch frontend/tabs/code-arch.html
```

- [ ] **Step 2: 写入骨架 HTML + 5 分区折叠 + A 区占位**

写入 `frontend/tabs/code-arch.html`：

```html
<!--
    代码知识库「技术架构」tab
    5 分区折叠：A 扫描流程 / B 搜索架构 / C MCP 协议 / D 设计决策 / E 原理演示
    Mermaid vendor 已在 index.html 加载，本文件只需 <pre class="mermaid">源码</pre>，由 initCodeArch 调 mermaid.run 渲染
    依赖：window.mermaid（vendor 提供）、window.escapeHtml（shared.js 提供）
-->
<div class="space-y-4">

    <!-- 顶部提示条 -->
    <div id="arch-no-repo-banner" class="panel text-sm" style="display:none; background-color: rgba(245, 158, 11, 0.10); border-color: rgba(245, 158, 11, 0.40);">
        ⚠️ 当前未配置代码仓库。请先在「代码仓库」tab 添加仓库后，再体验扫描/搜索/演示。
    </div>

    <!-- ─── A 区：仓库扫描流程 ─── -->
    <div class="panel">
        <button onclick="toggleArchSection('a')" class="flex items-center gap-2 text-base font-semibold w-full text-left focus:outline-none" style="color: var(--color-foreground);">
            <span id="arch-a-arrow" class="transition-transform duration-300" style="color: var(--color-muted);">▼</span>
            🏗️ A. 仓库扫描流程
        </button>
        <div id="arch-a-content" class="mt-4 space-y-4">
            <p class="text-sm" style="color: var(--color-muted);">从目录遍历到 LanceDB/SQLite 双写，每一步做什么、关键模块、参数坑。</p>
            <div class="text-xs p-3" style="background-color: rgba(245, 158, 11, 0.10); border-left: 3px solid #FCD34D; color: var(--color-muted);">
                <strong style="color: #FCD34D;">⚠️ 已知风险：</strong>
                <code>_PARSER_CACHE</code> 仍是模块级 <code>dict</code>（<code>code_parser.py:132</code>），跨线程共享可能 panic。
                CLAUDE.md 描述的 <code>threading.local()</code> 改造<strong>尚未落地</strong>——push 前如发现 panic 再修（参考 <code>coding-design-principles.md</code> 案例 4 教训）。
            </div>
            <pre class="mermaid">flowchart TD
    A[用户配置: 仓库路径 + skip_rules] --> B[scan_directory 目录遍历]
    B --> C{文件大小 &lt; max_file_size_kb?}
    C -->|否| X1[skip<br/>记录到 metrics]
    C -->|是| D[扩展名 in skip_exts?]
    D -->|是| X2[skip]
    D -->|否| E[读文件内容]
    E --> F[code_parser.parse_repo]
    F --> G[tree-sitter AST<br/>提取 symbols + 调用关系]
    G --> H[混合分块<br/>函数/类/方法粒度<br/>MAX_CHUNK_SIZE=900]
    H --> I[code_embedder.embed_batch<br/>bge-small-en 384维]
    I --> J[双写: code_lancedb + code_index.db]
    J --> K[code_relations 表<br/>插入调用边]
    J --> L[code_meta FTS5 同步]
    K --> M[watchdog 周期巡检]
    L --> M
    M -->|文件变更| B</pre>
        </div>
    </div>

    <!-- B/C/D/E 区占位，Task 5/6 填充 -->
    <div class="panel"><div class="text-sm" style="color: var(--color-muted);">B/C/D/E 区 — 后续任务填充</div></div>

</div>

<style>
    /* 折叠/展开动画：默认全部展开（max-height: none），点击后切 0 */
    #arch-a-content, #arch-b-content, #arch-c-content, #arch-d-content, #arch-e-content {
        overflow: hidden;
        transition: max-height 0.4s ease-out;
        max-height: 8000px;
    }
    #arch-a-content.collapsed,
    #arch-b-content.collapsed,
    #arch-c-content.collapsed,
    #arch-d-content.collapsed,
    #arch-e-content.collapsed {
        max-height: 0;
    }
</style>

<script>
/* ============================================================
 * 代码知识库「技术架构」tab — 页面脚本
 * initCodeArch() 由 router.js 路由命中后调用
 * 依赖：window.mermaid（vendor）、window.escapeHtml（shared.js）
 * ============================================================ */

// ─── 折叠/展开 ────────────────────────────────────────
window.toggleArchSection = function (key) {
    const content = document.getElementById(`arch-${key}-content`);
    const arrow = document.getElementById(`arch-${key}-arrow`);
    if (!content) return;
    if (content.classList.contains('collapsed')) {
        content.classList.remove('collapsed');
        if (arrow) arrow.style.transform = 'rotate(0deg)';
    } else {
        content.classList.add('collapsed');
        if (arrow) arrow.style.transform = 'rotate(-90deg)';
    }
};

// ─── 路由入口 ─────────────────────────────────────────
window.initCodeArch = async function () {
    // 1. 检查 mermaid vendor 是否加载
    if (window.__MERMAID_LOAD_FAILED) {
        console.warn('Mermaid vendor 加载失败，图表回退到 ASCII 源码显示');
        return;
    }
    // 2. 渲染所有 Mermaid 块
    try {
        if (window.mermaid && window.mermaid.run) {
            await window.mermaid.run({ querySelector: 'pre.mermaid' });
        }
    } catch (err) {
        console.error('Mermaid 渲染失败:', err);
    }
    // 3. 检查仓库配置（顶部提示条）
    try {
        const res = await fetch('/api/code/repos');
        if (res.ok) {
            const data = await res.json();
            const repos = data.repos || data || [];
            if (!repos || repos.length === 0) {
                const banner = document.getElementById('arch-no-repo-banner');
                if (banner) banner.style.display = 'block';
            }
        }
    } catch (err) {
        console.warn('检查 code_repos 失败:', err);
    }
};
</script>
```

- [ ] **Step 3: 浏览器验证 A 区 Mermaid 渲染**

硬刷新浏览器，访问 `#code/arch`：
- 看到 A 区 Mermaid 流程图**渲染成功**（不是源码 fallback）
- 顶部提示条 `arch-no-repo-banner` 默认隐藏（如果没仓库会显示）
- 点 A 区按钮能折叠/展开

- [ ] **Step 4: Commit**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/.claude/worktrees/arch-tab
git add frontend/tabs/code-arch.html
git commit -m "feat(frontend): code-arch.html 骨架 + A 区扫描流程 Mermaid

5 分区折叠骨架，A 区扫描流程 Mermaid 渲染通
initCodeArch() 路由入口：渲染 Mermaid + 检查 repo 配置
B/C/D/E 区占位，Task 5/6 填充"
```

---

## Task 5: 填充 B/C/D 区

**Files:**
- Modify: `frontend/tabs/code-arch.html`（追加 B/C/D 三个分区）

- [ ] **Step 1: 在骨架里 "B/C/D/E 占位" 那行之前插入 B 区**

⚠️ 步骤 2-4 是独立的小修改，每步 commit 一次会拆太碎；这里**一次性插入 3 个区**，最后整体 commit。

在 `<!-- B/C/D/E 区占位，Task 5/6 填充 -->` 之前插入：

```html
    <!-- ─── B 区：搜索匹配架构 ─── -->
    <div class="panel">
        <button onclick="toggleArchSection('b')" class="flex items-center gap-2 text-base font-semibold w-full text-left focus:outline-none" style="color: var(--color-foreground);">
            <span id="arch-b-arrow" class="transition-transform duration-300" style="color: var(--color-muted);">▼</span>
            🔍 B. 搜索匹配架构
        </button>
        <div id="arch-b-content" class="mt-4 space-y-4">
            <p class="text-sm" style="color: var(--color-muted);">顶层 3 路召回 + 翻译层降级 + trace BFS 多跳追踪</p>

            <h4 class="text-sm font-semibold" style="color: var(--color-foreground);">B.1 混搜架构图（代码真实现状：顶层 3 路 + keyword 内 EN/CN 子双路）</h4>
            <pre class="mermaid">flowchart LR
    Q[用户 query<br/>中文 or 英文] --> T[query_translator.translate]
    T -->|词典/缓存命中| KW[英文关键词]
    T -->|未命中| T2[MyMemory API]
    T2 --> KW
    KW --> P1[顶层路径1: 向量<br/>bge-small-en embed<br/>weight=1.0]
    KW --> P2[顶层路径2: keyword_dual<br/>英文 FTS5 weight=1.0<br/>中文 FTS5 weight=0.3<br/>组合 weight=0.5]
    Q --> P2
    KW --> P3[顶层路径3: 符号名LIKE<br/>symbol_name LIKE %kw%<br/>weight=1.5]
    P1 --> R[RRF 融合排序<br/>k=60]
    P2 --> R
    P3 --> R
    R --> O[top_k 结果<br/>含 match_reasons]</pre>

            <h4 class="text-sm font-semibold" style="color: var(--color-foreground);">B.2 混搜对比表</h4>
            <div class="overflow-x-auto">
                <table class="w-full text-xs" style="border-collapse: collapse;">
                    <thead><tr style="background-color: rgba(255,255,255,0.04);">
                        <th class="px-2 py-2 text-left">层</th>
                        <th class="px-2 py-2 text-left">路径</th>
                        <th class="px-2 py-2 text-left">方法</th>
                        <th class="px-2 py-2 text-left">权重</th>
                        <th class="px-2 py-2 text-left">效果</th>
                    </tr></thead>
                    <tbody>
                        <tr style="border-bottom: 1px solid var(--color-border);"><td class="px-2 py-1.5">顶层 1</td><td class="px-2 py-1.5">A</td><td class="px-2 py-1.5">bge-small-en (384维) 向量搜索</td><td class="px-2 py-1.5 font-mono">1.0</td><td class="px-2 py-1.5">同语言英文→英文代码</td></tr>
                        <tr style="border-bottom: 1px solid var(--color-border);"><td class="px-2 py-1.5">顶层 2</td><td class="px-2 py-1.5">A2 (EN)</td><td class="px-2 py-1.5">SQLite FTS5 + jieba (英文)</td><td class="px-2 py-1.5 font-mono">1.0</td><td class="px-2 py-1.5">英文 content/symbol 精确匹配</td></tr>
                        <tr style="border-bottom: 1px solid var(--color-border);"><td class="px-2 py-1.5">顶层 2</td><td class="px-2 py-1.5">A3 (CN)</td><td class="px-2 py-1.5">SQLite FTS5 + jieba (中文)</td><td class="px-2 py-1.5 font-mono">0.3</td><td class="px-2 py-1.5">中文 content 弱信号</td></tr>
                        <tr style="border-bottom: 1px solid var(--color-border);"><td class="px-2 py-1.5">顶层 2 (合并)</td><td class="px-2 py-1.5">keyword_dual</td><td class="px-2 py-1.5">RRF 融合 A2 + A3</td><td class="px-2 py-1.5 font-mono">0.5</td><td class="px-2 py-1.5">keyword 路总权重</td></tr>
                        <tr style="border-bottom: 1px solid var(--color-border);"><td class="px-2 py-1.5">顶层 3</td><td class="px-2 py-1.5">D</td><td class="px-2 py-1.5">symbol_name LIKE %kw%</td><td class="px-2 py-1.5 font-mono">1.5</td><td class="px-2 py-1.5">最可靠，兜底 FTS5 驼峰拆分盲区</td></tr>
                    </tbody>
                </table>
            </div>
            <p class="text-xs" style="color: var(--color-muted);">代码参考：<code>code_search.py:307</code>（keyword 内部 EN/CN 双路权重 <code>[1.0, 0.3]</code>）、<code>code_search.py:519</code>（顶层三路 RRF 融合权重 <code>[1.0, 0.5, 1.5]</code>）</p>

            <h4 class="text-sm font-semibold" style="color: var(--color-foreground);">B.3 翻译层降级链</h4>
            <pre class="mermaid">flowchart TD
    Q[中文 query] --> S1{step1: 词典贪心<br/>最长匹配}
    S1 -->|命中| EN[输出英文]
    S1 -->|未命中| S2{step2: 词典<br/>jieba 逐词}
    S2 -->|命中| EN
    S2 -->|未命中| S3{step3: 翻译缓存<br/>translation_cache.json}
    S3 -->|命中| EN
    S3 -->|未命中| S4{step4: MyMemory API}
    S4 -->|200| EN
    S4 -->|失败| S5{step5: LLM 翻译}
    S5 -->|200| EN
    S5 -->|失败| FB[原 query 回退]</pre>
            <div class="text-xs" style="color: var(--color-muted);">
                <div>• MyMemory 翻译不写缓存（直译置信度低，写缓存永久污染词典）</div>
                <div>• 词典优先于 API（"读信"→read/mail/message 命中 ReadCell.m）</div>
            </div>

            <h4 class="text-sm font-semibold" style="color: var(--color-foreground);">B.4 调用链追踪（trace）BFS 多跳</h4>
            <pre class="mermaid">flowchart TD
    S[输入符号:<br/>reloadAttachmentByCellModel] --> L0[L0: search_code 定位定义点]
    L0 --> N1[节点1: GHReadProtocolImpl.reloadAttachmentByCellModel]
    N1 -->|outgoing| N2[节点2: GHMailListCellModel.refreshData]
    N1 -->|outgoing| N3[节点3: GHAttachmentLoader.fetchData]
    N2 -->|outgoing| N4[节点4: addObject:]
    N2 -->|outgoing| N5[节点5: compare:]
    N3 -->|outgoing| N6[节点6: sendAsynchronousRequest]
    M[direction=hierarchy<br/>继承链: 反向查 relations.incoming]</pre>

            <h4 class="text-sm font-semibold" style="color: var(--color-foreground);">B.5 关键代码引用（示意）</h4>
            <pre class="text-xs overflow-x-auto" style="background-color: rgba(0,0,0,0.30); padding: 12px; border-radius: 6px;"><code># 真实入口: code_search.py:320 search_code(mode='hybrid')
def search_code(query, mode="hybrid", top_k=20, repo_name=None, language=None):
    keywords = query_translator.translate(query)  # 走 B.3 降级链
    vec_results = code_db.vector_search(keywords, top_k)  # 顶层 1
    kw_results  = _keyword_search_dual(keywords, query)   # 顶层 2，EN+CN 子双路
    like_results = code_db.symbol_like(keywords)            # 顶层 3
    fused = rrf_fusion(
        [vec_results, kw_results, like_results],
        weights=[1.0, 0.5, 1.5],  # 顶层权重
        k=60,
    )
    return fused[:top_k]</code></pre>
        </div>
    </div>
```

- [ ] **Step 2: 插入 C 区**

```html
    <!-- ─── C 区：MCP 协议层 ─── -->
    <div class="panel">
        <button onclick="toggleArchSection('c')" class="flex items-center gap-2 text-base font-semibold w-full text-left focus:outline-none" style="color: var(--color-foreground);">
            <span id="arch-c-arrow" class="transition-transform duration-300" style="color: var(--color-muted);">▼</span>
            🔌 C. MCP 协议层
        </button>
        <div id="arch-c-content" class="mt-4 space-y-4">
            <h4 class="text-sm font-semibold" style="color: var(--color-foreground);">C.1 MCP 5 tools 总览</h4>
            <div class="overflow-x-auto">
                <table class="w-full text-xs" style="border-collapse: collapse;">
                    <thead><tr style="background-color: rgba(255,255,255,0.04);">
                        <th class="px-2 py-2 text-left">Tool</th>
                        <th class="px-2 py-2 text-left">入参</th>
                        <th class="px-2 py-2 text-left">返回</th>
                    </tr></thead>
                    <tbody>
                        <tr style="border-bottom: 1px solid var(--color-border);"><td class="px-2 py-1.5 font-mono">code_search</td><td class="px-2 py-1.5">query, repo, top_k, hybrid</td><td class="px-2 py-1.5">top-K chunks + match_reasons</td></tr>
                        <tr style="border-bottom: 1px solid var(--color-border);"><td class="px-2 py-1.5 font-mono">code_chat</td><td class="px-2 py-1.5">question, repo, language</td><td class="px-2 py-1.5">非流式 JSON 字符串（REST /api/code/chat 才支持 SSE）</td></tr>
                        <tr style="border-bottom: 1px solid var(--color-border);"><td class="px-2 py-1.5 font-mono">code_list_repos</td><td class="px-2 py-1.5">—</td><td class="px-2 py-1.5">已索引仓库列表</td></tr>
                        <tr style="border-bottom: 1px solid var(--color-border);"><td class="px-2 py-1.5 font-mono">code_file_context</td><td class="px-2 py-1.5">repo, file_name</td><td class="px-2 py-1.5">单文件所有 chunks（v2.1 改造：file_path → file_name）</td></tr>
                        <tr><td class="px-2 py-1.5 font-mono">code_trace</td><td class="px-2 py-1.5">repo, symbol, direction, depth</td><td class="px-2 py-1.5">BFS 调用链 / 继承链</td></tr>
                    </tbody>
                </table>
            </div>

            <h4 class="text-sm font-semibold" style="color: var(--color-foreground);">C.2 Streamable HTTP 链路</h4>
            <pre class="mermaid">sequenceDiagram
    participant Agent as AI Agent (MCP client)
    participant MCP as code_mcp_v2.py<br/>MCP Server
    participant SR as code_search.py
    participant CD as code_db.py
    participant LLM as llm_client.py
    Agent->>MCP: POST /mcp/ tools/call code_search
    MCP->>SR: search_code(mode='hybrid', ...)
    SR->>CD: vector + fts5_dual + symbol_like
    CD-->>SR: 三路召回结果
    SR-->>MCP: RRF 融合 top-K
    MCP-->>Agent: JSON-RPC 2.0 响应
    Agent->>MCP: POST /mcp/ tools/call code_chat
    MCP->>SR: search_code(mode='hybrid', top_k=5)
    SR-->>MCP: top-K chunks
    MCP->>LLM: build_rag_prompt (一次性，非流式)
    LLM-->>MCP: 完整回答 JSON
    MCP-->>Agent: JSON 字符串 (MCP 端 code_chat 非流式)</pre>

            <h4 class="text-sm font-semibold" style="color: var(--color-foreground);">C.3 e2e 真实 query 链路</h4>
            <ol class="text-xs space-y-1" style="color: var(--color-muted); list-style: decimal inside;">
                <li>Agent 调 <code>code_search(query="读附件", repo="ghmail")</code></li>
                <li>MCP 走 B 区混搜：翻译"读附件"→<code>read attachment</code>，走顶层 3 路</li>
                <li>Agent 调 <code>code_file_context(repo="ghmail", file_name="GHAttachmentLoader.m")</code></li>
                <li>Agent 调 <code>code_trace(... direction="callees", depth=2)</code></li>
                <li>Agent 调 <code>code_chat(question="详细说明", repo="ghmail")</code>（MCP 非流式）</li>
            </ol>
        </div>
    </div>
```

- [ ] **Step 3: 插入 D 区**

```html
    <!-- ─── D 区：关键设计决策 ─── -->
    <div class="panel">
        <button onclick="toggleArchSection('d')" class="flex items-center gap-2 text-base font-semibold w-full text-left focus:outline-none" style="color: var(--color-foreground);">
            <span id="arch-d-arrow" class="transition-transform duration-300" style="color: var(--color-muted);">▼</span>
            📐 D. 关键设计决策
        </button>
        <div id="arch-d-content" class="mt-4 space-y-4">
            <h4 class="text-sm font-semibold" style="color: var(--color-foreground);">D.1 设计决策表</h4>
            <div class="overflow-x-auto">
                <table class="w-full text-xs" style="border-collapse: collapse;">
                    <thead><tr style="background-color: rgba(255,255,255,0.04);">
                        <th class="px-2 py-2 text-left">决策</th>
                        <th class="px-2 py-2 text-left">结论</th>
                        <th class="px-2 py-2 text-left">证据</th>
                    </tr></thead>
                    <tbody>
                        <tr style="border-bottom: 1px solid var(--color-border);"><td class="px-2 py-1.5">跨语言 embedding（e5/bge-m3）代替翻译层</td><td class="px-2 py-1.5">❌</td><td class="px-2 py-1.5">中文 query → 纯英文 OC 代码召回接近随机</td></tr>
                        <tr style="border-bottom: 1px solid var(--color-border);"><td class="px-2 py-1.5">词典是第一道防线</td><td class="px-2 py-1.5">✅</td><td class="px-2 py-1.5">"读信"→read/mail/message 命中 ReadCell.m</td></tr>
                        <tr style="border-bottom: 1px solid var(--color-border);"><td class="px-2 py-1.5">Embedding 前剥离注释/中文字面量</td><td class="px-2 py-1.5">✅</td><td class="px-2 py-1.5">剥离后向量路不再偏到中文噪声</td></tr>
                        <tr style="border-bottom: 1px solid var(--color-border);"><td class="px-2 py-1.5">MyMemory 翻译不写入缓存/词典</td><td class="px-2 py-1.5">✅</td><td class="px-2 py-1.5">直译置信度低，写缓存永久污染</td></tr>
                        <tr style="border-bottom: 1px solid var(--color-border);"><td class="px-2 py-1.5">向量阈值 0.0→0.5</td><td class="px-2 py-1.5">✅</td><td class="px-2 py-1.5">score = (1+余弦相似度)/2，0.5=正交分界</td></tr>
                        <tr style="border-bottom: 1px solid var(--color-border);"><td class="px-2 py-1.5">文档侧保持 bge-base-zh-v1.5</td><td class="px-2 py-1.5">✅</td><td class="px-2 py-1.5">同语言中文→中文，换多语言降低单项质量</td></tr>
                        <tr><td class="px-2 py-1.5"><strong>混搜架构重构</strong>（CLAUDE.md 旧 4 路 → 顶层 3 路）</td><td class="px-2 py-1.5">✅ 已落地</td><td class="px-2 py-1.5">旧 4 路融合时 keyword 被中文带偏；keyword 内 EN/CN 子双路 + 顶层三路让权重可调</td></tr>
                    </tbody>
                </table>
            </div>

            <h4 class="text-sm font-semibold" style="color: var(--color-foreground);">D.2 反例存档（CLAUDE.md 链接）</h4>
            <div class="space-y-2 text-xs">
                <details><summary class="cursor-pointer">📚 案例 1：PushService deviceToken 并发修复（2026-05-27，ghmail）— 减法思维经典</summary>
                    <div class="mt-2 p-3" style="background-color: rgba(0,0,0,0.20); border-radius: 4px; color: var(--color-muted);">
                        init 中 1s delay 触发的 cached token retry 与 deviceTokenReceived: 形成 race。<br>
                        AI 初版 +22 行加锁；柳哥减法方案 -4 行，识别 deviceTokenReceived: 已是带锁的权威入口，让 chaneNetSignal 路径调它消除并发。
                    </div>
                </details>
                <details><summary class="cursor-pointer">📚 案例 2：MCP 测试示例 file_path "README.md 必有" 翻车（2026-06-12）— 不查数据源拍脑袋</summary>
                    <div class="mt-2 p-3" style="background-color: rgba(0,0,0,0.20); border-radius: 4px; color: var(--color-muted);">
                        ghmail/README.md 是 0 字节占位；code_index.db 里整个 *.md 都被 skip 规则排除。<br>
                        AI 初版不查直接拍：换 mailflutter/README.md 仍然 0 命中。<br>
                        正确方案：sqlite3 查 code_meta 表找出真实存在的且 chunk 数适中的文件。
                    </div>
                </details>
                <details><summary class="cursor-pointer">📚 案例 3：file_path 改 file_name（2026-06-12 v2.1）— 减法+合并</summary>
                    <div class="mt-2 p-3" style="background-color: rgba(0,0,0,0.20); border-radius: 4px; color: var(--color-muted);">
                        code_file_context 强迫 AI 拼 path，错位。柳哥要求彻底废弃 file_path 入参，单一入参 file_name，后端做 name→path 映射。<br>
                        AI 初版"为兼容性"保留双入口。正确方案：敢删旧入参。
                    </div>
                </details>
                <details><summary class="cursor-pointer">📚 案例 4：MCP trace 召回翻车 — 100KB 硬编码 + parser 跨线程 panic（2026-06-12）</summary>
                    <div class="mt-2 p-3" style="background-color: rgba(0,0,0,0.20); border-radius: 4px; color: var(--color-muted);">
                        scan_directory 写死 100KB → 222KB 的 GHReadProtocolImpl.m 整个 skip；_PARSER_CACHE 模块级 dict 跨线程 panic。<br>
                        教训：硬编码数字阈值走配置；pyo3/torch 等 native handle 默认 threading.local()。
                    </div>
                </details>
            </div>
        </div>
    </div>
```

- [ ] **Step 4: 浏览器验证 B/C/D 区 Mermaid + 表格 + details**

硬刷新浏览器，访问 `#code/arch`：
- B/C/D 区 Mermaid 全部渲染成功（不是源码 fallback）
- B.2 表格行整齐
- D.1 决策表 7 行
- D.2 4 个 `<details>` 默认折叠，点击展开

- [ ] **Step 5: Commit**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/.claude/worktrees/arch-tab
git add frontend/tabs/code-arch.html
git commit -m "feat(frontend): code-arch.html 填充 B/C/D 区

B 区：4 张 Mermaid（混搜架构/翻译降级/trace BFS/代码引用）+ 5 行对比表
C 区：MCP 5 tools 表 + Streamable HTTP 序列图 + e2e 5 步链路
D 区：7 行决策表 + 4 个 details 反例存档（折叠）
3 张 Mermaid 验证渲染通过"
```

---

## Task 6: 填充 E 区演示卡 1+2

**Files:**
- Modify: `frontend/tabs/code-arch.html`（在 D 区之后追加 E 区）

- [ ] **Step 1: 在 D 区之后、E 区占位之前插入 E 区（演示 1+2）**

⚠️ 演示 3 留到 Task 7（依赖后端端点）。

把 D 区结尾 `</div></div>` 之后、"B/C/D/E 区占位"那行替换成真正的 E 区：

```html
    <!-- ─── E 区：原理演示 ─── -->
    <div class="panel">
        <button onclick="toggleArchSection('e')" class="flex items-center gap-2 text-base font-semibold w-full text-left focus:outline-none" style="color: var(--color-foreground);">
            <span id="arch-e-arrow" class="transition-transform duration-300" style="color: var(--color-muted);">▼</span>
            🧪 E. 原理演示
        </button>
        <div id="arch-e-content" class="mt-4 space-y-4">
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">

                <!-- 演示 1：📥 存入演示（Sandbox，不写库） -->
                <div class="panel" style="background-color: rgba(100, 116, 139, 0.10); border-color: rgba(100, 116, 139, 0.30);">
                    <h4 class="font-semibold text-sm mb-3" style="color: var(--color-foreground);">📥 存入演示 <span class="text-xs font-normal" style="color: var(--color-muted);">(Sandbox 不写库)</span></h4>
                    <div class="space-y-2 mb-3">
                        <textarea id="arch-insert-text" rows="4" class="input w-full text-sm font-mono" style="padding: 6px 10px;">def hello():
    print("hi")

def add(a, b):
    return a + b</textarea>
                        <div class="grid grid-cols-3 gap-2">
                            <select id="arch-insert-lang" class="input w-full text-sm" style="padding: 6px 10px;">
                                <option value="python">python</option>
                                <option value="javascript">javascript</option>
                                <option value="typescript">typescript</option>
                                <option value="java">java</option>
                                <option value="go">go</option>
                            </select>
                            <input type="text" id="arch-insert-repo" value="demo" class="input w-full text-sm" style="padding: 6px 10px;">
                            <input type="text" id="arch-insert-path" value="demo/hello.py" class="input w-full text-sm" style="padding: 6px 10px;">
                        </div>
                        <button onclick="runArchInsertDemo()" id="arch-insert-btn" class="btn w-full" style="background-color: var(--color-primary); color: var(--color-foreground); border: 1px solid var(--color-border); padding: 8px;">🚀 执行演示</button>
                    </div>
                    <div id="arch-insert-steps" class="space-y-2"></div>
                </div>

                <!-- 演示 2：🔍 搜索演示（真实 search_code，只读） -->
                <div class="panel" style="background-color: rgba(245, 158, 11, 0.08); border-color: rgba(245, 158, 11, 0.30);">
                    <h4 class="font-semibold text-sm mb-3" style="color: var(--color-foreground);">🔍 搜索演示 <span class="text-xs font-normal" style="color: var(--color-muted);">(真实只读)</span></h4>
                    <div class="space-y-2 mb-3">
                        <input type="text" id="arch-search-query" value="读附件" class="input w-full text-sm" style="padding: 6px 10px;">
                        <div class="grid grid-cols-2 gap-2">
                            <input type="number" id="arch-search-topk" value="5" class="input w-full text-sm" style="padding: 6px 10px;" placeholder="top_k">
                            <input type="number" id="arch-search-threshold" value="0.3" step="0.05" class="input w-full text-sm" style="padding: 6px 10px;" placeholder="score_threshold">
                        </div>
                        <button onclick="runArchSearchDemo()" id="arch-search-btn" class="btn w-full" style="background-color: rgba(245, 158, 11, 0.85); color: white; padding: 8px;">🔍 执行演示</button>
                    </div>
                    <div id="arch-search-steps" class="space-y-2"></div>
                </div>

                <!-- 演示 3 占位：🌐 混搜可视化（Task 7 实现） -->
                <div class="panel" style="background-color: rgba(99, 102, 241, 0.08); border-color: rgba(99, 102, 241, 0.30);">
                    <h4 class="font-semibold text-sm mb-3" style="color: var(--color-foreground);">🌐 混搜可视化 <span class="text-xs font-normal" style="color: var(--color-muted);">(Task 7 实现)</span></h4>
                    <p class="text-xs" style="color: var(--color-muted);">3 张子卡片分别展示 vector / keyword_dual / symbol_like 召回 + 1 张 RRF 融合结果卡</p>
                </div>

            </div>
        </div>
    </div>
```

- [ ] **Step 2: 在 `<script>` 块里加演示 1+2 的执行函数（追加在 `initCodeArch` 之后）**

在 `window.initCodeArch = async function () { ... }` 之后追加：

```js
// ─── 演示 1：存入演示（调 /api/code/lancedb/demo/insert） ─────
window.runArchInsertDemo = async function () {
    const btn = document.getElementById('arch-insert-btn');
    const stepsDiv = document.getElementById('arch-insert-steps');
    btn.disabled = true;
    stepsDiv.innerHTML = '<div class="text-xs" style="color: var(--color-muted);">执行中...</div>';
    try {
        const res = await fetch('/api/code/lancedb/demo/insert', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                text: document.getElementById('arch-insert-text').value,
                language: document.getElementById('arch-insert-lang').value,
                repo_name: document.getElementById('arch-insert-repo').value,
                file_path: document.getElementById('arch-insert-path').value,
            }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || '请求失败');
        stepsDiv.innerHTML = renderArchSteps(data.steps || []);
    } catch (err) {
        stepsDiv.innerHTML = `<div class="text-xs" style="color: #FCA5A5;">❌ ${escapeHtml(err.message)}</div>`;
    } finally {
        btn.disabled = false;
    }
};

// ─── 演示 2：搜索演示（调 /api/code/lancedb/demo/search） ─────
window.runArchSearchDemo = async function () {
    const btn = document.getElementById('arch-search-btn');
    const stepsDiv = document.getElementById('arch-search-steps');
    btn.disabled = true;
    stepsDiv.innerHTML = '<div class="text-xs" style="color: var(--color-muted);">执行中...</div>';
    try {
        const res = await fetch('/api/code/lancedb/demo/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query: document.getElementById('arch-search-query').value,
                top_k: parseInt(document.getElementById('arch-search-topk').value),
                score_threshold: parseFloat(document.getElementById('arch-search-threshold').value),
            }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || '请求失败');
        stepsDiv.innerHTML = renderArchSteps(data.steps || []);
    } catch (err) {
        stepsDiv.innerHTML = `<div class="text-xs" style="color: #FCA5A5;">❌ ${escapeHtml(err.message)}</div>`;
    } finally {
        btn.disabled = false;
    }
};

// ─── 步骤渲染（参考 code-lancedb.html 的 renderSteps） ─────
function renderArchSteps(steps) {
    if (!steps || steps.length === 0) return '<div class="text-xs" style="color: var(--color-muted);">无步骤</div>';
    return steps.map((s, i) => {
        const desc = escapeHtml(s.description || s.name || '');
        const output = s.output ? JSON.stringify(s.output, null, 2) : '';
        return `
            <details class="text-xs">
                <summary class="cursor-pointer" style="color: var(--color-foreground);">${i + 1}. ${escapeHtml(s.name || 'step')}</summary>
                <div class="mt-1 p-2" style="background-color: rgba(0,0,0,0.20); border-radius: 4px;">
                    <div style="color: var(--color-muted);">${desc}</div>
                    ${output ? `<pre class="mt-1 overflow-x-auto" style="font-size: 10px; color: #93C5FD;">${escapeHtml(output)}</pre>` : ''}
                </div>
            </details>
        `;
    }).join('');
}
```

- [ ] **Step 3: 浏览器验证演示 1+2**

硬刷新浏览器，访问 `#code/arch`：
- E 区 3 张卡横排（演示 1/2 真实可点；演示 3 占位）
- 点"🚀 执行演示"（演示 1）：返回分块 + embedding 步骤
- 点"🔍 执行演示"（演示 2）：返回搜索步骤
- **不真实写库**（演示 1 标 Sandbox）

- [ ] **Step 4: Commit**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/.claude/worktrees/arch-tab
git add frontend/tabs/code-arch.html
git commit -m "feat(frontend): code-arch.html E 区演示 1+2

演示 1 搬自 code-lancedb C 区（Sandbox 不写库）
演示 2 搬自 code-lancedb C 区（真实 search_code 只读）
演示 3 占位（Task 7 实现）
renderArchSteps 步骤渲染函数"
```

---

## Task 7: 后端 hybrid-demo 端点 + E 区演示 3

**Files:**
- Modify: `backend/code_routes.py`（追加 1 个端点）
- Modify: `frontend/tabs/code-arch.html`（演示 3 占位换成真卡 + 调端点函数）

- [ ] **Step 1: 定位 `code_routes.py` 末尾插入位置**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/.claude/worktrees/arch-tab
grep -n "demo_search\|@router.post.*code.*lancedb" backend/code_routes.py | head -5
tail -20 backend/code_routes.py
```

- [ ] **Step 2: 追加端点（参考 `demo_search` 风格）**

在 `demo_search` 函数之后追加（实际行号看 grep 结果）：

```python
@router.post("/arch/hybrid-demo")
async def arch_hybrid_demo(req: Request):
    """技术架构 tab 演示 3：混搜分层可视化

    绕开 search_code 顶层封装，直接调底层 3 个方法（vector/keyword_dual/symbol_like），
    返回每路 top-3 + RRF 融合结果。
    """
    from code_search import _keyword_search_dual
    from code_db import vector_search as _vector_search, symbol_like as _symbol_like
    from query_translator import translate as _translate
    from embedder import embed_text as _embed_text
    from code_config import load_repos as _load_repos
    import json

    try:
        body = await req.json()
    except Exception:
        body = {}

    query = (body.get("query") or "").strip()
    repo = (body.get("repo") or "").strip()
    top_k = int(body.get("top_k") or 5)

    if not query:
        return JSONResponse({"error": "query 不能为空"}, status_code=400)

    # repo 缺省策略：取 config/code_repos.json 第一个有索引数据的 repo
    if not repo:
        try:
            repos = _load_repos()
            for r in repos:
                name = r.get("name") if isinstance(r, dict) else str(r)
                if name:
                    repo = name
                    break
        except Exception:
            pass
    if not repo:
        return JSONResponse({"error": "未配置 code_repos，请先在'代码仓库' tab 添加仓库"}, status_code=400)

    # 翻译
    try:
        translated = _translate(query)
    except Exception as e:
        translated = query
    keywords = translated if isinstance(translated, list) else [str(translated)]

    # 顶层 1：向量召
    try:
        vec_emb = _embed_text(query)
        vector_results = _vector_search(vec_emb, top_k=3, repo_name=repo)
    except Exception as e:
        vector_results = []
    # 顶层 2：keyword_dual（内部 EN+CN 子双路 rrf_fusion）
    try:
        kw_results = _keyword_search_dual(keywords, query, top_k=3, repo_name=repo)
    except Exception as e:
        kw_results = []
    # 顶层 3：symbol_like
    try:
        like_results = _symbol_like(keywords, repo_name=repo, top_k=3)
    except Exception as e:
        like_results = []

    # 顶层 RRF 融合（调 search_code 拿融合结果，但只取前 top_k）
    try:
        from code_search import search_code
        fused = search_code(query=query, mode="hybrid", top_k=top_k, repo_name=repo)
    except Exception as e:
        fused = []

    return {
        "query": query,
        "translated_keywords": keywords,
        "repo": repo,
        "vector_path": vector_results[:3],
        "keyword_dual_path": kw_results[:3],
        "symbol_like_path": like_results[:3],
        "rrf_fused": fused[:top_k],
    }
```

⚠️ **导入**：`_keyword_search_dual` / `vector_search` / `symbol_like` / `embed_text` / `translate` / `load_repos` 实际函数名 / 模块位置可能跟假设不同，**落地时按 `code_search.py:266` / `code_db.py` / `embedder.py` / `query_translator.py` / `code_config.py` 实际定义核对**。如果某个函数名不对应，按 grep 结果调整。

- [ ] **Step 3: 验证后端端点**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/.claude/worktrees/arch-tab
cd backend && source venv/bin/activate
python3 -c "from code_routes import arch_hybrid_demo" 2>&1 | head -5
```

Expected: 无 import error（语法正确）

启动服务：
```bash
python3 -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 &
sleep 3
```

curl 测试：
```bash
curl -X POST http://localhost:8000/api/code/arch/hybrid-demo \
  -H "Content-Type: application/json" \
  -d '{"query": "读附件", "top_k": 3}'
```

Expected: 200 + JSON 返回（`vector_path` / `keyword_dual_path` / `symbol_like_path` / `rrf_fused` 4 个 key）

- [ ] **Step 4: 把 E 区演示 3 占位换成真卡**

在 `frontend/tabs/code-arch.html` 里找到"演示 3 占位"那整块 div，替换为：

```html
                <!-- 演示 3：🌐 混搜可视化（新增端点） -->
                <div class="panel" style="background-color: rgba(99, 102, 241, 0.08); border-color: rgba(99, 102, 241, 0.30);">
                    <h4 class="font-semibold text-sm mb-3" style="color: var(--color-foreground);">🌐 混搜可视化</h4>
                    <div class="space-y-2 mb-3">
                        <input type="text" id="arch-hybrid-query" value="reloadAttachmentByCellModel" class="input w-full text-sm font-mono" style="padding: 6px 10px;">
                        <button onclick="runArchHybridDemo()" id="arch-hybrid-btn" class="btn w-full" style="background-color: rgba(99, 102, 241, 0.85); color: white; padding: 8px;">🌐 执行混搜可视化</button>
                    </div>
                    <div id="arch-hybrid-steps" class="space-y-2"></div>
                </div>
```

在 `</script>` 之前追加：

```js
// ─── 演示 3：混搜可视化（调 /api/code/arch/hybrid-demo） ─────
window.runArchHybridDemo = async function () {
    const btn = document.getElementById('arch-hybrid-btn');
    const stepsDiv = document.getElementById('arch-hybrid-steps');
    btn.disabled = true;
    stepsDiv.innerHTML = '<div class="text-xs" style="color: var(--color-muted);">执行中（混搜 3 路 + 融合）...</div>';
    try {
        const res = await fetch('/api/code/arch/hybrid-demo', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query: document.getElementById('arch-hybrid-query').value,
                top_k: 3,
            }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.error || '请求失败');
        // 4 子 section：3 路 + 1 融合
        stepsDiv.innerHTML = `
            <details class="text-xs" open>
                <summary class="cursor-pointer" style="color: #93C5FD;">🅰 顶层 1: 向量 (${data.vector_path.length} 条)</summary>
                <pre class="mt-1 p-2 overflow-x-auto" style="background-color: rgba(0,0,0,0.20); border-radius: 4px; font-size: 10px;">${escapeHtml(JSON.stringify(data.vector_path, null, 2))}</pre>
            </details>
            <details class="text-xs" open>
                <summary class="cursor-pointer" style="color: #FCD34D;">🅱 顶层 2: keyword_dual (${data.keyword_dual_path.length} 条)</summary>
                <pre class="mt-1 p-2 overflow-x-auto" style="background-color: rgba(0,0,0,0.20); border-radius: 4px; font-size: 10px;">${escapeHtml(JSON.stringify(data.keyword_dual_path, null, 2))}</pre>
            </details>
            <details class="text-xs" open>
                <summary class="cursor-pointer" style="color: #A5B4FC;">🅲 顶层 3: symbol_like (${data.symbol_like_path.length} 条)</summary>
                <pre class="mt-1 p-2 overflow-x-auto" style="background-color: rgba(0,0,0,0.20); border-radius: 4px; font-size: 10px;">${escapeHtml(JSON.stringify(data.symbol_like_path, null, 2))}</pre>
            </details>
            <details class="text-xs" open>
                <summary class="cursor-pointer" style="color: #86EFAC;">✨ RRF 融合 (${data.rrf_fused.length} 条)</summary>
                <pre class="mt-1 p-2 overflow-x-auto" style="background-color: rgba(0,0,0,0.20); border-radius: 4px; font-size: 10px;">${escapeHtml(JSON.stringify(data.rrf_fused, null, 2))}</pre>
            </details>
        `;
    } catch (err) {
        stepsDiv.innerHTML = `<div class="text-xs" style="color: #FCA5A5;">❌ ${escapeHtml(err.message)}<br><button onclick="runArchHybridDemo()" class="btn mt-2" style="padding: 4px 10px;">重试</button></div>`;
    } finally {
        btn.disabled = false;
    }
};
```

- [ ] **Step 5: 浏览器端到端验证演示 3**

硬刷新浏览器，访问 `#code/arch`，E 区点"🌐 执行混搜可视化"：
- 4 张子 section（向量 / keyword_dual / symbol_like / RRF 融合）都返回数据
- 每张卡片显示 top-3 条

- [ ] **Step 6: Commit（后端 + 前端一起）**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/.claude/worktrees/arch-tab
git add backend/code_routes.py frontend/tabs/code-arch.html
git commit -m "feat(code-arch): 后端 /api/code/arch/hybrid-demo + E 区演示 3

后端：新增 POST /api/code/arch/hybrid-demo
- 绕开 search_code 顶层封装，直接调底层 3 方法
- 返回 vector_path / keyword_dual_path / symbol_like_path / rrf_fused 4 路
- repo 缺省从 config/code_repos.json 取第一个

前端：E 区演示 3 占位换成真卡
- 4 张子 section（3 路 + 1 融合）默认展开
- 失败时显示重试按钮"
```

---

## Task 8: 端到端验证 + 同步 CLAUDE.md

**Files:**
- Modify: `CLAUDE.md:140-164`（决策表加 1 行"混搜架构重构"）

- [ ] **Step 1: 完整 e2e 验证清单**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/.claude/worktrees/arch-tab
# 服务在跑（uvicorn）
curl -s http://localhost:8000/api/code/arch/hybrid-demo -X POST \
  -H "Content-Type: application/json" \
  -d '{"query": "读附件", "top_k": 3}' | head -c 500
```

Expected: 200 + JSON 4 路返回

浏览器硬刷新访问 `#code/arch`：
- [ ] 5 分区全部展开
- [ ] 5 张 Mermaid 全部渲染（A.1 / B.1 / B.3 / B.4 / C.2）
- [ ] B.2 表格 5 行
- [ ] C.1 表格 5 行
- [ ] D.1 表格 7 行 + D.2 4 个 details
- [ ] E 区演示 1 输入 `def hello()` 点执行 → 返回分块步骤
- [ ] E 区演示 2 输入 `读附件` 点执行 → 返回搜索步骤
- [ ] E 区演示 3 输入 `reloadAttachmentByCellModel` 点执行 → 4 张子 section
- [ ] `__TAB_VERSION=25` 生效（新 tab 出现）

- [ ] **Step 2: 跑 REGRESSION_TEST.md 已有用例**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/.claude/worktrees/arch-tab
grep -A 3 "代码搜索\|code/arch\|MCP" REGRESSION_TEST.md 2>/dev/null | head -20
```

Expected: 现有 11 个 tab 的测试用例全部通过（MCP 接入 / 代码搜索 / 代码仓库）；不破

- [ ] **Step 3: 同步 CLAUDE.md（决策表加 1 行）**

在 `CLAUDE.md` "代码搜索准确率策略" 节（行 140-164 附近），表格末尾加 1 行：

```markdown
| 混搜架构重构：CLAUDE.md 旧 4 路 A/B/C/D=1.0/1.0/0.3/1.5 → 顶层 3 路 vector/keyword_dual/symbol_like=1.0/0.5/1.5（keyword 内 EN/CN 子双路 1.0/0.3） | ✅ 已落地 | 旧 4 路模型融合时 keyword 路被中文噪声带偏；keyword 内 EN/CN 子双路 + 顶层三路让权重可调 | `code_search.py:307` + `:519` |
```

实际行号用 grep 核对：
```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/.claude/worktrees/arch-tab
grep -n "文档侧保持\|MyMemory 翻译不写入" CLAUDE.md
```

在最后一行（"文档侧保持"）之后追加。

- [ ] **Step 4: 跑 commit（含同步 CLAUDE.md）**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/.claude/worktrees/arch-tab
git add CLAUDE.md
git commit -m "docs: 同步 CLAUDE.md 加混搜架构重构决策行

补充 D 区决策表同步：
- CLAUDE.md 旧 4 路 A/B/C/D=1.0/1.0/0.3/1.5
- 实际是顶层 3 路 vector/keyword_dual/symbol_like=1.0/0.5/1.5
- keyword 内 EN/CN 子双路 1.0/0.3
参考 code_search.py:307 + :519"
```

- [ ] **Step 5: 整个 worktree 状态 sanity check**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/.claude/worktrees/arch-tab
git log --oneline origin/code_knowledge_base..feature/arch-tab 2>&1
echo "---worktree status---"
git status 2>&1 | head -3
echo "---主仓 status---"
git -C /Users/admin/Desktop/AI产出/email-wiki-demo status 2>&1 | head -3
```

Expected:
- worktree 跟 origin diff = 7-8 个 commit（spec + 6 个实施 + CLAUDE.md 同步）
- worktree 干净
- 主仓干净（除了 mcp-test-tab2 submodule 提示）

- [ ] **Step 6: 推 worktree branch 到 origin（如需）**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo/.claude/worktrees/arch-tab
git push -u origin feature/arch-tab 2>&1 | tail -5
```

⚠️ **推不推等柳哥指示**（按 git-workflow.md "明令才能 push"）。这一步柳哥授权再跑。

---

## 验收清单

最终 commit 后，浏览器硬刷新访问 `#code/arch` 应能看到：

- 5 分区全部展开（A 扫描 / B 搜索 / C MCP / D 设计 / E 演示）
- 5 张 Mermaid 全部渲染（不是源码 fallback）
- B.2 5 行对比表 + C.1 5 行 tool 表 + D.1 7 行决策表
- D.2 4 个 `<details>` 反例存档默认折叠
- E 区 3 张演示卡：演示 1 Sandbox 不写库 / 演示 2 真实只读 / 演示 3 4 张子 section
- 顶部提示条（如未配置仓库）显示
- 折叠按钮可切换各区显示

## 不在范围

- 把"原理演示"从 `code-lancedb.html` C 区**完全删除**（保留兼容）
- 加 Mermaid 暗色主题切换按钮
- 加 D 区反例存档的"修复 commit hash"自动链接
- 其他 tab（doc-*）的"原理演示"搬迁
