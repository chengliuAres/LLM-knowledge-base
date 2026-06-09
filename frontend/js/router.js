/**
 * Hash-based SPA 路由
 *
 * 路由表将 hash 键映射到 {file, title, init}：
 *   - file: tabs 目录下要加载的 HTML 文件
 *   - title: 页面标题
 *   - init: 注入完成后要调用的初始化函数（挂在 window 上）
 *
 * navigate(hash) 负责切换路由、刷新 sidebar 高亮、加载 HTML、
 * 触发 Tailwind CDN 重新扫描以及调用 init 函数。
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

/**
 * 导航到指定 hash 路由。
 * @param {string} hash - 例如 "doc/chat"，可不带 "#"
 */
async function navigate(hash) {
  // 去掉前导 "#"
  const key = (hash || "").replace(/^#/, "").trim();

  // 未匹配或缺失时回退到默认路由
  if (!Routes[key]) {
    console.warn(`[router] 未找到路由 "${key}"，回退到默认路由 "${defaultRoute}"`);
    location.hash = `#${defaultRoute}`;
    return;
  }

  const route = Routes[key];

  // 1. 更新 sidebar 高亮
  document.querySelectorAll(".sidebar-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.route === key);
  });

  // 2. 加载 HTML
  const contentArea = document.getElementById("content-area");
  if (!contentArea) {
    console.error('[router] 找不到 #content-area 容器');
    return;
  }

  try {
    const res = await fetch(route.file);
    if (!res.ok) {
      throw new Error(`HTTP ${res.status} ${res.statusText}`);
    }
    const html = await res.text();
    contentArea.innerHTML = html;
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

  // 3. 更新页面标题
  if (route.title) {
    document.title = `${route.title} · email-wiki`;
  }

  // 4. 让 Tailwind CDN 重新扫描新注入的 DOM（CDN 模式需要）
  if (window.tailwind && typeof window.tailwind.refresh === "function") {
    try {
      window.tailwind.refresh();
    } catch (err) {
      console.warn("[router] tailwind.refresh() 调用失败:", err);
    }
  }

  // 5. 调用 init 函数（页面级脚本入口）
  if (route.init && typeof window[route.init] === "function") {
    try {
      await window[route.init]();
    } catch (err) {
      console.error(`[router] ${route.init}() 执行失败:`, err);
    }
  } else if (route.init) {
    console.warn(`[router] window.${route.init} 不是函数，跳过初始化`);
  }
}

/**
 * HTML 转义，避免错误信息中混入 markup
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
 * 初始化路由：监听 hashchange，首次进入时跳到当前 hash 或默认路由
 */
function init() {
  window.addEventListener("hashchange", () => {
    navigate(location.hash);
  });

  const initial = (location.hash || "").replace(/^#/, "").trim();
  if (!initial || !Routes[initial]) {
    // 用 replace 避免污染历史记录
    location.replace(`#${defaultRoute}`);
  } else {
    navigate(initial);
  }
}

// 暴露到 window
window.Routes = Routes;
window.defaultRoute = defaultRoute;
window.navigate = navigate;
window.initRouter = init;

// DOM 就绪后自动启动
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
