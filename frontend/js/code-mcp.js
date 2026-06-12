/**
 * MCP 接入 Tab 交互逻辑：
 * - 子标签切换 (接入指南/客户端配置/使用示例/AI视角/测试)
 * - 一键复制代码
 * - MCP Streamable HTTP 端点测试 (initialize + tools/list + tools/call)
 */

// Streamable HTTP 协议要求带 Accept 头以声明可接受 SSE 流响应
var MCP_PROTOCOL_VERSION = '2024-11-05';

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

  // 切到测试 tab 时刷新端点显示
  if (tabId === 'test') {
    refreshMcpTestEndpoint();
  }
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

function refreshMcpTestEndpoint() {
  var endpoint = location.protocol + '//' + location.host + '/mcp/';
  var el = document.getElementById('mcp-test-endpoint');
  if (el) el.textContent = endpoint;
}

// ===== MCP 测试功能 =====

// 用 fetch + ReadableStream 解析 SSE 格式响应（服务端可能返回 text/event-stream）
async function mcpTestPostRpc(method, params) {
  var endpoint = location.protocol + '//' + location.host + '/mcp/';
  var body = JSON.stringify({
    jsonrpc: '2.0',
    id: Date.now(),
    method: method,
    params: params || {}
  });

  var resp = await fetch(endpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json, text/event-stream',
      'MCP-Protocol-Version': MCP_PROTOCOL_VERSION
    },
    body: body
  });

  if (!resp.ok) {
    var errText = await resp.text().catch(function() { return ''; });
    throw new Error('HTTP ' + resp.status + ' ' + resp.statusText + (errText ? '\n' + errText : ''));
  }

  var contentType = resp.headers.get('content-type') || '';
  var raw = await resp.text();

  // application/json：直接 parse
  if (contentType.indexOf('application/json') !== -1) {
    return JSON.parse(raw);
  }

  // text/event-stream：抽取首个 data: 行
  var lines = raw.split('\n');
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i].trim();
    if (line.indexOf('data:') === 0) {
      var data = line.slice(5).trim();
      if (data) return JSON.parse(data);
    }
  }
  throw new Error('SSE 响应无 data 行: ' + raw.slice(0, 200));
}

function mcpTestSetStatus(text, color) {
  var el = document.getElementById('mcp-test-status');
  if (!el) return;
  el.textContent = text;
  el.style.color = color || 'var(--color-muted)';
}

function mcpTestRender(payload) {
  var pre = document.getElementById('mcp-test-response');
  if (!pre) return;
  if (typeof payload === 'string') {
    pre.textContent = payload;
  } else {
    pre.textContent = JSON.stringify(payload, null, 2);
  }
}

async function mcpTestConnect() {
  var btn = document.getElementById('mcp-test-connect-btn');
  btn.disabled = true;
  btn.textContent = '⏳ 连接中…';
  mcpTestSetStatus('连接中…', 'var(--color-muted)');
  mcpTestRender('正在发送 initialize 请求…');

  var start = Date.now();
  try {
    // 1. initialize 握手
    var initResp = await mcpTestPostRpc('initialize', {
      protocolVersion: MCP_PROTOCOL_VERSION,
      capabilities: {},
      clientInfo: { name: 'email-wiki-mcp-test-ui', version: '1.0.0' }
    });

    if (initResp.error) {
      throw new Error('initialize 错误: ' + JSON.stringify(initResp.error));
    }

    // 2. 拉取工具列表
    var toolsResp = await mcpTestPostRpc('tools/list', {});
    if (toolsResp.error) {
      throw new Error('tools/list 错误: ' + JSON.stringify(toolsResp.error));
    }

    var tools = (toolsResp.result && toolsResp.result.tools) || [];
    var elapsed = Date.now() - start;

    // 填充工具下拉
    var sel = document.getElementById('mcp-test-tool');
    sel.innerHTML = '';
    tools.forEach(function(t) {
      var opt = document.createElement('option');
      opt.value = t.name;
      opt.textContent = t.name + (t.description ? ' — ' + t.description.slice(0, 40) : '');
      opt.dataset.schema = JSON.stringify(t.inputSchema || {});
      sel.appendChild(opt);
    });
    sel.disabled = false;

    // 联动：选中工具时自动填入参数 schema 模板
    sel.onchange = function() {
      var opt = sel.options[sel.selectedIndex];
      if (!opt || !opt.dataset.schema) return;
      var schema;
      try { schema = JSON.parse(opt.dataset.schema); } catch (e) { return; }
      var props = (schema.properties || {});
      var required = schema.required || [];
      var sample = {};
      Object.keys(props).forEach(function(k) {
        // 简单示例值：string→空串(让用户填) / number→0 / bool→false
        if (props[k].type === 'string') sample[k] = '';
        else if (props[k].type === 'number' || props[k].type === 'integer') sample[k] = 0;
        else if (props[k].type === 'boolean') sample[k] = false;
        else sample[k] = null;
      });
      // required 提示行加在 schema 注释里（仅做提示，不影响 JSON 合法性）
      var hint = required.length ? '// 必填参数: ' + required.join(', ') + '\n' : '';
      var ta = document.getElementById('mcp-test-args');
      ta.value = hint + JSON.stringify(sample, null, 2);
    };

    // 启用输入与发送
    document.getElementById('mcp-test-args').disabled = false;
    document.getElementById('mcp-test-send-btn').disabled = false;

    mcpTestSetStatus('✓ 已连接（' + tools.length + ' 工具，' + elapsed + 'ms）', '#22C55E');
    var serverName = (initResp.result && initResp.result.serverInfo && initResp.result.serverInfo.name) || '?';
    document.getElementById('mcp-test-serverinfo').textContent = 'server=' + serverName;

    mcpTestRender({
      _note: 'initialize + tools/list 成功',
      initialize_result: initResp.result,
      tools: tools.map(function(t) { return { name: t.name, description: t.description }; })
    });

    // 自动选第一个工具并填 schema
    if (tools.length) sel.onchange();
  } catch (err) {
    mcpTestSetStatus('✗ 连接失败', '#EF4444');
    mcpTestRender({ _error: err.message, _hint: '确认后端已启动 (./start.sh)，端口 8000 可访问' });
  } finally {
    btn.disabled = false;
    btn.textContent = '🔌 重新连接';
  }
}

