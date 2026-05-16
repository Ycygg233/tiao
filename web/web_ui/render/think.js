/* render/think.js — 思考面板（日志流风格：摘要行 + 可展开过程体） */
var RenderThink = {};
RenderThink._panels = {};
RenderThink._currentId = null;
RenderThink._thinkSeq = 0;

RenderThink.setCurrentId = function(id) {
  RenderThink._currentId = id;
};

/**
 * 创建一个思考条目（日志流风格）
 * @param {*} id  会话序列号，null 时用 _currentId
 * @returns {string} 面板的 key，用于后续 append/done
 */
RenderThink.create = function(id) {
  var sessionKey = id != null ? id : RenderThink._currentId;
  if (sessionKey == null) return;
  RenderThink._thinkSeq++;
  var key = sessionKey + '-' + RenderThink._thinkSeq;

  // 创建外层 .log-entry
  var entry = document.createElement('div');
  entry.className = 'log-entry';
  entry.dataset.thinkKey = key;

  // 摘要行
  var summary = document.createElement('div');
  summary.className = 'process-summary thinking-summary expanded';
  summary.innerHTML =
    '<span class="thinking-chevron">\u25be</span>' +
    '<span class="think-label">思考中\u2026</span>' +
    '<span class="think-status">\u25cf 进行中</span>';

  // 点击切换展开/收起
  summary.onclick = function(e) {
    // 不拦截 tool-detail-btn 的点击
    if (e.target.closest('.tool-detail-btn')) return;
    var body = entry.querySelector('.process-body');
    if (body) {
      body.classList.toggle('open');
      summary.classList.toggle('expanded');
    }
  };
  entry.appendChild(summary);

  // 过程体（默认展开）
  var body = document.createElement('div');
  body.className = 'process-body open';
  entry.appendChild(body);

  // 追加到消息流末尾
  var msgDiv = document.getElementById('messages');
  if (msgDiv) {
    // 移除尾部 status/alert 等辅助元素前的插入
    msgDiv.appendChild(entry);
  }

  RenderThink._panels[key] = entry;
  Utils.scrollToBottom();
  return key;
};

/**
 * 追加思考文本
 */
RenderThink.append = function(text) {
  var sessionKey = RenderThink._currentId;
  if (sessionKey == null) return;
  var keys = Object.keys(RenderThink._panels).filter(function(k) {
    return k.startsWith(sessionKey + '-');
  });
  if (!keys.length) {
    RenderThink.create(sessionKey);
    keys = Object.keys(RenderThink._panels).filter(function(k) {
      return k.startsWith(sessionKey + '-');
    });
  }
  var lastKey = keys[keys.length - 1];
  var entry = RenderThink._panels[lastKey];

  // 如果最后一个面板已完成，新建面板承接后续思考
  if (entry && entry.classList.contains('done')) {
    RenderThink.create(sessionKey);
    keys = Object.keys(RenderThink._panels).filter(function(k) {
      return k.startsWith(sessionKey + '-');
    });
    lastKey = keys[keys.length - 1];
    entry = RenderThink._panels[lastKey];
  }
  if (!entry) return;

  var body = entry.querySelector('.process-body');
  if (body) body.textContent += text;

  // 更新摘要行：取第一行作为摘要
  var summary = entry.querySelector('.thinking-summary');
  if (summary) {
    var label = summary.querySelector('.think-label');
    if (label) {
      var fullText = body ? body.textContent : '';
      var firstLine = fullText.split('\n')[0].trim();
      if (firstLine.length > 60) firstLine = firstLine.slice(0, 60) + '\u2026';
      if (firstLine) label.textContent = firstLine;
    }
  }

  Utils.scrollToBottom();
};

/**
 * 思考完成
 */
RenderThink.done = function() {
  var sessionKey = RenderThink._currentId;
  if (sessionKey == null) return;
  var keys = Object.keys(RenderThink._panels).filter(function(k) {
    return k.startsWith(sessionKey + '-');
  });
  if (!keys.length) return;
  var lastKey = keys[keys.length - 1];
  var entry = RenderThink._panels[lastKey];
  if (!entry) return;

  entry.classList.add('done');
  var summary = entry.querySelector('.thinking-summary');
  if (summary) {
    var status = summary.querySelector('.think-status');
    if (status) status.textContent = '\u2713 完成';
    // 完成后自动收起
    summary.classList.remove('expanded');
    var body = entry.querySelector('.process-body');
    if (body) body.classList.remove('open');
  }
};

/**
 * 清空所有思考面板
 */
RenderThink.clearAll = function() {
  Object.keys(RenderThink._panels).forEach(function(key) {
    var entry = RenderThink._panels[key];
    if (entry && entry.parentNode) {
      entry.parentNode.removeChild(entry);
    }
    delete RenderThink._panels[key];
  });
  RenderThink._currentId = null;
  RenderThink._thinkSeq = 0;
};
