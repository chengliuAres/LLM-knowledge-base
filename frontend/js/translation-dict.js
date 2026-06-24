/**
 * 翻译词典模态框 — 业务逻辑 + 分类 tab 切换
 *
 * 由来：模态框在 index.html body 直属（避免被 .tab-page fadeIn 干扰），
 * 配套的 JS 必须全局可用、router 懒加载 code-dashboard.html 之前就已就绪。
 *
 * 依赖（由 shared.js / index.html 提前注入）：
 * - window.escapeHtml / window.showToast（shared.js）
 * - #translation-dict-modal 及其子节点（index.html）
 *
 * 调用入口（由 index.html 内联 onclick 触发）：
 * - openTranslationDictModal() / closeTranslationDictModal()
 * - addDictTerm() / editDictTerm(cn) / removeDictTerm(cn)
 * - saveTranslationDict() / resetTranslationDict() / refreshTranslationDict()
 * - openTranslationDictInFinder() / filterDictTerms(keyword)
 * - switchDictTab(name)  ← 弹窗内 tabs 切换
 */

// ── 分类定义 ────────────────────────────────────────────────
const DICT_CATEGORIES = [
    '全部', '认证/账号', '邮件核心', '操作', 'UI组件', 'UI属性/布局',
    'UI状态/交互', '移动端', '数据/状态', '网络/存储', '状态', '其他'
];

// ── 状态 ────────────────────────────────────────────────────
let _dictTerms = {};        // {cn: {translations: [...], category: "..."}}
let _dictDraft = {};        // 编辑中的草稿
let _dictActiveTab = '全部';
let _dictSearchKeyword = '';
let _dictEditingCn = null;  // 正在编辑的词条

// ── 打开/关闭 ───────────────────────────────────────────────

async function openTranslationDictModal() {
    document.getElementById('translation-dict-modal').classList.remove('hidden');
    _dictActiveTab = '全部';
    _dictSearchKeyword = '';
    _dictEditingCn = null;
    document.getElementById('dict-search-input').value = '';
    await loadTranslationDict();
    _updateDictTabButtons();
}

function closeTranslationDictModal() {
    document.getElementById('translation-dict-modal').classList.add('hidden');
    _dictEditingCn = null;
}

// ── 加载词典 ────────────────────────────────────────────────

async function loadTranslationDict() {
    try {
        const res = await fetch('/api/code/translation-dict');
        if (!res.ok) throw new Error('加载词典失败');
        const data = await res.json();
        _dictTerms = data.terms || {};
        _dictDraft = JSON.parse(JSON.stringify(_dictTerms)); // deep copy
        _renderDictTable();
        _renderDictCategoryTabs();
        _updateDictStats();
    } catch (e) {
        showToast('加载翻译词典失败: ' + e.message, 'error');
    }
}

// ── 自动同步到后端（静默，不打断用户操作）─────────────────────

async function _autoSaveToBackend() {
    try {
        const res = await fetch('/api/code/translation-dict', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({terms: _dictDraft}),
        });
        if (res.ok) {
            _dictTerms = JSON.parse(JSON.stringify(_dictDraft));
        }
    } catch (e) {
        console.warn('[translation-dict] 自动保存失败:', e.message);
    }
}

// ── 保存词典 ────────────────────────────────────────────────

async function saveTranslationDict() {
    try {
        const res = await fetch('/api/code/translation-dict', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({terms: _dictDraft}),
        });
        if (!res.ok) throw new Error('保存失败');
        const data = await res.json();
        _dictTerms = JSON.parse(JSON.stringify(_dictDraft));
        showToast(data.message || '已保存', 'success');
        _updateDictStats();
    } catch (e) {
        showToast('保存失败: ' + e.message, 'error');
    }
}

// ── 刷新 ────────────────────────────────────────────────────

