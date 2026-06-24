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
        const re = new RegExp(`(${escapeRegExp(key)})`, "gi");
        result = result.replace(re, (m) => {
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
