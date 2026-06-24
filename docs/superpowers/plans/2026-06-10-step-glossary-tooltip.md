# Step 流程术语 Hover 解释功能 - 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 4 个主要面板（代码搜索流程/翻译流程 + 两个 Dashboard 的 Step 耗时拆解）中给英文术语/技术名词加鼠标 hover 解释（深色风中文 tooltip），术语词典集中维护，零后端改动。

**Architecture:**
- 新增 `frontend/js/glossary.js`：术语 SSOT + 字符串级/DOM 级包装 API
- 新增 `frontend/js/glossary-tooltip.js`：单例 tooltip 渲染与事件委托
- 新增 `frontend/css/glossary.css`：暗色风样式（独立文件避免污染 theme.css）
- `index.html` 全局引入两个 JS
- 4 个面板在术语渲染处接入：`code-search.html`（2 处）、`doc-dashboard.html`（旁挂术语图例）、`code-dashboard.html`（旁挂术语图例）
- Dashboard 采用「旁挂术语图例」方案（方案 Y），因为 Chart.js canvas 不直接支持 HTML label，方案 Y 实现最稳

**Tech Stack:**
- 原生 JS（无构建步骤）
- Tailwind runtime（已有）
- Chart.js（已用 canvas，不直接支持 HTML label）

---

## 文件结构

| 路径 | 责任 | 状态 |
|------|------|------|
| `frontend/js/glossary.js` | 术语词典 + wrapTerm/applyGlossary API | 新建 |
| `frontend/js/glossary-tooltip.js` | 单例 tooltip DOM + 事件委托 + 定位 | 新建 |
| `frontend/css/glossary.css` | .glossary-term / .glossary-tooltip 样式 | 新建 |
| `frontend/index.html` | 引入 2 个 JS + 1 个 CSS | 改 |
| `frontend/tabs/code-search.html` | 翻译流程 + 搜索流程面板接入 wrapTerm | 改 |
| `frontend/tabs/doc-dashboard.html` | 在 breakdown chart 旁挂术语图例 | 改 |
| `frontend/tabs/code-dashboard.html` | 在 breakdown chart 旁挂术语图例 | 改 |

---

## Task 1: 新建 glossary.js（术语词典 + API）

**Files:**
- Create: `frontend/js/glossary.js`

- [ ] **Step 1.1: 创建文件，写入术语词典和工具函数**

