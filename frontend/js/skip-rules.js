/**
 * 排除规则模态框 — 业务逻辑 + tab 切换
 *
 * 由来：模态框在 index.html body 直属（避免被 .tab-page fadeIn 干扰），
 * 配套的 JS 必须全局可用、router 懒加载 code-repos.html 之前就已就绪。
 *
 * 依赖（由 shared.js / index.html 提前注入）：
 * - window.escapeHtml / window.showToast（shared.js）
 * - #skip-rules-modal 及其子节点（index.html）
 *
 * 调用入口（由 index.html 内联 onclick 触发）：
 * - openSkipRulesModal() / closeSkipRulesModal()
 * - addSkipRule(type) / removeSkipRule(type, idx)
 * - saveSkipRules() / resetSkipRules() / refreshSkipRules()
 * - openSkipRulesInFinder() / toggleGitignoreAll(checked)
 * - switchSkipTab(name)  ← 弹窗内 tabs 切换
 */

const SKIP_DIR_CATEGORIES = ['版本控制', '依赖', '构建产物', 'IDE', '资源', '缓存', '虚拟环境', '第三方', '自定义'];
const SKIP_EXT_CATEGORIES = ['图片', '字体', 'iOS/Mac资源', 'Android资源', '配置/数据', '自定义'];

let _skipRulesDraft = {dirs: [], exts: []};
let _gitignoreDraft = [];

function _getCurrentRepoPath() {
    const el = document.getElementById('codeRepoPath');
    return el ? el.value.trim() : '';
}

async function openSkipRulesModal() {
    document.getElementById('skip-rules-modal').classList.remove('hidden');
    await loadSkipRules();
    await loadPreview();
}

function closeSkipRulesModal() {
    document.getElementById('skip-rules-modal').classList.add('hidden');
}

async function loadPreview() {
    const bar = document.getElementById('skip-rules-preview-bar');
    if (!bar) return;
    bar.innerHTML = '⏳ 计算中...';
    const repoPath = _getCurrentRepoPath();
    if (!repoPath) {
        bar.innerHTML = '📊 预览：请先填写仓库路径';
        return;
    }
    try {
        const res = await fetch(`/api/code/skip-rules/preview?repo_path=${encodeURIComponent(repoPath)}`, {method: 'POST'});
        const data = await res.json();
        const filtered = data.filtered_files ?? 0;
        const total = data.total_files ?? 0;
        const skipped = data.skipped_files ?? 0;
        bar.innerHTML = `📊 预览：将扫描 <strong style="color: #93C5FD;">${filtered}</strong> / ${total} 个文件（排除 <strong style="color: #FCA5A5;">${skipped}</strong> 个）`;
    } catch (e) {
        bar.innerHTML = `<span style="color: var(--color-destructive);">预览加载失败: ${escapeHtml(e.message)}</span>`;
    }
}

async function refreshSkipRules() {
    const btn = document.getElementById('skip-rules-refresh-btn');
    if (!btn) return;
    const orig = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '刷新中...';
    try {
        await loadSkipRules();
        await loadPreview();
    } finally {
        btn.disabled = false;
        btn.innerHTML = orig;
    }
}

async function loadSkipRules() {
    try {
        const res = await fetch('/api/code/skip-rules');
        if (!res.ok) throw new Error('加载规则失败');
        const data = await res.json();
        _skipRulesDraft = {
            dirs: (data.skip_dirs || []).map(d => ({name: d.name, category: d.category})),
            exts: (data.skip_exts || []).map(d => ({name: d.name, category: d.category})),
        };
        renderSkipTable('skip-dirs-body', _skipRulesDraft.dirs, 'dirs');
        renderSkipTable('skip-exts-body', _skipRulesDraft.exts, 'exts');
        await loadGitignoreDirs(data.gitignore_selections || []);
    } catch (e) {
        showToast('加载排除规则失败: ' + e.message, 'error');
    }
}

