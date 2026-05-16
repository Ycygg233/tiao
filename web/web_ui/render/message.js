/* render/message.js — 消息气泡（日志流风格：终端日志条目） */
var RenderMsg = {};
RenderMsg._currentAiEl = null;
RenderMsg._statusEl = null;
RenderMsg._lastWasProcess = false;  // 上次是否添加了 process 条目（用于 section-break）

// ===== 移除空状态 =====
RenderMsg._removeEmpty = function() {
  var es = document.getElementById('empty-state');
  if (es && es.parentNode) es.parentNode.removeChild(es);
};

// ===== 在 content-entry 中添加复制按钮 =====
RenderMsg._addEntryCopyBtn = function(entryEl, getText) {
  var btn = document.createElement('button');
  btn.className = 'entry-copy-btn';
  btn.title = '复制消息';
  btn.innerHTML =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:13px;height:13px">' +
    '<rect x="9" y="9" width="13" height="13" rx="2"/>' +
    '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>' +
    '</svg>';
  btn.onclick = function(e) {
    e.stopPropagation();
    var txt = getText();
    Utils.copyToClipboard(txt, function() {
      btn.innerHTML =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="width:13px;height:13px;color:var(--accent-green)">' +
        '<polyline points="20 6 9 17 4 12"/>' +
        '</svg>';
      btn.classList.add('copied');
      setTimeout(function() {
        btn.innerHTML =
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:13px;height:13px">' +
          '<rect x="9" y="9" width="13" height="13" rx="2"/>' +
          '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>' +
          '</svg>';
        btn.classList.remove('copied');
      }, 2000);
    });
  };
  entryEl.appendChild(btn);
};

// ===== 用户消息（终端风格：> 前缀，无气泡） =====
RenderMsg.addUser = function(text) {
  RenderMsg._removeEmpty();
  RenderMsg.clearStatus();
  RenderMsg._currentAiEl = null;
  RenderMsg._lastWasProcess = false;

  var entry = document.createElement('div');
  entry.className = 'log-entry user-entry';
  entry.textContent = text;

  // 双击回填输入框
  entry.ondblclick = function() {
    var input = document.getElementById('input');
    if (input) { input.value = text; input.focus(); }
  };

  var msgDiv = document.getElementById('messages');
  if (msgDiv) msgDiv.appendChild(entry);
  Utils.scrollToBottom(true);
};

// ===== 编辑用户消息 =====
RenderMsg._editUser = function(userEntry, text) {
  var input = document.getElementById('input');
  if (!input) return;
  input.value = text;
  input.focus();
  input.style.height = 'auto';
  input.style.height = Math.min(input.scrollHeight, 120) + 'px';

  // 移除该用户消息之后的所有兄弟节点
  var msgDiv = document.getElementById('messages');
  if (!msgDiv) return;
  var nodes = Array.from(msgDiv.children);
  var idx = nodes.indexOf(userEntry);
  if (idx !== -1) {
    var toRemove = nodes.slice(idx + 1);
    toRemove.forEach(function(n) {
      if (n.parentNode) n.parentNode.removeChild(n);
    });
  }
  RenderMsg._currentAiEl = null;
  RenderMsg.clearStatus();
  RenderThink.clearAll();
  RenderContent.reset();
};

// ===== 来源标识 =====
RenderMsg.addSourceLabel = function(modelName, timeStr) {
  RenderMsg._removeEmpty();
  var label = document.createElement('div');
  label.className = 'log-entry source-label';
  label.textContent = (modelName || 'AI') + ' \u00b7 ' + (timeStr || '');
  var msgDiv = document.getElementById('messages');
  if (msgDiv) msgDiv.appendChild(label);
};

// ===== 分隔线 =====
RenderMsg.addSectionBreak = function() {
  var hr = document.createElement('hr');
  hr.className = 'section-break';
  var msgDiv = document.getElementById('messages');
  if (msgDiv) msgDiv.appendChild(hr);
  RenderMsg._lastWasProcess = false;
};