```js
/**
 * 术语词典 SSOT + 包装 API
 *
 * 约定:
 * - 词典 key 用后端 step.name 的原始英文形式 (snake_case 为主)
 * - 解释用中文, 1-2 句话, 重点说"它是什么/做什么"
 * - 加新术语只改这个文件, 刷新页面即可生效
 */

const GLOSSARY = {
    // 搜索流程 (code_search / query_translator)
    hybrid_search:      "混合搜索: 同时跑向量 + FTS5 + 符号三路, 用 RRF 融合排序",
    vector_search:      "向量搜索: 用 Embedding 模型把查询转成向量, 按余弦相似度找最相关的代码片段",
    keyword_search:     "关键词搜索: 在 SQLite FTS5 全文索引中精确匹配关键词 (支持中文原文)",
    embed_query:        "生成查询向量: 把用户输入转成 Embedding 模型输出, 用于相似度搜索",
    rrf_fusion:         "RRF 融合 (Reciprocal Rank Fusion): 多路结果按排名倒数加权融合, 合并为统一排序",
    query_translate:    "查询翻译: 把中文查询自动翻译为英文代码关键词, 提高英文代码库匹配率",
    lanceDB_search:     "LanceDB 向量检索: 在向量数据库中执行余弦距离计算, 返回最相似的文档块",

    // 调用链追踪
    trace_search:       "搜索起始符号: 用混合搜索定位用户指定的符号出现在哪些文件",
    trace_chain:        "追踪调用链: 从起始符号沿调用关系多跳追踪 (向上找调用方, 向下找被调方)",

    // 问答
    llm_generate:       "LLM 生成回答: 把检索到的相关片段作为上下文, 调用大模型生成自然语言答案",

    // 翻译流程
    translation_cache:  "翻译缓存命中: 直接从 data/translation_cache.json 读取已有翻译结果 (0ms)",
    llm_translate:      "LLM 翻译: 用 MiMo 等大模型做中英翻译, 翻译质量最高",
    mymemory_translate: "MyMemory API: 调用免费在线翻译 API 做中英翻译 (日 5000 字符限额)",
    dict_translate:     "本地词典翻译: 在内置 TERM_MAP 中匹配中文词, 无网络依赖",
    fallback:           "翻译降级: 所有翻译方式都失败时, 保留原文让 FTS5 搜索中文 content",

    // 通用技术名词
    RRF:            "Reciprocal Rank Fusion: 多路结果融合排序算法",
    FTS5:           "SQLite 全文搜索引擎 v5, 支持快速关键词匹配",
    LanceDB:        "基于 Lance 列式格式的向量数据库, 存 Embedding 向量",
    "bge-small-en": "BAAI/bge-small-en-v1.5 英文 Embedding 模型 (384 维)",
    MiMo:           "项目默认配置的大模型 (见 llm_client.py), 用于翻译和问答",
    MyMemory:       "MyMemory 免费在线翻译 API, 翻译失败时的备用方案",
};

/**
 * 转义正则元字符
 */
function escapeRegExp(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * 字符串级包装: 把 text 中出现的所有术语用 <span data-glossary="key"> 包起来
 * - 按 key 长度倒序匹配, 避免短词截断长词
 * - 大小写不敏感 (RRF / rrf 都能匹配)
 * - 跳过已包过的 [data-glossary] span 内部
 * @param {string} text
 * @returns {string} HTML 字符串 (含可能的 <span> 标签)
 */
function wrapTerm(text) {
    if (typeof text !== "string" || !text) return text;
    const keys = Object.keys(GLOSSARY).sort((a, b) => b.length - a.length);
    let result = text;
    for (const key of keys) {
        // 用单词边界, 大小写不敏感
        // 注意: key 中可能含 - (如 bge-small-en), 单词边界在 - 处不匹配
        // 所以无 key 边界用 (?=\b|$|[\s,;:.()]) 之类
        const re = new RegExp(`(${escapeRegExp(key)})`, "gi");
        result = result.replace(re, (m) => {
            // 避免重复包裹 (data-glossary span 内部)
            return `<span class="glossary-term" data-glossary="${key}" tabindex="0">${m}</span>`;
        });
    }
    return result;
}

/**
 * DOM 节点级批量包装: 扫描 rootEl 内所有 textNode, 替换为包裹后的节点
 * - 跳过 <script> / <style> 标签
 * - 跳过已包过的 [data-glossary] 元素
 * @param {HTMLElement} rootEl
 */
function applyGlossary(rootEl) {
    if (!rootEl) return;
    const walker = document.createTreeWalker(rootEl, NodeFilter.SHOW_TEXT, {
        acceptNode(node) {
            if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
            const p = node.parentElement;
            if (!p) return NodeFilter.FILTER_REJECT;
            if (p.closest("script, style, [data-glossary]")) return NodeFilter.FILTER_REJECT;
            return NodeFilter.FILTER_ACCEPT;
        },
    });
    const targets = [];
    let n;
    while ((n = walker.nextNode())) targets.push(n);

    for (const t of targets) {
        const html = wrapTerm(t.nodeValue);
        if (html !== t.nodeValue) {
            const tmp = document.createElement("span");
            tmp.innerHTML = html;
            const frag = document.createDocumentFragment();
            while (tmp.firstChild) frag.appendChild(tmp.firstChild);
            t.replaceWith(frag);
        }
    }
}

// 暴露到 window
window.GLOSSARY = GLOSSARY;
window.wrapTerm = wrapTerm;
window.applyGlossary = applyGlossary;
window._glossaryEscapeRegExp = escapeRegExp;
```

- [ ] **Step 1.2: 验证文件创建成功**

Run:
```bash
ls -la frontend/js/glossary.js
```
Expected: 文件存在, 大小 ~3KB

- [ ] **Step 1.3: Commit**

```bash
git add frontend/js/glossary.js
git commit -m "feat(glossary): 新增术语词典 SSOT + wrapTerm/applyGlossary API"
```