async function loadGitignoreDirs(savedSelections) {
    const body = document.getElementById('gitignore-dirs-body');
    const selectAll = document.getElementById('gitignore-select-all');
    const repoPath = _getCurrentRepoPath();
    if (!repoPath) {
        body.innerHTML = '<div style="color: var(--color-muted);">请先在主页填写仓库路径</div>';
        selectAll.checked = false;
        selectAll.disabled = true;
        _gitignoreDraft = [];
        return;
    }
    try {
        const res = await fetch(`/api/code/gitignore-dirs?repo_path=${encodeURIComponent(repoPath)}`);
        if (!res.ok) throw new Error('加载 .gitignore 失败');
        const data = await res.json();
        const dirs = data.dirs || [];
        if (!dirs.length) {
            body.innerHTML = '<div style="color: var(--color-muted);">未找到 .gitignore 或无目录条目</div>';
            selectAll.checked = false;
            selectAll.disabled = true;
            _gitignoreDraft = [];
            return;
        }
        selectAll.disabled = false;
        const savedMap = new Map((savedSelections || []).map(s => [s.name, s.selected !== false]));
        _gitignoreDraft = dirs.map(name => ({
            name,
            selected: savedSelections && savedSelections.length ? (savedMap.get(name) !== false) : true,
        }));
        renderGitignoreDirs();
    } catch (e) {
        body.innerHTML = `<div style="color: var(--color-destructive);">${escapeHtml(e.message)}</div>`;
        _gitignoreDraft = [];
    }
}

function renderGitignoreDirs() {
    const body = document.getElementById('gitignore-dirs-body');
    if (!_gitignoreDraft.length) {
        body.innerHTML = '<div style="color: var(--color-muted);">未找到 .gitignore 或无目录条目</div>';
        return;
    }
    body.innerHTML = _gitignoreDraft.map((it, idx) => `
        <label class="inline-flex items-center gap-1.5 mr-3 mb-1.5 cursor-pointer">
            <input type="checkbox" ${it.selected ? 'checked' : ''} onchange="_gitignoreDraft[${idx}].selected = this.checked; _autoSaveSkipRules();" class="accent-green-600">
            <span style="font-family: var(--font-mono); font-size: 12px; color: var(--color-foreground);">${escapeHtml(it.name)}</span>
        </label>
    `).join('');
    const allChecked = _gitignoreDraft.every(it => it.selected);
    const selectAll = document.getElementById('gitignore-select-all');
    if (selectAll) selectAll.checked = allChecked;
}

function toggleGitignoreAll(checked) {
    _gitignoreDraft.forEach(it => it.selected = checked);
    renderGitignoreDirs();
    _autoSaveSkipRules();
}

function renderSkipTable(containerId, items, type) {
    const tbody = document.getElementById(containerId);
    if (!items.length) {
        tbody.innerHTML = `<tr><td colspan="3" class="text-center py-3" style="color: var(--color-muted); font-size: 12px;">暂无规则</td></tr>`;
        return;
    }
    const grouped = {};
    items.forEach((it, idx) => {
        if (!grouped[it.category]) grouped[it.category] = [];
        grouped[it.category].push({...it, _idx: idx});
    });
    const sortedCats = Object.keys(grouped).sort();
    tbody.innerHTML = sortedCats.map(cat => {
        const rows = grouped[cat]
            .slice()
            .sort((a, b) => a.name.localeCompare(b.name))
            .map(it => `
            <tr style="border-top: 1px solid var(--color-border);">
                <td class="py-1.5 px-2 text-xs" style="font-family: var(--font-mono); color: var(--color-foreground);">${escapeHtml(it.name)}</td>
                <td class="py-1.5 px-2 text-xs" style="color: var(--color-muted);">${escapeHtml(it.category)}</td>
                <td class="py-1.5 px-2 text-right">
                    <button onclick="removeSkipRule('${type}', ${it._idx})" class="btn btn-danger text-xs py-0.5 px-2">删除</button>
                </td>
            </tr>`).join('');
        return `
            <tr style="background: rgba(255,255,255,0.04);">
                <td colspan="3" class="py-1 px-2" style="font-size: 11px; font-weight: 600; color: var(--color-muted); text-transform: uppercase; letter-spacing: 0.05em;">${escapeHtml(cat)} <span style="font-weight: 400;">(${grouped[cat].length})</span></td>
            </tr>
            ${rows}
        `;
    }).join('');
}

function addSkipRule(type) {
    const inputId = type === 'dirs' ? 'skip-dir-input' : 'skip-ext-input';
    const selectId = type === 'dirs' ? 'skip-dir-category' : 'skip-ext-category';
    const name = document.getElementById(inputId).value.trim();
    const category = document.getElementById(selectId).value;
    if (!name) return showToast('请输入规则名称', 'warning');
    if (name.includes('/')) return showToast('目录名/扩展名不能包含 / 字符', 'warning');
    const arr = type === 'dirs' ? _skipRulesDraft.dirs : _skipRulesDraft.exts;
    if (arr.some(it => it.name === name)) return showToast('该规则已存在', 'warning');
    arr.push({name, category});
    document.getElementById(inputId).value = '';
    renderSkipTable(type === 'dirs' ? 'skip-dirs-body' : 'skip-exts-body', arr, type);
    _autoSaveSkipRules();
}

