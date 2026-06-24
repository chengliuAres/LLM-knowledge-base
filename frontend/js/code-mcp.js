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

// ===== MCP 测试功能 =====

// 用 fetch 直接 POST JSON-RPC 2.0，content-type 双支持（服务端可能返回 SSE）
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

    // 填充工具下拉（option 上挂 inputSchema 供参数模板用）
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

    // 联动：选中工具时根据 inputSchema 自动填入参数模板
    sel.onchange = function() {
      var opt = sel.options[sel.selectedIndex];
      if (!opt || !opt.dataset.schema) return;
      var schema;
      try { schema = JSON.parse(opt.dataset.schema); } catch (e) { return; }
      var props = (schema.properties || {});
      var required = schema.required || [];
      // 无参（code_list_repos 这种）：直接填 {}
      if (Object.keys(props).length === 0) {
        document.getElementById('mcp-test-args').value = '{}';
        return;
      }
      // 有参：按类型生成示例值，required 加 // 注释提示
      var sample = {};
      Object.keys(props).forEach(function(k) {
        if (props[k].type === 'string') sample[k] = '';
        else if (props[k].type === 'number' || props[k].type === 'integer') sample[k] = 0;
        else if (props[k].type === 'boolean') sample[k] = false;
        else sample[k] = null;
      });
      var hint = required.length ? '// 必填参数: ' + required.join(', ') + '\n' : '';
      document.getElementById('mcp-test-args').value = hint + JSON.stringify(sample, null, 2);
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

    // 默认选 code_list_repos（零参数，连接后点"发送"即可拿到真实数据做闭环验证）
    var preferred = tools.find(function(t) { return t.name === 'code_list_repos'; }) || tools[0];
    if (preferred) {
      sel.value = preferred.name;
      sel.onchange();
    }
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

  // 过滤掉 // 开头的注释行（参数模板里的 "必填参数" 提示）
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

function mcpTestClear() {
  mcpTestRender('');
  document.getElementById('mcp-test-elapsed').textContent = '';
}

// 一键填入真实可跑参数（全部锁定 ghmail 仓，保证点"发送"立刻有数据返回）
// 4 个示例对应 4 个 tool（code_list_repos 零参单独保留"🔌 测试连接"后默认体验）
function mcpTestFillSample(kind) {
  var sel = document.getElementById('mcp-test-tool');
  var ta = document.getElementById('mcp-test-args');

  // 参数设计原则：
  // - repo 全部锁 ghmail（iOS 仓，柳哥的工作项目）
  // - query/symbol/file_path 全部用真实存在的标识符（避免"搜不到"）
  // - language 留空 = 不限定（多语言混合的 ghmail 仓不限制更稳）
  var samples = {
    search: {
      tool: 'code_search',
      // 必填 query；其他字段全留空 = 默认 hybrid + top_k=10
      args: {
        query: '大师号登录页面',
        repo: 'ghmail',
        language: '',
        symbol: '',
        mode: 'hybrid',
        top_k: 5
      }
    },
    chat: {
      tool: 'code_chat',
      // 必填 question；repo 锁 ghmail 拿到 RAG 上下文
      args: {
        question: 'ghmail 的登录流程是怎么实现的？',
        repo: 'ghmail',
        language: ''
      }
    },
    trace: {
      tool: 'code_trace',
      // viewDidLoad 是 iOS 仓最常见符号，必有数据
      args: {
        symbol: 'viewDidLoad',
        repo: 'ghmail',
        direction: 'both',
        depth: 2
      }
    },
    file: {
      tool: 'code_file_context',
      // v2.1 改造：file_name 替代 file_path（AI 记不住长路径，裸文件名更稳）
      // - mailflutter/lib/ui/pages/login/login_page.dart 是登录核心文件，61 chunks
      // - 多匹配时（如 update.py 仓内有 2 个），MCP 返回 candidates 列表让 AI 挑
      args: {
        repo: 'ghmail',
        file_name: 'login_page.dart',
        line_start: 0,
        line_end: 0
      }
    }
  };

  var s = samples[kind];
  if (!s) return;

  // 必须先连上（sel 有 options）才能切换 tool
  if (!sel.options.length || !Array.from(sel.options).some(function(o) { return o.value === s.tool; })) {
    showMcpToast('请先点"测试连接"加载工具列表');
    return;
  }

  // 直接覆盖：切 tool + 写参数（绕过 sel.onchange 防止被覆盖回默认）
  sel.value = s.tool;
  ta.value = JSON.stringify(s.args, null, 2);
  showMcpToast('已填入 ' + s.tool + ' 示例（ghmail），点"📤 发送"试试');
}

window.initCodeMcp = function() {
  // 更新 URL 占位符
  var serverUrl = location.protocol + '//' + location.host;
  document.querySelectorAll('.mcp-url-placeholder').forEach(function(el) {
    el.textContent = serverUrl;
  });
  var urlEl = document.getElementById('mcp-server-url');
  if (urlEl) urlEl.textContent = serverUrl;

  // 测试 tab 端点显示
  var endpointEl = document.getElementById('mcp-test-endpoint');
  if (endpointEl) endpointEl.textContent = serverUrl + '/mcp/';
};