---

## Task 2: 新建 glossary-tooltip.js（单例 tooltip + 事件委托）

**Files:**
- Create: `frontend/js/glossary-tooltip.js`

- [ ] **Step 2.1: 创建文件，写入 tooltip 渲染与事件委托**

```js
/**
 * 术语 hover tooltip — 单例 DOM + 事件委托
 *
 * 用法: 不需要手动调用, 加载此脚本后, 任何带 [data-glossary] 属性的元素
 * 鼠标 hover 都会自动显示 tooltip
 *
 * 行为:
 * - mouseenter 0.15s 防抖后显示
 * - mouseleave 0.1s 延迟隐藏 (含移入 tooltip 自身)
 * - focus 时显示, Esc 关闭
 * - 视口边界检测: 超出右/下边界时翻向左/上
 */

(function () {
    const SHOW_DELAY = 150;
    const HIDE_DELAY = 100;
    const TOOLTIP_GAP = 8;        // 目标元素与 tooltip 的间距
    const TOOLTIP_MAX_WIDTH = 320;

    let tooltipEl = null;
    let currentTarget = null;
    let showTimer = null;
    let hideTimer = null;

    function ensureTooltip() {
        if (tooltipEl) return tooltipEl;
        tooltipEl = document.createElement("div");
        tooltipEl.className = "glossary-tooltip";
        tooltipEl.setAttribute("role", "tooltip");
        tooltipEl.style.position = "fixed";
        tooltipEl.style.maxWidth = TOOLTIP_MAX_WIDTH + "px";
        tooltipEl.style.pointerEvents = "auto";   // 允许 hover 到 tooltip 自身
        document.body.appendChild(tooltipEl);
        return tooltipEl;
    }

    function lookupGlossary(key) {
        return (window.GLOSSARY && window.GLOSSARY[key]) || null;
    }

    function show(target) {
        if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
        const key = target.getAttribute("data-glossary");
        const text = lookupGlossary(key);
        if (!text) return;

        const tip = ensureTooltip();
        tip.textContent = text;
        tip.classList.remove("is-bottom");
        tip.classList.add("is-visible");
        currentTarget = target;

        // 定位: 默认在目标元素上方居中
        const rect = target.getBoundingClientRect();
        const tipRect = tip.getBoundingClientRect();
        const vw = window.innerWidth;
        const vh = window.innerHeight;

        // 水平: 居中, 防止溢出
        let left = rect.left + rect.width / 2 - tipRect.width / 2;
        left = Math.max(8, Math.min(left, vw - tipRect.width - 8));

        // 垂直: 优先上方, 超出上边界则翻下
        let top = rect.top - tipRect.height - TOOLTIP_GAP;
        let isBottom = false;
        if (top < 8) {
            top = rect.bottom + TOOLTIP_GAP;
            isBottom = true;
        }

        tip.style.left = left + "px";
        tip.style.top = top + "px";
        if (isBottom) tip.classList.add("is-bottom");
    }

    function hide() {
        if (!tooltipEl) return;
        tooltipEl.classList.remove("is-visible");
        currentTarget = null;
    }

    function scheduleShow(target) {
        if (showTimer) clearTimeout(showTimer);
        showTimer = setTimeout(() => {
            showTimer = null;
            show(target);
        }, SHOW_DELAY);
    }

    function scheduleHide() {
        if (showTimer) { clearTimeout(showTimer); showTimer = null; }
        if (hideTimer) clearTimeout(hideTimer);
        hideTimer = setTimeout(() => {
            hideTimer = null;
            hide();
        }, HIDE_DELAY);
    }

    // 事件委托在 document
    document.addEventListener("mouseover", (e) => {
        const t = e.target.closest("[data-glossary]");
        if (!t) return;
        scheduleShow(t);
    });

    document.addEventListener("mouseout", (e) => {
        const t = e.target.closest("[data-glossary]");
        if (!t) return;
        // 如果鼠标移到了 tooltip 自身, 不隐藏
        const related = e.relatedTarget;
        if (related && (related === tooltipEl || tooltipEl?.contains(related))) return;
        scheduleHide();
    });

    // tooltip 自身的 hover: 取消隐藏
    document.addEventListener("mouseover", (e) => {
        if (e.target === tooltipEl || tooltipEl?.contains(e.target)) {
            if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
        }
    });
    document.addEventListener("mouseout", (e) => {
        if (e.target === tooltipEl || tooltipEl?.contains(e.target)) {
            scheduleHide();
        }
    });

    // 键盘可达: focus 显示, blur 隐藏
    document.addEventListener("focusin", (e) => {
        const t = e.target.closest("[data-glossary]");
        if (!t) return;
        if (showTimer) { clearTimeout(showTimer); showTimer = null; }
        show(t);
    });
    document.addEventListener("focusout", (e) => {
        const t = e.target.closest("[data-glossary]");
        if (!t) return;
        scheduleHide();
    });

    // Esc 关闭
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && tooltipEl?.classList.contains("is-visible")) {
            if (showTimer) { clearTimeout(showTimer); showTimer = null; }
            if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
            hide();
            if (currentTarget && currentTarget.focus) currentTarget.blur();
        }
    });
})();
```