function removeSkipRule(type, index) {
    const arr = type === 'dirs' ? _skipRulesDraft.dirs : _skipRulesDraft.exts;
    arr.splice(index, 1);
    renderSkipTable(type === 'dirs' ? 'skip-dirs-body' : 'skip-exts-body', arr, type);
    _autoSaveSkipRules();
}

// ── 自动同步到后端（静默）────────────────────────────────────

async function _autoSaveSkipRules() {
    try {
        const res = await fetch('/api/code/skip-rules', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                skip_dirs: _skipRulesDraft.dirs,
                skip_exts: _skipRulesDraft.exts,
                gitignore_selections: _gitignoreDraft.map(it => ({name: it.name, selected: it.selected})),
            }),
        });
        if (res.ok) loadPreview();
    } catch (e) {
        console.warn('[skip-rules] 自动保存失败:', e.message);
    }
}

async function saveSkipRules() {
    try {
        const res = await fetch('/api/code/skip-rules', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                skip_dirs: _skipRulesDraft.dirs,
                skip_exts: _skipRulesDraft.exts,
                gitignore_selections: _gitignoreDraft.map(it => ({name: it.name, selected: it.selected})),
            }),
        });
        if (!res.ok) throw new Error('保存失败');
        showToast('已保存', 'success');
        await loadPreview();
        closeSkipRulesModal();
    } catch (e) {
        showToast('保存失败: ' + e.message, 'error');
    }
}

async function resetSkipRules() {
    if (!confirm('确定要恢复默认排除规则吗？当前修改会丢失。')) return;
    try {
        const res = await fetch('/api/code/skip-rules/reset', {method: 'POST'});
        if (!res.ok) throw new Error('重置失败');
        const data = await res.json();
        _skipRulesDraft = {
            dirs: (data.rules.skip_dirs || []).map(d => ({name: d.name, category: d.category})),
            exts: (data.rules.skip_exts || []).map(d => ({name: d.name, category: d.category})),
        };
        renderSkipTable('skip-dirs-body', _skipRulesDraft.dirs, 'dirs');
        renderSkipTable('skip-exts-body', _skipRulesDraft.exts, 'exts');
        await loadGitignoreDirs([]);
        await loadPreview();
    } catch (e) {
        showToast('重置失败: ' + e.message, 'error');
    }
}

async function openSkipRulesInFinder() {
    try {
        const res = await fetch('/api/code/skip-rules/open-finder', {method: 'POST'});
        if (!res.ok) throw new Error('打开 Finder 失败');
    } catch (e) {
        showToast('打开 Finder 失败: ' + e.message, 'error');
    }
}

// 弹窗内独立 tab 切换（与项目路由的 10 个 tab 无关）
// 视觉样式在 theme.css 的 .skip-tab-btn / .skip-tab-btn-active
function switchSkipTab(name) {
    document.querySelectorAll('#skip-rules-modal .skip-tab-btn').forEach(b => {
        b.classList.toggle('skip-tab-btn-active', b.dataset.tab === name);
    });
    const dirs = document.getElementById('skip-pane-dirs');
    const exts = document.getElementById('skip-pane-exts');
    if (dirs) dirs.classList.toggle('hidden', name !== 'dirs');
    if (exts) exts.classList.toggle('hidden', name !== 'exts');
}

// 初始化分类下拉选项（DOM 已就绪：select 在 index.html body 内，<script> 同步执行）
(function initSkipRuleSelects() {
    const dirSel = document.getElementById('skip-dir-category');
    const extSel = document.getElementById('skip-ext-category');
    if (dirSel) dirSel.innerHTML = SKIP_DIR_CATEGORIES.map(c => `<option value="${c}">${c}</option>`).join('');
    if (extSel) extSel.innerHTML = SKIP_EXT_CATEGORIES.map(c => `<option value="${c}">${c}</option>`).join('');
})();

// 全局暴露（onclick / 路由用）
window.openSkipRulesModal = openSkipRulesModal;
window.closeSkipRulesModal = closeSkipRulesModal;
window.refreshSkipRules = refreshSkipRules;
window.saveSkipRules = saveSkipRules;
window.resetSkipRules = resetSkipRules;
window.openSkipRulesInFinder = openSkipRulesInFinder;
window.addSkipRule = addSkipRule;
window.removeSkipRule = removeSkipRule;
window.toggleGitignoreAll = toggleGitignoreAll;
window.switchSkipTab = switchSkipTab;
