/**
 * MCP 接入 Tab 交互逻辑：
 * - 子标签切换 (接入指南/客户端配置/使用示例)
 * - 一键复制代码
 */

function switchMcpTab(tabId) {
  // 更新按钮状态
  document.querySelectorAll('.mcp-subtab-btn').forEach(function(btn) {
    var isActive = btn.dataset.mcpTab === tabId;
    btn.classList.toggle('active', isActive);
    btn.style.background = isActive ? 'var(--color-accent)' : '';
    btn.style.color = isActive ? 'var(--color-on-primary)' : 'var(--color-muted)';
  });

  // 切换内容区
  document.querySelectorAll('.mcp-tab-content').forEach(function(content) {
    content.classList.toggle('hidden', content.id !== 'mcp-tab-' + tabId);
  });
}

function copyMcpCode(btn, codeText) {
  // 替换 URL 占位符
  var url = location.protocol + '//' + location.host;
  var text = codeText.replace(/REPLACE_URL/g, url);

  navigator.clipboard.writeText(text).then(function() {
    // 按钮反馈
    var origText = btn.textContent;
    btn.textContent = '✓ 已复制';
    btn.style.color = 'var(--color-accent)';
    setTimeout(function() {
      btn.textContent = origText;
      btn.style.color = '';
    }, 2000);

    // Toast 提示
    showMcpToast('已复制到剪贴板');
  }).catch(function() {
    showMcpToast('复制失败，请手动复制');
  });
}

function showMcpToast(msg) {
  var toast = document.getElementById('mcp-toast');
  if (!toast) return;
  toast.textContent = msg;
  toast.classList.remove('opacity-0');
  toast.classList.add('opacity-100');
  setTimeout(function() {
    toast.classList.remove('opacity-100');
    toast.classList.add('opacity-0');
  }, 3000);
}

window.initCodeMcp = function() {
  // 更新 URL 占位符
  var serverUrl = location.protocol + '//' + location.host;
  document.querySelectorAll('.mcp-url-placeholder').forEach(function(el) {
    el.textContent = serverUrl;
  });
  var urlEl = document.getElementById('mcp-server-url');
  if (urlEl) urlEl.textContent = serverUrl;
};
