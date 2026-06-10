# Step 流程术语 Hover 解释功能 - 设计文档

> 日期：2026-06-10
> 状态：已批准，待写实施计划
> 项目：email-wiki-demo

## 1. 背景与目标

email-wiki-demo 的"耗时拆解"和"流程步骤"面板中频繁出现英文术语（`hybrid_search`、`rrf_fusion`、FTS5、MiMo 等），用户和初次接触项目的开发者很难理解其含义。需要在术语首次出现处加鼠标 hover 解释（中文 tooltip），降低理解门槛。

**目标**：在 4 个主要面板中，对出现的英文术语/技术名词提供轻量的 hover 解释能力，零后端改动、术语集中维护、未来扩展只需改一个文件。

## 2. 范围

### 2.1 包含

| 面板 | 文件 | 触发方式 |
|------|------|---------|
| 代码搜索 - 搜索流程面板 | `frontend/tabs/code-search.html` | 渲染 `step.description`/`step.name` 时包裹术语 |
| 代码搜索 - 翻译流程面板 | `frontend/tabs/code-search.html` | 翻译方式 label + description 包裹 |
| 文档库 Dashboard - Step 耗时拆解 | `frontend/tabs/doc-dashboard.html` | Chart.js y 轴 label 渲染时包裹 |
| 代码库 Dashboard - Step 耗时拆解 | `frontend/tabs/code-dashboard.html` | 同上 |

### 2.2 不包含（YAGNI）

- 文档上传/邮件导入流程面板（`doc-upload.html`、`doc-email.html`）— 后端已传中文 description，无英文术语
- LanceDB 教学演示面板（`doc-lancedb.html`、`code-lancedb.html`）— 范围外
- 仓库列表、文档列表中的英文技术名词（不在流程面板）
- 用户自定义术语、术语搜索面板
- 国际化 i18n（中文固定）

## 3. 架构

```
glossary.js (新增)               ← 术语 SSOT
   ├─ export const GLOSSARY      ← 20+ 条术语映射
   ├─ wrapTerm(text)             ← 字符串级包装
   └─ applyGlossary(rootEl)      ← DOM 节点级批量包装

glossary-tooltip.js (新增)       ← Tooltip 渲染与交互
   ├─ 单例 tooltip DOM
   ├─ mouseenter/mouseleave 监听 [data-glossary]
   ├─ focus/blur 键盘可达
   ├─ Esc 关闭
   └─ 视口边界检测 + 翻转定位

theme.css (新增样式)             ← 暗色风卡片样式
   ├─ .glossary-term             ← 虚线下划线 + 鼠标手型
   └─ .glossary-tooltip          ← 深色卡片 + 阴影 + 三角

4 个面板 (小幅改动)              ← 在术语渲染处接入
```

## 4. 数据设计

### 4.1 词典结构

`frontend/js/glossary.js`：

```js
export const GLOSSARY = {
  // 搜索流程
  hybrid_search:    "混合搜索: 同时跑向量 + FTS5 + 符号三路, 用 RRF 融合排序",
  vector_search:    "向量搜索: 用 Embedding 模型把查询转成向量, 按余弦相似度找最相关的代码片段",
  keyword_search:   "关键词搜索: 在 SQLite FTS5 全文索引中精确匹配关键词 (支持中文原文)",
  embed_query:      "生成查询向量: 把用户输入转成 Embedding 模型输出, 用于相似度搜索",
  rrf_fusion:       "RRF 融合 (Reciprocal Rank Fusion): 多路结果按排名倒数加权融合",
  query_translate:  "查询翻译: 把中文查询自动翻译为英文代码关键词, 提高英文代码库匹配率",
  lanceDB_search:   "LanceDB 向量检索: 在向量数据库中执行余弦距离计算, 返回最相似的文档块",

  // 调用链追踪
  trace_search:     "搜索起始符号: 用混合搜索定位用户指定的符号出现在哪些文件",
  trace_chain:      "追踪调用链: 从起始符号沿调用关系多跳追踪 (向上找调用方, 向下找被调方)",

  // 问答
  llm_generate:     "LLM 生成回答: 把检索到的相关片段作为上下文, 调用大模型生成自然语言答案",

  // 翻译流程
  translation_cache:   "翻译缓存命中: 直接从 data/translation_cache.json 读取已有翻译结果 (0ms)",
  llm_translate:       "LLM 翻译: 用 MiMo 等大模型做中英翻译, 翻译质量最高",
  mymemory_translate:  "MyMemory API: 调用免费在线翻译 API 做中英翻译 (日 5000 字符限额)",
  dict_translate:      "本地词典翻译: 在内置 TERM_MAP 中匹配中文词, 无网络依赖",
  fallback:            "翻译降级: 所有翻译方式都失败时, 保留原文让 FTS5 搜索中文 content",

  // 通用技术名词
  RRF:          "Reciprocal Rank Fusion: 多路结果融合排序算法",
  FTS5:         "SQLite 全文搜索引擎 v5, 支持快速关键词匹配",
  LanceDB:      "基于 Lance 列式格式的向量数据库, 存 Embedding 向量",
  "bge-small-en": "BAAI/bge-small-en-v1.5 英文 Embedding 模型 (384 维)",
  MiMo:         "项目默认配置的大模型 (见 llm_client.py), 用于翻译和问答",
  MyMemory:     "MyMemory 免费在线翻译 API, 翻译失败时的备用方案",
};
```

