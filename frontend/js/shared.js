/**
 * shared.js — 全局公共工具函数
 * 由 index.html 在所有 tab 之前加载，所有函数挂到 window 上
 */

// ─── HTML 转义 ───────────────────────────────────────────
function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// ─── 字节格式化 ─────────────────────────────────────────
function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    let val = bytes;
    while (val >= 1024 && i < units.length - 1) { val /= 1024; i++; }
    return val.toFixed(i === 0 ? 0 : 1) + ' ' + units[i];
}

// ─── 毫秒格式化 ─────────────────────────────────────────
function formatDuration(ms) {
    if (ms == null) return '--';
    if (ms < 1000) return ms + 'ms';
    return (ms / 1000).toFixed(2) + 's';
}

// ─── API 请求封装 ───────────────────────────────────────
async function apiFetch(url, options = {}) {
    const res = await fetch(url, options);
    if (!res.ok) {
        const text = await res.text().catch(() => res.statusText);
        throw new Error(text || `HTTP ${res.status}`);
    }
    return res;
}

// ─── Toast 通知 ─────────────────────────────────────────
function showToast(message, type = 'info') {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'fixed top-4 right-4 z-[9999] flex flex-col gap-2';
        document.body.appendChild(container);
    }
    const colors = {
        info:    { bg: '#1E293B', border: '#334155', text: '#E2E8F0' },
        success: { bg: '#064E3B', border: '#10B981', text: '#A7F3D0' },
        error:   { bg: '#450A0A', border: '#EF4444', text: '#FCA5A5' },
        warning: { bg: '#451A03', border: '#F59E0B', text: '#FCD34D' },
    };
    const c = colors[type] || colors.info;
    const toast = document.createElement('div');
    toast.className = 'px-4 py-3 rounded-lg shadow-lg text-sm max-w-sm';
    toast.style.cssText = `background:${c.bg}; border:1px solid ${c.border}; color:${c.text}; animation: slideIn 0.3s ease;`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => { toast.style.opacity = '0'; toast.style.transition = 'opacity 0.3s'; setTimeout(() => toast.remove(), 300); }, 3000);
}

// ─── 步骤卡片折叠 ──────────────────────────────────────
function toggleStepCard(header) {
    const body = header.nextElementSibling;
    if (!body) return;
    const arrow = header.querySelector('.arrow');
    if (body.style.display === 'none') {
        body.style.display = '';
        if (arrow) arrow.textContent = '▼';
    } else {
        body.style.display = 'none';
        if (arrow) arrow.textContent = '▶';
    }
}

// ─── codeRenderSteps：渲染执行步骤（接受 container 参数） ───
// 兼容旧调用：codeRenderSteps(steps) → 使用默认容器
function codeRenderSteps(containerOrId, steps) {
    let el, actualSteps;
    if (Array.isArray(containerOrId)) {
        // 旧调用方式：codeRenderSteps(steps)
        actualSteps = containerOrId;
        el = document.getElementById('codeScanProgress') || document.getElementById('codeSteps') || document.getElementById('codeSearchSteps') || document.getElementById('codeChatSteps');
    } else {
        el = typeof containerOrId === 'string' ? document.getElementById(containerOrId) : containerOrId;
        actualSteps = steps;
    }
    if (!el || !actualSteps || actualSteps.length === 0) return;
    el.innerHTML = actualSteps.map((step) => {
        const icon = step.status === 'done' ? '✅' : step.status === 'error' ? '❌' : '⏳';
        const ms = step.elapsed_ms != null ? ` <span class="text-xs" style="color:var(--color-muted)">${step.elapsed_ms}ms</span>` : '';
        const details = (step.details || []).map(d => {
            const val = typeof d.value === 'object' ? JSON.stringify(d.value) : String(d.value);
            return `<div class="text-xs ml-6" style="color:var(--color-muted)">${escapeHtml(d.label)}: ${escapeHtml(val)}</div>`;
        }).join('');
        return `<div class="py-1">${icon} <span class="font-medium">${escapeHtml(step.name)}</span>${ms}${details}</div>`;
    }).join('');
}

// ─── 搜索结果渲染工具（从 doc-upload/doc-chat 提取） ───
const REASON_COLOR_CLASS = {
    red:    { bg: 'rgba(239, 68, 68, 0.15)',  fg: '#FCA5A5', border: 'rgba(239, 68, 68, 0.40)' },
    amber:  { bg: 'rgba(245, 158, 11, 0.15)', fg: '#FCD34D', border: 'rgba(245, 158, 11, 0.40)' },
    blue:   { bg: 'rgba(59, 130, 246, 0.15)', fg: '#93C5FD', border: 'rgba(59, 130, 246, 0.40)' },
    indigo: { bg: 'rgba(99, 102, 241, 0.15)', fg: '#A5B4FC', border: 'rgba(99, 102, 241, 0.40)' },
    slate:  { bg: 'rgba(100, 116, 139, 0.15)',fg: '#CBD5E1', border: 'rgba(100, 116, 139, 0.40)' },
    purple: { bg: 'rgba(168, 85, 247, 0.15)', fg: '#D8B4FE', border: 'rgba(168, 85, 247, 0.40)' },
    green:  { bg: 'rgba(34, 197, 94, 0.15)',  fg: '#86EFAC', border: 'rgba(34, 197, 94, 0.40)' },
};

function highlightText(text, query, hitKeywords) {
    if (!text) return '';
    let escaped = escapeHtml(text);
    let words = [];
    if (hitKeywords && hitKeywords.length > 0) {
        words = [...hitKeywords];
    } else if (query) {
        words = query.split(/\s+/).filter(w => w.length > 0);
    }
    if (words.length === 0) return escaped;
    words.sort((a, b) => b.length - a.length);
    const escapedWords = words.map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    const regex = new RegExp(`(${escapedWords.join('|')})`, 'gi');
    return escaped.replace(regex, '<mark>$1</mark>');
}

function renderMatchReasons(reasons) {
    if (!reasons || reasons.length === 0) return '';
    return '<div class="flex flex-wrap gap-1 mt-1.5">' +
        reasons.map(r => {
            const c = REASON_COLOR_CLASS[r.color] || REASON_COLOR_CLASS.slate;
            return '<span class="text-[10px] px-1.5 py-0.5 rounded border" style="background-color: ' + c.bg + '; color: ' + c.fg + '; border-color: ' + c.border + ';">' + escapeHtml(r.label) + '</span>';
        }).join('') +
        '</div>';
}

// ─── 全局暴露 ──────────────────────────────────────────
window.escapeHtml = escapeHtml;
window.formatBytes = formatBytes;
window.formatDuration = formatDuration;
window.apiFetch = apiFetch;
window.showToast = showToast;
window.toggleStepCard = toggleStepCard;
window.codeRenderSteps = codeRenderSteps;
window.REASON_COLOR_CLASS = REASON_COLOR_CLASS;
window.highlightText = highlightText;
window.renderMatchReasons = renderMatchReasons;