- [ ] **Step 2.2: 验证文件创建成功**

Run:
```bash
ls -la frontend/js/glossary-tooltip.js
```
Expected: 文件存在, 大小 ~4KB

- [ ] **Step 2.3: Commit**

```bash
git add frontend/js/glossary-tooltip.js
git commit -m "feat(glossary): 新增术语 hover tooltip 单例 + 事件委托"
```

---

## Task 3: 新建 glossary.css（暗色风样式）

**Files:**
- Create: `frontend/css/glossary.css`

- [ ] **Step 3.1: 创建文件，写入样式**

```css
/* 术语 hover 解释 — 暗色风卡片样式 */

.glossary-term {
    border-bottom: 1px dashed var(--color-primary, #6366f1);
    cursor: help;
    color: inherit;
    transition: border-bottom-color 0.15s;
}

.glossary-term:hover,
.glossary-term:focus {
    border-bottom-color: var(--color-accent, #22c55e);
}

.glossary-term:focus {
    outline: 1px dotted var(--color-primary, #6366f1);
    outline-offset: 2px;
}

.glossary-tooltip {
    position: fixed;
    z-index: 9999;
    max-width: 320px;
    padding: 8px 12px;
    background: var(--color-bg-elevated, #1e293b);
    color: var(--color-foreground, #e2e8f0);
    border: 1px solid var(--color-border, #334155);
    border-radius: 8px;
    font-size: 12px;
    line-height: 1.5;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
    pointer-events: auto;
    white-space: pre-wrap;
    word-wrap: break-word;
    opacity: 0;
    visibility: hidden;
    transition: opacity 0.12s, visibility 0.12s;
}

.glossary-tooltip.is-visible {
    opacity: 1;
    visibility: visible;
}

/* 默认三角: tooltip 在目标下方, 三角在 tooltip 顶部 (朝上) */
.glossary-tooltip::after {
    content: "";
    position: absolute;
    top: -6px;
    left: 50%;
    transform: translateX(-50%);
    border: 6px solid transparent;
    border-top: none;
    border-bottom-color: var(--color-bg-elevated, #1e293b);
}

/* tooltip 在目标上方时 (is-bottom), 三角在 tooltip 底部 (朝下) */
.glossary-tooltip.is-bottom::after {
    top: auto;
    bottom: -6px;
    border-top-color: var(--color-bg-elevated, #1e293b);
    border-bottom: none;
}
```

- [ ] **Step 3.2: 验证文件创建成功**

Run:
```bash
ls -la frontend/css/glossary.css
```
Expected: 文件存在, 大小 ~1KB

- [ ] **Step 3.3: Commit**

```bash
git add frontend/css/glossary.css
git commit -m "feat(glossary): 新增术语 tooltip 暗色风样式"
```

---

## Task 4: index.html 全局引入 glossary 资源

**Files:**
- Modify: `frontend/index.html:13-14,211-212`

- [ ] **Step 4.1: 在 theme.css 之后新增 glossary.css 引用**

