/**
 * shared.js — 跨 tab 复用的工具函数
 *
 * 提供：HTML 转义、字节/时长格式化、fetch 封装、Toast 通知、折叠卡片切换
 * 不含：领域相关的 renderStepTracker / renderMatchReasons / renderVectorHeatmap16
 *       （这些留在各自 tab 文件内）
 */

/**
 * HTML 转义（基于 createElement + textContent，避免双重转义）
 * @param {*} str
 * @returns {string}
 */
function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = String(str ?? "");
  return div.innerHTML;
}

/**
 * 字节数格式化为 B / KB / MB / GB
 * @param {number} bytes
 * @returns {string}
 */
function formatBytes(bytes) {
  if (bytes == null || isNaN(bytes) || bytes === 0) return "0 B";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  return (bytes / (1024 * 1024 * 1024)).toFixed(1) + " GB";
}

/**
 * 毫秒格式化为 ms / s
 * @param {number} ms
 * @returns {string}
 */
function formatDuration(ms) {
  if (ms == null || isNaN(ms)) return "-";
  if (ms < 1000) return ms.toFixed(0) + " ms";
  return (ms / 1000).toFixed(2) + " s";
}

/**
 * fetch 封装：自动 JSON 头 + 解析响应 + 错误抛出
 * - 非 2xx 状态码时，尝试从 JSON 响应里取出 detail 作为错误信息抛出
 * - 成功时返回解析后的 JSON
 *
 * @param {string} url
 * @param {RequestInit} [options]
 * @returns {Promise<any>}
 */
async function apiFetch(url, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };

  let res;
  try {
    res = await fetch(url, { ...options, headers });
  } catch (err) {
    throw new Error("网络请求失败: " + (err.message || err));
  }

  // 尝试解析 JSON（即使是非 2xx，错误响应体也是 JSON）
  let data = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (_) {
      // 响应不是 JSON，留 null
    }
  }

  if (!res.ok) {
    const detail = (data && (data.detail || data.message)) || res.statusText || `HTTP ${res.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }

  return data;
}

/**
 * 轻量 Toast 通知，3 秒后自动消失
 * @param {string} msg
 * @param {"info"|"success"|"error"} [type="info"]
 */
function showToast(msg, type = "info") {
  const palette = {
    info:    "bg-slate-700 text-white",
    success: "bg-green-500 text-white",
    error:   "bg-red-500 text-white",
  };
  const cls = palette[type] || palette.info;

  const toast = document.createElement("div");
  toast.className = `fixed bottom-4 right-4 px-4 py-2 rounded-lg shadow-lg z-50 text-sm ${cls}`;
  toast.textContent = msg;
  document.body.appendChild(toast);

  setTimeout(() => {
    toast.remove();
  }, 3000);
}

/**
 * 切换 .collapsible-content 的 max-height（步骤卡片折叠/展开）
 * @param {string} stepId
 */
function toggleStepCard(stepId) {
  const el = document.getElementById(stepId);
  if (el) el.classList.toggle("expanded");
}

// 暴露到 window，供内联 onclick / 其他模块使用
window.escapeHtml = escapeHtml;
window.formatBytes = formatBytes;
window.formatDuration = formatDuration;
window.apiFetch = apiFetch;
window.showToast = showToast;
window.toggleStepCard = toggleStepCard;