async function refreshTranslationDict() {
    const btn = document.getElementById('dict-refresh-btn');
    if (!btn) return;
    const orig = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '刷新中...';
    try {
        await loadTranslationDict();
    } finally {
        btn.disabled = false;
        btn.innerHTML = orig;
    }
}

// ── 恢复默认 ────────────────────────────────────────────────

async function resetTranslationDict() {
    if (!confirm('确定要恢复默认翻译词典吗？当前修改会丢失。')) return;
    try {
        const res = await fetch('/api/code/translation-dict/reload', {method: 'POST'});
        if (!res.ok) throw new Error('重置失败');
        await loadTranslationDict();
        showToast('已恢复默认词典', 'success');
    } catch (e) {
        showToast('重置失败: ' + e.message, 'error');
    }
}

// ── Finder ──────────────────────────────────────────────────

async function openTranslationDictInFinder() {
    try {
        const res = await fetch('/api/code/translation-dict/open-finder', {method: 'POST'});
        if (!res.ok) throw new Error('打开 Finder 失败');
    } catch (e) {
        showToast('打开 Finder 失败: ' + e.message, 'error');
    }
}

// ── 添加词条 ────────────────────────────────────────────────

function addDictTerm() {
    const cnInput = document.getElementById('dict-add-cn');
    const enInput = document.getElementById('dict-add-en');
    const catSelect = document.getElementById('dict-add-category');

    const cn = cnInput.value.trim();
    const enStr = enInput.value.trim();
    const category = catSelect.value;

    if (!cn) return showToast('请输入中文词', 'warning');
    if (!enStr) return showToast('请输入英文翻译', 'warning');

    // 解析英文翻译（逗号分隔）
    const translations = enStr.split(/[,，]/).map(s => s.trim()).filter(s => s.length > 0);
    if (translations.length === 0) return showToast('请输入有效的英文翻译', 'warning');

    if (_dictDraft[cn]) return showToast('该词条已存在，请使用编辑功能', 'warning');

    _dictDraft[cn] = {translations, category};
    cnInput.value = '';
    enInput.value = '';
    _renderDictTable();
    _updateDictStats();
    showToast(`已添加: ${cn}`, 'success');
    _autoSaveToBackend();
}

// ── 编辑词条 ────────────────────────────────────────────────

function editDictTerm(cn) {
    _dictEditingCn = cn;
    _renderDictTable();
}

function cancelEditDictTerm() {
    _dictEditingCn = null;
    _renderDictTable();
}

function saveEditDictTerm(cn) {
    const enInput = document.getElementById(`dict-edit-en-${cn}`);
    const catSelect = document.getElementById(`dict-edit-cat-${cn}`);

    if (!enInput || !catSelect) return;

    const enStr = enInput.value.trim();
    const category = catSelect.value;

    if (!enStr) return showToast('英文翻译不能为空', 'warning');

    const translations = enStr.split(/[,，]/).map(s => s.trim()).filter(s => s.length > 0);
    if (translations.length === 0) return showToast('请输入有效的英文翻译', 'warning');

    _dictDraft[cn] = {translations, category};
    _dictEditingCn = null;
    _renderDictTable();
    _updateDictStats();
    showToast(`已更新: ${cn}`, 'success');
    // 同步到后端，确保翻译器立即生效
    _autoSaveToBackend();
}

// ── 删除词条 ────────────────────────────────────────────────

function removeDictTerm(cn) {
    if (!confirm(`确定要删除词条「${cn}」吗？`)) return;
    delete _dictDraft[cn];
    if (_dictEditingCn === cn) _dictEditingCn = null;
    _renderDictTable();
    _updateDictStats();
    showToast(`已删除: ${cn}`, 'success');
    _autoSaveToBackend();
}

// ── 搜索过滤 ────────────────────────────────────────────────

function filterDictTerms(keyword) {
    _dictSearchKeyword = keyword.trim().toLowerCase();
    _renderDictTable();
}

// ── 分类 tab 切换 ────────────────────────────────────────────