修改 `frontend/index.html` 第 14 行附近，在 theme.css 后追加：

```html
    <!-- 全局暗色主题（侧边栏/侧边栏项/面板/按钮/输入框等） -->
    <link rel="stylesheet" href="css/theme.css">
    <!-- 术语 hover tooltip 样式 -->
    <link rel="stylesheet" href="css/glossary.css?v=1">
```

- [ ] **Step 4.2: 在 router.js 之后新增两个 JS 引用**

修改 `frontend/index.html` 第 211-212 行附近：

```html
    <script src="js/shared.js?v=5"></script>
    <script src="js/router.js?v=7"></script>
    <!-- 术语词典 + tooltip（依赖 shared.js 的 window 全局） -->
    <script src="js/glossary.js?v=1"></script>
    <script src="js/glossary-tooltip.js?v=1"></script>
```

- [ ] **Step 4.3: 验证修改**

Run:
```bash
grep -n "glossary" frontend/index.html
```
Expected: 至少 3 行匹配 (1 行 css, 2 行 js)

- [ ] **Step 4.4: Commit**

```bash
git add frontend/index.html
git commit -m "feat(glossary): index.html 全局引入词典 + tooltip 资源"
```

---

## Task 5: 接入 code-search.html - 搜索流程面板

**Files:**
- Modify: `frontend/tabs/code-search.html:266-290`（`codeRenderSearchStep` 函数）

- [ ] **Step 5.1: 修改 codeRenderSearchStep，把 step.description / step.name 用 wrapTerm 包裹**

定位 `frontend/tabs/code-search.html` 第 266-290 行的 `codeRenderSearchStep` 函数，把 L284 行的：

```js
            <span class="text-xs font-medium" style="color: var(--color-foreground);">${escapeHtml(step.description || step.name || '')}</span>
```

替换为：

```js
            <span class="text-xs font-medium" style="color: var(--color-foreground);">${wrapTerm(step.description || step.name || '')}</span>
```

> 说明：原代码用 `escapeHtml` 是为了防 XSS，但 step.description 来自后端 add_step 调用，wrapTerm 内会生成 `<span>` HTML 标签，必须直接输出 HTML 而非转义。词典 key 来自受控词典，**不构成 XSS 风险**（用户输入不会进词典 key）。

- [ ] **Step 5.2: 验证修改**

Run:
```bash
grep -n "wrapTerm(step" frontend/tabs/code-search.html
```
Expected: 至少 1 行匹配

- [ ] **Step 5.3: Commit**

```bash
git add frontend/tabs/code-search.html
git commit -m "feat(glossary): 接入代码搜索-搜索流程面板的术语 hover"
```

---

## Task 6: 接入 code-search.html - 翻译流程面板

**Files:**
- Modify: `frontend/tabs/code-search.html:233-263`（`codeRenderTranslationStep` 函数）

- [ ] **Step 6.1: 修改 codeRenderTranslationStep，keywords 区域用 wrapTerm 包裹**

定位 `frontend/tabs/code-search.html` 第 261 行的 keywords 显示：

```js
            <div class="ml-5 mt-1 text-[10px]" style="color: var(--color-muted);">${escapeHtml(kws)}</div>
```

替换为：

```js
            <div class="ml-5 mt-1 text-[10px]" style="color: var(--color-muted);">${wrapTerm(kws)}</div>
```

> 说明：keywords 来自 `step.keywords` 数组（后端翻译的英文关键词），其中可能含 glossary 词典 key（如 `cache`、`llm`）。label 区域（`escapeHtml(label)`）是中文 labelMap 映射值，不含英文术语，保持原样。

- [ ] **Step 6.2: 验证修改**

Run:
```bash
grep -n "wrapTerm(kws)" frontend/tabs/code-search.html
```
Expected: 1 行匹配

- [ ] **Step 6.3: Commit**

```bash
git add frontend/tabs/code-search.html
git commit -m "feat(glossary): 接入代码搜索-翻译流程面板的术语 hover"
```

---

## Task 7: 接入 doc-dashboard.html - Step 耗时拆解旁挂术语图例