async function mcpTestSend() {
  var tool = document.getElementById('mcp-test-tool').value;
  var argsRaw = document.getElementById('mcp-test-args').value.trim();
  if (!tool) {
    mcpTestRender({ _error: '请先选择工具' });
    return;
  }

  // 去掉 schema 注释行（以 // 开头）
  var cleanedLines = argsRaw.split('\n').filter(function(line) {
    return line.trim().indexOf('//') !== 0;
  });
  var cleanedRaw = cleanedLines.join('\n').trim();

  var args = {};
  if (cleanedRaw) {
    try { args = JSON.parse(cleanedRaw); }
    catch (e) {
      mcpTestRender({ _error: '参数 JSON 解析失败: ' + e.message });
      return;
    }
  }

  var btn = document.getElementById('mcp-test-send-btn');
  var spinner = document.getElementById('mcp-test-spinner');
  var elapsedEl = document.getElementById('mcp-test-elapsed');
  btn.disabled = true;
  spinner.classList.remove('hidden');
  elapsedEl.textContent = '';

  var start = Date.now();
  try {
    var resp = await mcpTestPostRpc('tools/call', { name: tool, arguments: args });
    var elapsed = Date.now() - start;
    elapsedEl.textContent = '⏱ ' + elapsed + 'ms';

    if (resp.error) {
      mcpTestRender({
        _request: { method: 'tools/call', name: tool, arguments: args },
        _error: resp.error
      });
    } else {
      mcpTestRender({
        _request: { method: 'tools/call', name: tool, arguments: args },
        _elapsed_ms: elapsed,
        _result: resp.result
      });
    }
  } catch (err) {
    elapsedEl.textContent = '';
    mcpTestRender({
      _request: { method: 'tools/call', name: tool, arguments: args },
      _error: err.message
    });
  } finally {
    btn.disabled = false;
    spinner.classList.add('hidden');
  }
}

function mcpTestFillSample() {
  var sel = document.getElementById('mcp-test-tool');
  if (!sel.value) {
    showMcpToast('请先选择工具');
    return;
  }
  var opt = sel.options[sel.selectedIndex];
  if (opt && opt.dataset.schema) {
    sel.onchange();
  }
}

function mcpTestClear() {
  mcpTestRender('');
  document.getElementById('mcp-test-elapsed').textContent = '';
}

window.initCodeMcp = function() {
  // 更新 URL 占位符
  var serverUrl = location.protocol + '//' + location.host;
  document.querySelectorAll('.mcp-url-placeholder').forEach(function(el) {
    el.textContent = serverUrl;
  });
  var urlEl = document.getElementById('mcp-server-url');
  if (urlEl) urlEl.textContent = serverUrl;

  // 初始化测试 tab 端点显示
  refreshMcpTestEndpoint();
};
