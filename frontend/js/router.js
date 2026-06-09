/**
 * Hash-based SPA 路由（带 DOM 缓存）
 *
 * 首次访问 tab：fetch HTML → 注入 DOM → 执行 script → 缓存
 * 再次访问 tab：直接 show 缓存的 DOM（状态保留）
 *
 * 路由表将 hash 键映射到 {file, title, init}：
 *   - file: tabs 目录下要加载的 HTML 文件
 *   - title: 页面标题
 *   - init: 注入完成后要调用的初始化函数（挂在 window 上，仅首次调用）
 */

const Routes = {
  "doc/upload":      { file: "tabs/doc-upload.html",      title: "文档上传",     init: "initDocUpload" },
  "doc/email":       { file: "tabs/doc-email.html",       title: "邮件导入",     init: "initDocEmail" },
  "doc/chat":        { file: "tabs/doc-chat.html",        title: "文档问答",     init: "initDocChat" },
  "doc/dashboard":   { file: "tabs/doc-dashboard.html",   title: "文档统计",     init: "initDocDashboard" },
  "doc/lancedb":     { file: "tabs/doc-lancedb.html",     title: "LanceDB 浏览器", init: "initDocLancedb" },
  "code/repos":      { file: "tabs/code-repos.html",      title: "代码仓库",     init: "initCodeRepos" },
  "code/search":     { file: "tabs/code-search.html",     title: "代码搜索",     init: "initCodeSearch" },
  "code/chat":       { file: "tabs/code-chat.html",       title: "代码问答",     init: "initCodeChat" },
  "code/dashboard":  { file: "tabs/code-dashboard.html",  title: "代码统计",     init: "initCodeDashboard" },
  "code/lancedb":    { file: "tabs/code-lancedb.html",    title: "代码 LanceDB",  init: "initCodeLancedb" },
};

const defaultRoute = "doc/upload";

// DOM 缓存：key → { wrapper: HTMLElement, initialized: boolean }
const _cache = {};
let _currentKey = null;

/**
 * 导航到指定 hash 路由。
 * @param {string} hash - 例如 "doc/chat"，可不带 "#"
 */
async function navigate(hash) {
  const key = (hash || "").replace(/^#/, "").trim();

  if (!Routes[key]) {
    console.warn(`[router] 未找到路由 "${key}"，回退到默认路由 "${defaultRoute}"`);
    location.hash = `#${defaultRoute}`;
    return;
  }

  // 同一个 tab，不重复加载
  if (key === _currentKey) return;

  const route = Routes[key];
  const contentArea = document.getElementById("content-area");
  if (!contentArea) {
    console.error('[router] 找不到 #content-area 容器');
    return;
  }

  // 1. 隐藏当前 tab
  if (_currentKey && _cache[_currentKey]) {
    _cache[_currentKey].wrapper.style.display = "none";
  }

  // 2. 获取或创建目标 tab 的 DOM
  if (!_cache[key]) {
    // 首次访问：清除 content-area 默认占位（"加载中…"）
    // appendChild 模式下不会自动覆盖，需手动清理
    const placeholder = contentArea.querySelector('.router-placeholder');
    if (placeholder) placeholder.remove();

    // fetch + 注入
    try {
      const res = await fetch(route.file + '?v=' + (window.__TAB_VERSION || '1'));
      if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`);
      const html = await res.text();

      // 创建隔离的 wrapper div
      const wrapper = document.createElement("div");
      wrapper.id = `tab-${key.replace("/", "-")}`;
      wrapper.className = "tab-page";
      wrapper.innerHTML = html;
      contentArea.appendChild(wrapper);

      _cache[key] = { wrapper, initialized: false };

      // 执行注入的 <script> 标签（仅首次）
      const scripts = Array.from(wrapper.querySelectorAll("script"));
      for (const oldScript of scripts) {
        if (oldScript.src) {
          const newScript = document.createElement("script");
          newScript.src = oldScript.src;
          document.head.appendChild(newScript);
        } else {
          try {
            eval(oldScript.textContent);
          } catch (err) {
            console.error("[router] 脚本执行失败:", err);
          }
        }
      }
    } catch (err) {
      console.error(`[router] 加载 "${route.file}" 失败:`, err);
      contentArea.innerHTML = `
        <div class="p-6">
          <div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
            <p class="font-semibold">页面加载失败</p>
            <p class="text-sm mt-1">${escapeHtml(err.message || String(err))}</p>
          </div>
        </div>`;
      return;
    }
  }

  // 3. 显示目标 tab
  _cache[key].wrapper.style.display = "";
  _currentKey = key;

  // 4. 更新 sidebar 高亮
  document.querySelectorAll(".sidebar-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.route === key);
  });

  // 5. 更新页面标题
  if (route.title) {
    document.title = `${route.title} · email-wiki`;
  }

  // 6. Tailwind CDN 重新扫描（首次加载时需要）
  if (window.tailwind && typeof window.tailwind.refresh === "function") {
    try { window.tailwind.refresh(); } catch (e) { /* ignore */ }
  }

  // 7. 调用 init 函数（仅首次）
  if (!_cache[key].initialized && route.init && typeof window[route.init] === "function") {
    _cache[key].initialized = true;
    try {
      await window[route.init]();
    } catch (err) {
      console.error(`[router] ${route.init}() 执行失败:`, err);
    }
  }
}

/**
 * 强制重新加载当前 tab（丢弃缓存，用于刷新数据）
 */
function reloadCurrentTab() {
  if (_currentKey && _cache[_currentKey]) {
    _cache[_currentKey].wrapper.remove();
    delete _cache[_currentKey];
    const key = _currentKey;
    _currentKey = null;
    navigate(key);
  }
}

/**
 * HTML 转义
 */
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * 初始化路由
 */
let _routerInitialized = false;
function init() {
  if (_routerInitialized) return;
  _routerInitialized = true;

  window.addEventListener("hashchange", () => {
    navigate(location.hash);
  });

  const initial = (location.hash || "").replace(/^#/, "").trim();
  if (!initial || !Routes[initial]) {
    location.replace(`#${defaultRoute}`);
  } else {
    navigate(initial);
  }
}

// 暴露到 window
window.Routes = Routes;
window.defaultRoute = defaultRoute;
window.navigate = navigate;
window.reloadCurrentTab = reloadCurrentTab;
window.initRouter = init;

// DOM 就绪后自动启动
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