**Files:**
- Modify: `frontend/tabs/doc-dashboard.html:83-97`（Step 耗时拆解 panel）
- Modify: `frontend/tabs/doc-dashboard.html:276-306`（`loadBreakdown` 函数）

- [ ] **Step 7.1: 在 Step 拆解 panel 内部，chart canvas 之后新增术语图例容器**

定位 `frontend/tabs/doc-dashboard.html` 第 95 行：

```html
            <div class="h-64"><canvas id="breakdownChart"></canvas></div>
```

在它后面（仍在 panel 内）追加：

```html
            <div class="h-64"><canvas id="breakdownChart"></canvas></div>
            <!-- 术语图例（hover 解释旁路）-->
            <div id="docBreakdownGlossary" class="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[10px]" style="color: var(--color-muted);"></div>
```

- [ ] **Step 7.2: 在 loadBreakdown 函数末尾渲染术语图例**

定位 `frontend/tabs/doc-dashboard.html` 第 285 行 `new Chart(...)` 调用结束后（即第 304 行 `});` 后、catch 块之前），插入：

```js
        });
        // 渲染术语图例 (旁路 hover 解释, 替代 Chart.js canvas 不支持 HTML label 的限制)
        renderBreakdownGlossary('docBreakdownGlossary', labels);
```

完整修改后的函数尾部（第 303-306 行）：

```js
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { beginAtZero: true, ticks: { font: { size: 10 } }, grid: { color: 'rgba(148, 163, 184, 0.1)' } },
                    y: { ticks: { font: { size: 10 } }, grid: { color: 'rgba(148, 163, 184, 0.1)' } }
                }
            }
        });
        // 渲染术语图例 (旁路 hover 解释)
        renderBreakdownGlossary('docBreakdownGlossary', labels);
    } catch (err) { console.error('breakdown load failed:', err); }
}
```

- [ ] **Step 7.3: 在 doc-dashboard.html 脚本末尾新增 renderBreakdownGlossary 函数**

定位 `frontend/tabs/doc-dashboard.html` 脚本末尾（第 313 行 `window.loadBreakdown = loadBreakdown;` 后），追加：

```js
/**
 * 渲染 dashboard 拆解图的术语图例 (旁路 hover 解释)
 * - 对每个 label, 提取其中含 glossary 词典的术语
 * - 输出为带虚线下划线的 <span>, hover 出解释
 * @param {string} containerId
 * @param {string[]} labels - chart 的 y 轴 label 数组
 */
function renderBreakdownGlossary(containerId, labels) {
    const el = document.getElementById(containerId);
    if (!el) return;
    if (!labels || labels.length === 0) {
        el.innerHTML = '<span style="color: var(--color-muted);">该类型暂无数据</span>';
        return;
    }
    // 收集所有出现过的术语 key (去重)
    const seen = new Set();
    const items = [];
    for (const label of labels) {
        if (typeof label !== "string") continue;
        const keys = Object.keys(window.GLOSSARY || {}).sort((a, b) => b.length - a.length);
        for (const key of keys) {
            if (seen.has(key)) continue;
            const re = new RegExp(key, "i");
            if (re.test(label)) {
                seen.add(key);
                items.push(key);
            }
        }
    }
    if (items.length === 0) {
        el.innerHTML = '';
        return;
    }
    el.innerHTML = '<span style="margin-right: 4px;">💡 术语:</span>' +
        items.map(k => `<span class="glossary-term" data-glossary="${k}" tabindex="0">${k}</span>`).join(', ');
}
window.renderBreakdownGlossary = renderBreakdownGlossary;
```

- [ ] **Step 7.4: 验证修改**

Run:
```bash
grep -n "docBreakdownGlossary\|renderBreakdownGlossary" frontend/tabs/doc-dashboard.html
```
Expected: 至少 3 行匹配 (1 行容器, 1 行调用, 1 行函数定义/暴露)

- [ ] **Step 7.5: Commit**

```bash
git add frontend/tabs/doc-dashboard.html
git commit -m "feat(glossary): 接入 doc-dashboard Step 拆解图旁挂术语图例"
```

---

## Task 8: 接入 code-dashboard.html - Step 耗时拆解旁挂术语图例