// ===== AI 内容条目（获取或创建） =====
RenderMsg.getOrCreateAi = function() {
  if (RenderMsg._currentAiEl &&
      RenderMsg._currentAiEl.parentNode &&
      RenderMsg._currentAiEl.parentNode.parentNode === document.getElementById('messages')) {
    return RenderMsg._currentAiEl;
  }

  RenderMsg._removeEmpty();
  RenderMsg.clearStatus();
  RenderContent.reset();

  var entry = document.createElement('div');
  entry.className = 'log-entry content-entry';

  // 内容容器
  var contentDiv = document.createElement('div');
  contentDiv.className = 'ai-content';
  entry.appendChild(contentDiv);

  // 词元统计（隐藏）
  var usage = document.createElement('span');
  usage.className = 'entry-usage';
  entry.appendChild(usage);

  // 复制按钮
  RenderMsg._addEntryCopyBtn(entry, function() {
    var segs = contentDiv.querySelectorAll('.md-segment');
    return Array.from(segs).map(function(s) { return s.textContent; }).join('\n');
  });

  var msgDiv = document.getElementById('messages');
  if (msgDiv) msgDiv.appendChild(entry);

  RenderMsg._currentAiEl = contentDiv;
  Utils.scrollToBottom(true);
  return RenderMsg._currentAiEl;
};

// ===== 更新词元统计 =====
RenderMsg.updateUsage = function(d) {
  var entries = document.querySelectorAll('.content-entry');
  if (!entries.length) return;
  var lastEntry = entries[entries.length - 1];
  var usageEl = lastEntry.querySelector('.entry-usage');
  if (!usageEl) return;

  var fmt = function(n) {
    if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
    return String(n);
  };
  var inTok = d.input || 0;
  var outTok = d.output || 0;
  var totalIn = d.total_input || 0;
  var totalOut = d.total_output || 0;
  usageEl.textContent = '\u2191' + fmt(inTok) + '  \u2193' + fmt(outTok) + '  (\u2191' + fmt(totalIn) + '/\u2193' + fmt(totalOut) + ')';
};

// ===== 追加流式内容 =====
RenderMsg.appendChunk = function(text) {
  var el = RenderMsg.getOrCreateAi();
  RenderContent.processChunk(text, el);
  Utils.scrollToBottom();
};

// ===== 设置 AI 内容（HTML） =====
RenderMsg.setAiHtml = function(html) {
  var el = RenderMsg.getOrCreateAi();
  el.innerHTML = html;
  RenderContent.highlight(el);
  RenderContent.enhanceCodeBlocks(el);
  Utils.scrollToBottom();
};

// ===== 工具调用内容解析（与之前相同） =====
RenderMsg._parseToolCall = function(content) {
  var info = {name:'', args:{}, elapsed:'', rest:''};
  var c = content;
  // 提取耗时 [1.0s]
  var tm = c.match(/\[([\d.]+)s\]\s*$/);
  if (tm) { info.elapsed = tm[1]; c = c.slice(0, tm.index).trim(); }
  // 提取工具名和参数
  var pi = c.indexOf('(');
  if (pi === -1) { info.name = c; return info; }
  info.name = c.slice(0, pi).trim();
  var inner = c.slice(pi + 1);
  // 找匹配的右括号
  var depth = 1, close = -1;
  for (var i = 0; i < inner.length && depth > 0; i++) {
    if (inner[i] === '(') depth++;
    else if (inner[i] === ')') { depth--; if (depth === 0) close = i; }
  }
  if (close >= 0) {
    info.rest = inner.slice(close + 1).trim();
    inner = inner.slice(0, close);
  }
  // 解析 key=value
  inner.split(',').forEach(function(p) {
    var eq = p.indexOf('=');
    if (eq > 0) info.args[p.slice(0, eq).trim()] = p.slice(eq + 1).trim();
  });
  return info;
};