function switchDictTab(name) {
    _dictActiveTab = name;
    _dictEditingCn = null;
    _updateDictTabButtons();
    _renderDictTable();
}

function _updateDictTabButtons() {
    document.querySelectorAll('#translation-dict-modal .dict-tab-btn').forEach(b => {
        b.classList.toggle('dict-tab-btn-active', b.dataset.tab === _dictActiveTab);
    });
}

// ── 渲染分类 tabs ────────────────────────────────────────────

function _renderDictCategoryTabs() {
    const container = document.getElementById('dict-category-tabs');
    if (!container) return;

    // 统计每个分类的词条数
    const counts = {'全部': Object.keys(_dictDraft).length};
    DICT_CATEGORIES.slice(1).forEach(cat => {
        counts[cat] = 0;
    });
    Object.values(_dictDraft).forEach(info => {
        const cat = info.category || '其他';
        if (counts[cat] !== undefined) counts[cat]++;
        else counts[cat] = 1;
    });

    container.innerHTML = DICT_CATEGORIES.map(cat => {
        const count = counts[cat] || 0;
        return `<button type="button" data-tab="${cat}" onclick="switchDictTab('${cat}')"
                    class="dict-tab-btn ${cat === _dictActiveTab ? 'dict-tab-btn-active' : ''} px-3 py-1.5 text-xs font-medium whitespace-nowrap">
                    ${cat} <span class="opacity-60">(${count})</span>
                </button>`;
    }).join('');
}

// ── 渲染表格 ────────────────────────────────────────────────