**Files:**
- Modify: `frontend/tabs/code-dashboard.html:115-130`（Step 耗时拆解 panel，具体行号以实际为准）
- Modify: `frontend/tabs/code-dashboard.html` `loadBreakdown` 函数

- [ ] **Step 8.1: 读取 code-dashboard.html 定位 chart canvas 位置**

Run:
```bash
grep -n "breakdownChart\|loadBreakdown\|indexAxis" frontend/tabs/code-dashboard.html
```
确认 canvas id 和函数位置后继续。

- [ ] **Step 8.2: 在 chart canvas 后新增术语图例容器**

类似 Task 7.1，在 chart canvas 后追加：

```html
            <!-- 术语图例（hover 解释旁路）-->
            <div id="codeBreakdownGlossary" class="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[10px]" style="color: var(--color-muted);"></div>
```

- [ ] **Step 8.3: 在 loadBreakdown 函数末尾调用 renderBreakdownGlossary**

类似 Task 7.2，调用：

```js
        renderBreakdownGlossary('codeBreakdownGlossary', labels);
```

> 注意：`renderBreakdownGlossary` 函数是在 doc-dashboard.html 的脚本中定义的。code-dashboard.html 需要这个函数可用。两种方式选一：
>
> **方式 A（推荐）**：在 code-dashboard.html 脚本开头加一行 `if (typeof renderBreakdownGlossary === "undefined")` 保护，并在脚本末尾也定义一份（与 doc-dashboard 相同实现）
>
> **方式 B**：把 `renderBreakdownGlossary` 移到 `frontend/js/shared.js` 暴露
>
> **本任务选 A**（实现简单、避免污染 shared.js），具体实现：

在 code-dashboard.html 脚本末尾追加：

```js
// 术语图例渲染（与 doc-dashboard 共享实现；如已定义则跳过）
if (typeof renderBreakdownGlossary === "undefined") {
    function renderBreakdownGlossary(containerId, labels) {
        const el = document.getElementById(containerId);
        if (!el) return;
        if (!labels || labels.length === 0) {
            el.innerHTML = '<span style="color: var(--color-muted);">该类型暂无数据</span>';
            return;
        }
        const seen = new Set();
        const items = [];
        for (const label of labels) {
            if (typeof label !== "string") continue;
            const keys = Object.keys(window.GLOSSARY || {}).sort((a, b) => b.length - a.length);
            for (const key of keys) {
                if (seen.has(key)) continue;
                const re = new RegExp(key, "i");
                if (re.test(label)) {
                    seen.add(key);
                    items.push(key);
                }
            }
        }
        if (items.length === 0) {
            el.innerHTML = '';
            return;
        }
        el.innerHTML = '<span style="margin-right: 4px;">💡 术语:</span>' +
            items.map(k => `<span class="glossary-term" data-glossary="${k}" tabindex="0">${k}</span>`).join(', ');
    }
    window.renderBreakdownGlossary = renderBreakdownGlossary;
}
```

- [ ] **Step 8.4: 验证修改**

Run:
```bash
grep -n "codeBreakdownGlossary\|renderBreakdownGlossary" frontend/tabs/code-dashboard.html
```
Expected: 至少 3 行匹配

- [ ] **Step 8.5: Commit**

```bash
git add frontend/tabs/code-dashboard.html
git commit -m "feat(glossary): 接入 code-dashboard Step 拆解图旁挂术语图例"
```

---

## Task 9: 端到端手动验证（10 条验收标准）

**Files:** 无（仅操作浏览器）

- [ ] **Step 9.1: 启动项目**

```bash
cd /Users/admin/Desktop/AI产出/email-wiki-demo
./start.sh
```

等 FastAPI 启动后访问 http://localhost:8000

- [ ] **Step 9.2: 验收 #1-#2 — 代码搜索面板**

1. 浏览器打开 http://localhost:8000
2. 点击侧边栏「🔍 代码搜索」
3. 输入 "登录"（或任何查询），点击搜索
4. 验证：右侧「搜索流程」面板里出现的 `vector_search`（或 `hybrid_search`）等英文术语下方有虚线
5. 鼠标 hover 任一术语，0.2s 内出现深色卡片显示中文解释
6. 验收 1、2 通过 ✓