### 4.2 API 设计

```js
// glossary.js 导出
export const GLOSSARY = { /* ... */ };

// 字符串级包装: 把 text 中出现的所有术语用 <span data-glossary="key"> 包起来
// - 按 key 长度倒序匹配, 避免短词截断长词
// - 大小写不敏感 (RRF / rrf 都能匹配)
// - 跳过已包过的 span
export function wrapTerm(text: string): string;

// DOM 节点级批量包装: 扫描 rootEl 内所有 textNode, 替换为包裹后的节点
// - 跳过 <script> / <style> 标签
// - 跳过已包过的 [data-glossary] 元素
export function applyGlossary(rootEl: HTMLElement): void;
```

## 5. Tooltip 行为

| 维度 | 设计 |
|------|------|
| **触发元素** | 任意带 `[data-glossary]` 属性的元素（class `.glossary-term`） |
| **鼠标交互** | `mouseenter` 0.15s 防抖后显示；`mouseleave`（含移入 tooltip）0.1s 延迟隐藏 |
| **键盘可达** | `tabindex="0"`，focus 时显示，Esc 关闭 |
| **位置策略** | 目标元素上方居中，距离 8px；超出视口右/下边界时翻向下/左/右 |
| **样式** | 深色卡（`--color-bg-elevated`），圆角 8px，阴影 + 顶部小三角；`max-width: 320px` 自动换行 |
| **单例** | 全局只一个 tooltip DOM，mousemove 时只重新定位不重建 |
| **事件委托** | 在 `document` 上监听，匹配 `[data-glossary]`，避免每条都绑监听器 |

## 6. 4 个面板接入点（精确到函数/位置）

### 6.1 `frontend/tabs/code-search.html` - 搜索流程面板

**函数**：`codeRenderSearchStep(step)` 约 L265

**当前逻辑**：直接 `el.textContent = step.description || step.name`

**改法**：判断是否含英文术语，是则用 `wrapTerm()` 生成 HTML 并 `innerHTML` 写入；纯中文仍用 `textContent`

### 6.2 `frontend/tabs/code-search.html` - 翻译流程面板

**函数**：`codeRenderTranslationStep(step)` 约 L233

**当前逻辑**：使用硬编码 `labelMap` 把 `cache/llm/mymemory/dict/fallback` 映射为中文

**改法**：labelMap 仍用中文（保证显示稳定），但 description 字段（如"缓存命中 (0ms)"）里的 `cache` 等术语走 `wrapTerm` 包裹

### 6.3 `frontend/tabs/doc-dashboard.html` - Step 耗时拆解

**位置**：Chart.js 初始化处，bar chart y 轴 labels

**改法**：渲染 chart 前对 labels 数组做 `wrapTerm` 转换。Chart.js 支持 HTML 数组作为 label（需要设置 `renderText` 行为或用 plugin）

**注意**：Chart.js 默认会把 HTML 当文本渲染，需查其 API 是否支持 HTML label；若不支持，改为 hover 时用 tooltip plugin 显示中文解释

### 6.4 `frontend/tabs/code-dashboard.html` - Step 耗时拆解

**位置**：同 6.3

**改法**：同 6.3

### 6.5 Chart.js 兼容性预案

Chart.js v3+ 的 `scale.label` 默认对字符串做纯文本渲染（不支持 HTML 标签）。两个备选方案：