function _renderDictTable() {
    const tbody = document.getElementById('dict-terms-body');
    if (!tbody) return;

    // 过滤 + 分类
    let entries = Object.entries(_dictDraft);

    // 分类过滤
    if (_dictActiveTab !== '全部') {
        entries = entries.filter(([cn, info]) => (info.category || '其他') === _dictActiveTab);
    }

    // 搜索过滤
    if (_dictSearchKeyword) {
        entries = entries.filter(([cn, info]) => {
            const cnMatch = cn.toLowerCase().includes(_dictSearchKeyword);
            const enMatch = info.translations.some(t => t.toLowerCase().includes(_dictSearchKeyword));
            return cnMatch || enMatch;
        });
    }

    // 排序：按中文拼音
    entries.sort((a, b) => a[0].localeCompare(b[0], 'zh-CN'));

    if (entries.length === 0) {
        tbody.innerHTML = `<tr><td colspan="4" class="text-center py-6" style="color: var(--color-muted);">
            ${_dictSearchKeyword ? '无匹配结果' : '暂无词条'}
        </td></tr>`;
        return;
    }

    tbody.innerHTML = entries.map(([cn, info]) => {
        const isEditing = _dictEditingCn === cn;
        const translations = info.translations || [];
        const category = info.category || '其他';

        if (isEditing) {
            // 编辑模式
            return `<tr style="border-top: 1px solid var(--color-border); background: rgba(168, 85, 247, 0.08);">
                <td class="py-2 px-2 text-xs font-medium" style="color: var(--color-foreground);">
                    ${escapeHtml(cn)}
                </td>
                <td class="py-2 px-2">
                    <input id="dict-edit-en-${escapeHtml(cn)}" type="text" value="${escapeHtml(translations.join(', '))}"
                           class="input text-xs w-full" style="padding: 4px 8px;">
                </td>
                <td class="py-2 px-2">
                    <select id="dict-edit-cat-${escapeHtml(cn)}" class="input text-xs" style="padding: 4px 8px; width: auto;">
                        ${DICT_CATEGORIES.slice(1).map(c =>
                            `<option value="${c}" ${c === category ? 'selected' : ''}>${c}</option>`
                        ).join('')}
                    </select>
                </td>
                <td class="py-2 px-2 text-right whitespace-nowrap">
                    <button onclick="saveEditDictTerm('${escapeHtml(cn)}')" class="btn btn-accent text-xs py-0.5 px-2">保存</button>
                    <button onclick="cancelEditDictTerm()" class="btn btn-secondary text-xs py-0.5 px-2 ml-1">取消</button>
                </td>
            </tr>`;
        }

        // 显示模式
        const enHtml = translations.map(t => {
            // 高亮搜索关键词
            if (_dictSearchKeyword && t.toLowerCase().includes(_dictSearchKeyword)) {
                const idx = t.toLowerCase().indexOf(_dictSearchKeyword);
                const before = t.substring(0, idx);
                const match = t.substring(idx, idx + _dictSearchKeyword.length);
                const after = t.substring(idx + _dictSearchKeyword.length);
                return `<span class="px-1 py-0.5 rounded mr-1" style="background: rgba(168, 85, 247, 0.15); color: #C4B5FD;">${escapeHtml(before)}<mark style="background: rgba(251, 191, 36, 0.4); color: inherit; border-radius: 2px;">${escapeHtml(match)}</mark>${escapeHtml(after)}</span>`;
            }
            return `<span class="px-1 py-0.5 rounded mr-1" style="background: rgba(168, 85, 247, 0.15); color: #C4B5FD;">${escapeHtml(t)}</span>`;
        }).join('');

        // 中文高亮
        let cnHtml = escapeHtml(cn);
        if (_dictSearchKeyword && cn.toLowerCase().includes(_dictSearchKeyword)) {
            const idx = cn.toLowerCase().indexOf(_dictSearchKeyword);
            const before = cn.substring(0, idx);
            const match = cn.substring(idx, idx + _dictSearchKeyword.length);
            const after = cn.substring(idx + _dictSearchKeyword.length);
            cnHtml = `${escapeHtml(before)}<mark style="background: rgba(251, 191, 36, 0.4); color: inherit; border-radius: 2px;">${escapeHtml(match)}</mark>${escapeHtml(after)}`;
        }

        return `<tr style="border-top: 1px solid var(--color-border);">
            <td class="py-2 px-2 text-xs font-medium" style="color: var(--color-foreground);">${cnHtml}</td>
            <td class="py-2 px-2">${enHtml}</td>
            <td class="py-2 px-2 text-xs" style="color: var(--color-muted);">${escapeHtml(category)}</td>
            <td class="py-2 px-2 text-right whitespace-nowrap">
                <button onclick="editDictTerm('${escapeHtml(cn)}')" class="btn btn-secondary text-xs py-0.5 px-2">编辑</button>
                <button onclick="removeDictTerm('${escapeHtml(cn)}')" class="btn btn-danger text-xs py-0.5 px-2 ml-1">删除</button>
            </td>
        </tr>`;
    }).join('');
}

// ── 统计更新 ────────────────────────────────────────────────

function _updateDictStats() {
    const el = document.getElementById('dict-stats');
    if (!el) return;
    const total = Object.keys(_dictDraft).length;
    const categories = new Set(Object.values(_dictDraft).map(i => i.category || '其他'));
    el.textContent = `共 ${total} 条 · ${categories.size} 个分类`;
}

// ── 全局暴露 ────────────────────────────────────────────────
window.openTranslationDictModal = openTranslationDictModal;
window.closeTranslationDictModal = closeTranslationDictModal;
window.refreshTranslationDict = refreshTranslationDict;
window.saveTranslationDict = saveTranslationDict;
window.resetTranslationDict = resetTranslationDict;
window.openTranslationDictInFinder = openTranslationDictInFinder;
window.addDictTerm = addDictTerm;
window.editDictTerm = editDictTerm;
window.cancelEditDictTerm = cancelEditDictTerm;
window.saveEditDictTerm = saveEditDictTerm;
window.removeDictTerm = removeDictTerm;
window.filterDictTerms = filterDictTerms;
window.switchDictTab = switchDictTab;