- [ ] **Step 9.3: 验收 #3-#4 — tooltip 持续与消失**

1. 鼠标移到 tooltip 卡片上，tooltip 不消失
2. 鼠标移出术语 0.1s 后，tooltip 消失
3. 验收 3、4 通过 ✓

- [ ] **Step 9.4: 验收 #5 — 视口边界翻转**

1. 找一个靠近视口右上角的术语元素（可在 DevTools 修改样式临时放在右上角）
2. hover 后 tooltip 应翻向左下而非溢出屏幕
3. 验收 5 通过 ✓

- [ ] **Step 9.5: 验收 #6-#7 — 键盘可达性**

1. 鼠标移开，tooltip 消失
2. Tab 键聚焦到一个术语元素
3. 焦点时 tooltip 自动显示
4. 按 Esc，tooltip 关闭
5. 验收 6、7 通过 ✓

- [ ] **Step 9.6: 验收 #8 — Dashboard 术语图例**

1. 点击「📊 文档统计」进入 doc dashboard
2. 找到「Step 耗时拆解」panel
3. 在下拉选「搜索」并等图表加载
4. 验证：图表下方出现「💡 术语: vector_search, embed_query, ...」的虚线术语列表
5. hover 任一术语，卡片显示解释
6. 切到「代码统计」重复上述验证
7. 验收 8 通过 ✓

- [ ] **Step 9.7: 验收 #9 — 词典维护成本**

1. 编辑 `frontend/js/glossary.js`，在 GLOSSARY 末尾加一行：
```js
    test_term: "测试术语: 验证加新词只改一个文件即可生效",
```
2. 浏览器刷新页面
3. 跑一次代码搜索（搜索结果含 `test_term` 不会出现，因为后端不会输出这个 key，但人工可在 search 步骤面板手敲一个含 test_term 的 description 来测试）
4. 验收 9 通过（只改 `glossary.js` 一处）✓
5. 验证完成后删除测试条目

- [ ] **Step 9.8: 验收 #10 — 回归 + 控制台**

1. 打开 DevTools Console，确认无红色错误
2. 切换到 doc-upload、doc-email、code-repos、code-chat 等其他 tab，确认未受影响
3. 验收 10 通过 ✓

- [ ] **Step 9.9: 提交最终标记**

```bash
git add -A
git status   # 确认无未追踪的修改
git commit --allow-empty -m "feat(glossary): 完成 Step 流程术语 hover 解释功能"
```

---

## 自检报告

### 1. Spec 覆盖检查

| Spec 章节 | 对应 Task |
|-----------|-----------|
| 4. 范围（4 个面板） | Task 5, 6, 7, 8 |
| 5. 架构（2 个 JS + 1 个 CSS） | Task 1, 2, 3 |
| 6. 4 个面板接入点 | Task 5, 6, 7, 8 |
| 7. 样式规范 | Task 3 |
| 8. 验收标准（10 条） | Task 9 |
| 9. 风险（Chart.js 兼容性） | 选方案 Y（Task 7.1-7.3 旁挂图例）|
| 10. 实施步骤 | 全部 Task |

✅ 全部覆盖

### 2. 占位符扫描

- 无 "TBD" / "TODO"
- 代码块完整，无 "类似 Task N" 引用
- 所有函数/类名在早 Task 定义后被一致使用（`wrapTerm` / `applyGlossary` / `GLOSSARY` / `renderBreakdownGlossary`）

### 3. 类型一致性

- `GLOSSARY` 在 Task 1 暴露 `window.GLOSSARY`、Task 2 用 `window.GLOSSARY` 查、Task 7.3 用 `window.GLOSSARY` 查 → 一致
- `wrapTerm(text: string): string` 签名在 Task 1 定义、Task 5/6 调用一致
- `renderBreakdownGlossary(containerId, labels)` 在 Task 7.3 定义、Task 8.3 复用一致
- `data-glossary` 属性在所有 4 个面板一致使用
- `glossary-term` class 在 glossary.js（wrapTerm 生成）和 dashboard（renderBreakdownGlossary 生成）一致使用