// ===== 工具调用条目（日志流风格：摘要行 + 可展开过程体） =====
RenderMsg.addTool = function(content) {
  RenderMsg._removeEmpty();
  RenderMsg.clearStatus();

  // 重置 _currentAiEl，确保后续 chunk 创建新的 content-entry
  RenderMsg._currentAiEl = null;
  RenderContent.reset();

  var entry = document.createElement('div');
  entry.className = 'log-entry';

  var info = RenderMsg._parseToolCall(content);
  var displayContent = content.replace(/\[\d+\.?\d*s\]\s*$/, '').trim();

  // 摘要行
  var summary = document.createElement('div');
  summary.className = 'process-summary tool-summary';
  summary.innerHTML =
    '<span class="tool-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg></span>' +
    '<span class="tool-name">' + Utils.E(info.name) + '</span>' +
    (info.elapsed ? '<span class="tool-time">' + info.elapsed + 's</span>' : '');

  // 详情按钮
  var detailBtn = document.createElement('button');
  detailBtn.className = 'tool-detail-btn';
  detailBtn.title = '查看完整参数';
  detailBtn.innerHTML =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:15px;height:15px">' +
    '<circle cx="12" cy="12" r="10"/>' +
    '<line x1="12" y1="16" x2="12" y2="12"/>' +
    '<line x1="12" y1="8" x2="12.01" y2="8"/>' +
    '</svg>';
  detailBtn.onclick = function(e) {
    e.stopPropagation();
    RenderMsg._showToolDetail(displayContent, entry.dataset.toolResult || '');
  };
  summary.appendChild(detailBtn);

  entry.appendChild(summary);

  // 过程体（默认收起 — 采用懒渲染策略）
  var body = document.createElement('div');
  body.className = 'process-body';
  entry.appendChild(body);

  // 缓存原始内容到 dataset，点击展开时再渲染
  entry.dataset.toolResult = '';
  entry.dataset.toolArgs = JSON.stringify(info.args);
  entry.dataset.toolRest = info.rest || '';
  entry.dataset.toolRaw = displayContent;

  // ★ 懒渲染：点击展开时首次渲染 body 内容
  summary.onclick = function(e) {
    if (e.target.closest('.tool-detail-btn')) return;
    var b = entry.querySelector('.process-body');
    if (b) {
      // 首次展开时渲染内容
      if (!b.dataset.rendered) {
        b.dataset.rendered = '1';
        var argsHtml = '';
        var argsData = {};
        try { argsData = JSON.parse(entry.dataset.toolArgs); } catch(e) {}
        for (var k in argsData) {
          argsHtml += '  ' + k + ' = ' + String(argsData[k]).slice(0, 200) + '\n';
        }
        var bodyText = '';
        if (argsHtml) bodyText += argsHtml;
        if (entry.dataset.toolRest) bodyText += entry.dataset.toolRest + '\n';
        if (!argsHtml && !entry.dataset.toolRest) {
          bodyText = entry.dataset.toolRaw;
        }
        // 工具结果（如果有）
        var result = entry.dataset.toolResult;
        if (result) {
          // 大结果截断显示
          if (result.length > 2000) {
            bodyText += '\n\u2500\u2500\u2500 返回结果 (前2000字符) \u2500\u2500\u2500\n' + result.slice(0, 2000) + '\n... (' + result.length + ' 字符)';
          } else {
            bodyText += '\n\u2500\u2500\u2500 返回结果 \u2500\u2500\u2500\n' + result;
          }
        }
        b.textContent = bodyText || '(无参数)';
      }
      b.classList.toggle('open');
    }
  };

  // 插入到消息流末尾
  var msgDiv = document.getElementById('messages');
  if (msgDiv) msgDiv.appendChild(entry);

  // 标记最近添加了 process 条目
  RenderMsg._lastWasProcess = true;

  // 大内容自动折叠提示
  if (content.length > 300 && summary) {
    // 已经默认收起，无需额外操作
  }

  Utils.scrollToBottom(true);
};