- **方案 X（推荐）**：使用 `chartjs-plugin-datalabels` 之类的 plugin，或自定义 plugin 在 `afterDatasetsDraw` 钩子中拿到 y 轴 label 元素后注入 HTML。简单做法：直接拦截 Chart.js 内部 tick 回调，在 `ticks.callback` 中返回 wrapTerm 后的字符串（含 `<span>`），然后在 chart option 里设置 `font`/HTML 渲染。
- **方案 Y（回退）**：如果方案 X 调研后发现改动较大，则**在图表旁额外渲染一份"术语图例"列表**（与图表 y 轴 label 一一对应），术语列表用普通 DOM + glossary-tooltip.js 处理，hover 解释靠这个列表承担。

**实施时优先尝试 X，遇到阻塞再回退到 Y**。

## 7. 样式规范（`css/theme.css` 新增）

```css
.glossary-term {
  border-bottom: 1px dashed var(--color-primary);
  cursor: help;
  color: inherit;
}
.glossary-term:focus {
  outline: 1px dotted var(--color-primary);
  outline-offset: 2px;
}

.glossary-tooltip {
  position: fixed;
  z-index: 9999;
  max-width: 320px;
  padding: 8px 12px;
  background: var(--color-bg-elevated);
  color: var(--color-text);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.5;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
  pointer-events: auto;       /* 允许 hover 到 tooltip 自身 */
  white-space: pre-wrap;
  opacity: 0;
  transition: opacity 0.12s;
}
.glossary-tooltip.is-visible {
  opacity: 1;
}
.glossary-tooltip::after {
  content: "";
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 6px solid transparent;
  border-top-color: var(--color-bg-elevated);
}
.glossary-tooltip.is-bottom::after {
  top: auto;
  bottom: 100%;
  border-top-color: transparent;
  border-bottom-color: var(--color-bg-elevated);
}
```

## 8. 验收标准

| # | 验收项 | 验证方式 |
|---|--------|---------|
| 1 | 跑一次代码搜索，搜索流程面板中出现的 `hybrid_search`、`vector_search` 等英文术语下方有虚线 | 视觉确认 |
| 2 | 鼠标 hover 任一术语，0.2s 内出现深色卡片显示中文解释 | 计时确认 |
| 3 | 移动鼠标到 tooltip 自身，tooltip 不消失（可读完整内容） | 交互确认 |
| 4 | 鼠标移出术语 0.1s 后 tooltip 消失 | 交互确认 |
| 5 | 鼠标 hover 视口边缘术语（如右上角）时，tooltip 翻转不溢出 | 边界用例确认 |
| 6 | Esc 键能关闭当前显示的 tooltip | 键盘确认 |
| 7 | Tab 键能聚焦到术语元素，focus 时也显示 tooltip | 键盘可达性确认 |
| 8 | Dashboard 的 Step 耗时拆解图表 y 轴 label 上术语带虚线，hover 出解释 | 视觉 + 交互 |
| 9 | 词典加新术语只改 `glossary.js` 一处，刷新页面即可生效 | 改一处验证（手动）|
| 10 | 浏览器控制台无报错；4 个面板外的术语不受影响 | 控制台 + 回归 |

## 9. 风险与回退

| 风险 | 应对 |
|------|------|
| Chart.js 不直接支持 HTML label | 回退方案：用 Chart.js plugin 在 afterDraw 钩子中绘制自定义 tooltip；或先在 chart 旁加一个隐藏的 DOM 列表展示同名术语 hover 解释 |
| `wrapTerm` 误伤（如 `cache` 出现在用户内容里） | 关键优化：词边界正则 + 大小写不敏感；只在 `step.description` / `step.name` / chart label 中调用，不扫描整个页面 |
| tooltip 性能问题（mousemove 频触发） | 用 `requestAnimationFrame` 节流；不重建 DOM，只更新 `transform` |
| 多术语同行密集 | 物理位置上 tooltip 单例避免重叠，hover 哪个就显示哪个 |

## 10. 实施步骤概览（具体 plan 见 writing-plans）

1. 新建 `frontend/js/glossary.js`（含 GLOSSARY + wrapTerm + applyGlossary）
2. 新建 `frontend/js/glossary-tooltip.js`（含事件委托 + 定位 + 显隐）
3. 改 `frontend/css/theme.css`（新增 .glossary-term / .glossary-tooltip 样式）
4. 改 `frontend/tabs/code-search.html`（搜索流程 + 翻译流程面板接入）
5. 改 `frontend/tabs/doc-dashboard.html`（Chart.js label 接入）
6. 改 `frontend/tabs/code-dashboard.html`（Chart.js label 接入）
7. 各 tab HTML 引入 `glossary.js` + `glossary-tooltip.js`（按现有引入方式）
8. 手动验证 10 条验收标准
