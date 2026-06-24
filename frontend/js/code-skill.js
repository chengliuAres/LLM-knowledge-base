/**
 * Skill 接入子页 — 4 子 tab 切换 + 数据加载
 * 由 code-mcp.html 的 switchAgentTab('skill') 触发
 */
(function () {
  var cache = { md: null, info: null, commands: null };

  window.switchSkillTab = function (name) {
    document.querySelectorAll('.skill-tab-btn').forEach(function (btn) {
      var isActive = btn.dataset.skillTab === name;
      btn.classList.toggle('active', isActive);
      btn.style.background = isActive ? 'var(--color-accent)' : '';
      btn.style.color = isActive ? 'var(--color-on-primary)' : 'var(--color-muted)';
    });
    document.querySelectorAll('.skill-tab-content').forEach(function (el) {
      el.classList.toggle('hidden', el.id !== 'skill-tab-' + name);
    });
    if (name === 'md' && !cache.md) loadSkillMd();
    if (name === 'commands' && !cache.commands) loadSkillCommands();
    if (name === 'download' && !cache.info) loadSkillInfo();
  };

  window.initSkillTab = function () {
    if (!document.querySelector('.skill-tab-content:not(.hidden)')) {
      window.switchSkillTab('install');
    }
  };

  function fetchSkillData(url, cacheKey, contentId, renderer) {
    fetch(url).then(function (r) { return r.json(); }).then(function (data) {
      cache[cacheKey] = data;
      var el = document.getElementById(contentId);
      if (el) renderer(el, data);
    }).catch(function (e) {
      var el = document.getElementById(contentId);
      if (el) el.innerHTML = '<div style="color:#EF4444;">❌ 加载失败: ' + e + '</div>';
    });
  }

  function loadSkillMd() {
    fetchSkillData('/api/skill/raw', 'md', 'skill-md-content', function (el, data) {
      el.innerHTML = renderMarkdown(data.content);
    });
  }

  function loadSkillCommands() {
    fetchSkillData('/api/skill/commands', 'commands', 'skill-commands-content', function (el, data) {
      renderCommandsTable(el, data.commands || []);
    });
  }

  function loadSkillInfo() {
    fetchSkillData('/api/skill/info', 'info', 'skill-info-content', renderSkillInfo);
  }

  function renderSkillInfo(el, data) {
    var filesHtml = (data.files || []).map(function (f) {
      return '<li><code>' + f.name + '</code> <span style="color:var(--color-muted);">(' + formatSize(f.size) + ')</span></li>';
    }).join('');
    el.innerHTML =
      '<div class="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">' +
        '<div class="rounded p-3" style="background:var(--color-surface);"><div class="text-xs" style="color:var(--color-muted);">文件数</div><div class="text-lg font-semibold">' + data.file_count + '</div></div>' +
        '<div class="rounded p-3" style="background:var(--color-surface);"><div class="text-xs" style="color:var(--color-muted);">总大小</div><div class="text-lg font-semibold">' + formatSize(data.total_size) + '</div></div>' +
        '<div class="rounded p-3" style="background:var(--color-surface);"><div class="text-xs" style="color:var(--color-muted);">根目录</div><div class="text-lg font-semibold font-mono">code-search/</div></div>' +
      '</div>' +
      '<div class="rounded p-3 mb-4" style="background:var(--color-surface);"><div class="text-xs mb-2" style="color:var(--color-muted);">文件清单</div><ul class="text-sm space-y-1">' + filesHtml + '</ul></div>' +
      '<a href="/api/skill/download" download="code-search.zip" ' +
         'class="inline-block px-5 py-2.5 rounded text-sm font-medium transition-colors" ' +
         'style="background:var(--color-accent); color:var(--color-on-primary);" ' +
         'onmouseover="this.style.opacity=0.85" onmouseout="this.style.opacity=1">⬇️ 下载 code-search.zip</a>';
  }

  function renderCommandsTable(el, commands) {
    if (commands.length === 0) {
      el.innerHTML = '<div style="color:var(--color-muted);">⚠️ 暂未解析到子命令</div>';
      return;
    }
    var rows = commands.map(function (c) {
      return '<tr><td class="px-3 py-2 font-mono">' + c.name + '</td><td class="px-3 py-2 text-sm" style="color:var(--color-muted);">' + (c.help || '—') + '</td></tr>';
    }).join('');
    el.innerHTML =
      '<table class="w-full text-sm" style="border-collapse:collapse;">' +
        '<thead><tr style="background:var(--color-surface);">' +
          '<th class="px-3 py-2 text-left">子命令</th><th class="px-3 py-2 text-left">说明</th>' +
        '</tr></thead>' +
        '<tbody>' + rows + '</tbody>' +
      '</table>';
  }

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1024 / 1024).toFixed(2) + ' MB';
  }

  // 极简 markdown 渲染（~30 行，仅支持本 SKILL.md 用到的语法）
  function renderMarkdown(text) {
    var html = text
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/```(\w*)\n([\s\S]*?)```/g, function (_, lang, code) {
        return '<pre style="background:var(--color-background); padding:8px; border-radius:4px; overflow:auto;"><code>' + code.trim() + '</code></pre>';
      })
      .replace(/^### (.+)$/gm, '<h3 style="color:var(--color-accent); margin:12px 0 6px;">$1</h3>')
      .replace(/^## (.+)$/gm, '<h2 style="color:white; margin:16px 0 8px;">$1</h2>')
      .replace(/^# (.+)$/gm, '<h1 style="color:white; margin:20px 0 10px;">$1</h1>')
      .replace(/`([^`]+)`/g, '<code style="background:var(--color-background); padding:1px 4px; border-radius:2px;">$1</code>')
      .replace(/^\- (.+)$/gm, '<li>$1</li>')
      .replace(/(<li>.*<\/li>\n?)+/g, function (block) { return '<ul style="margin:6px 0 6px 20px;">' + block + '</ul>'; })
      .replace(/\n\n/g, '</p><p style="margin:8px 0;">')
      .replace(/^/, '<p style="margin:8px 0;">')
      .replace(/$/, '</p>');
    return html;
  }
})();