// ===== 工具调用详情浮层（与之前相同） =====
RenderMsg._showToolDetail = function(content, result) {
  var overlay = document.createElement('div');
  overlay.className = 'code-viewer-overlay';
  overlay.onclick = function(e) { if (e.target === this) close(); };
  function close() {
    if (overlay.parentNode) document.body.removeChild(overlay);
    document.removeEventListener('keydown', onKey);
  }
  function onKey(e) { if (e.key === 'Escape') close(); }
  document.addEventListener('keydown', onKey);

  var card = document.createElement('div');
  card.className = 'code-viewer-card';
  card.onclick = function(e) { e.stopPropagation(); };

  var header = document.createElement('div');
  header.className = 'code-viewer-header';
  var titleSpan = document.createElement('span');
  titleSpan.className = 'lang-tag';
  titleSpan.textContent = Utils.E(content.replace(/\(.*/, '').trim() || 'tool');
  header.appendChild(titleSpan);

  var closeBtn = document.createElement('button');
  closeBtn.className = 'code-viewer-close';
  closeBtn.innerHTML =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px">' +
    '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>' +
    '</svg>';
  closeBtn.title = '\u5173\u95ed (ESC)';
  closeBtn.onclick = close;
  header.appendChild(closeBtn);

  var body = document.createElement('div');
  body.className = 'code-viewer-body';
  var pre = document.createElement('pre');
  pre.style.cssText = 'margin:0;min-width:0';
  var codeEl = document.createElement('code');
  codeEl.className = 'language-json';
  codeEl.textContent = content;
  codeEl.style.cssText = 'display:inline-block;max-width:100%;word-break:break-word;overflow-wrap:anywhere';
  pre.appendChild(codeEl);
  body.appendChild(pre);

  if (result) {
    var resultHr = document.createElement('hr');
    resultHr.style.cssText = 'border:none;border-top:1px solid var(--border);margin:12px 0';
    body.appendChild(resultHr);
    var resultHeader = document.createElement('div');
    resultHeader.style.cssText = 'font-size:12px;color:var(--text-secondary);margin-bottom:8px';
    resultHeader.textContent = '\u8fd4\u56de\u7ed3\u679c';
    body.appendChild(resultHeader);
    var resultPre = document.createElement('pre');
    resultPre.style.cssText = 'margin:0;min-width:0;white-space:pre-wrap;overflow-wrap:anywhere;font-family:inherit;font-size:14px;line-height:1.6;color:var(--text-primary)';
    resultPre.textContent = result;
    body.appendChild(resultPre);
  }

  card.appendChild(header);
  card.appendChild(body);
  overlay.appendChild(card);
  document.body.appendChild(overlay);

  if (typeof Prism !== 'undefined') {
    try { Prism.highlightElement(codeEl); } catch(e) {}
  }
  setTimeout(function() { closeBtn.focus(); }, 50);
};

// ===== 告警消息（日志风格） =====
RenderMsg.addAlert = function(type, text) {
  RenderMsg._removeEmpty();
  RenderMsg.clearStatus();
  RenderMsg._currentAiEl = null;

  var entry = document.createElement('div');
  entry.className = 'log-entry alert-entry ' + type;
  var svg = type === 'error'
    ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px;flex-shrink:0"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>'
    : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px;flex-shrink:0"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>';
  entry.innerHTML = '<span class="alert-icon">' + svg + '</span><span>' + Utils.E(text) + '</span>';

  var msgDiv = document.getElementById('messages');
  if (msgDiv) msgDiv.appendChild(entry);
  Utils.scrollToBottom(true);
};

// ===== 状态消息 =====
RenderMsg.setStatus = function(text) {
  if (!text) { RenderMsg.clearStatus(); return; }
  if (!RenderMsg._statusEl) {
    RenderMsg._removeEmpty();
    RenderMsg._statusEl = document.createElement('div');
    RenderMsg._statusEl.className = 'log-entry status-entry';
    var msgDiv = document.getElementById('messages');
    if (msgDiv) msgDiv.appendChild(RenderMsg._statusEl);
  }
  RenderMsg._statusEl.textContent = text;
  Utils.scrollToBottom();
};

RenderMsg.clearStatus = function() {
  if (RenderMsg._statusEl && RenderMsg._statusEl.parentNode) {
    RenderMsg._statusEl.parentNode.removeChild(RenderMsg._statusEl);
  }
  RenderMsg._statusEl = null;
};

// ===== 清空消息区 =====
RenderMsg.clearAll = function() {
  RenderMsg._currentAiEl = null;
  RenderMsg.clearStatus();
  RenderMsg._lastWasProcess = false;
  RenderThink.clearAll();
  var msgDiv = document.getElementById('messages');
  if (!msgDiv) return;
  // 保留 empty-state（如果有）
  var empty = document.getElementById('empty-state');
  while (msgDiv.firstChild) msgDiv.removeChild(msgDiv.firstChild);
  if (empty) msgDiv.appendChild(empty);
};
