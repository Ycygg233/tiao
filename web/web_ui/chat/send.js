/* chat/send.js — 发送调度 */
var ChatSend = {};
ChatSend._sending = false;
ChatSend._sessionSeq = 0;
ChatSend._replyTimeout = null;

// 状态标签（前端维护，随请求发送）
ChatSend.tags = {
  thinking: false,
  model: '',
  temperature: null,
  top_p: null,
  reasoning_effort: 'high',
  profile: '',
  tools: null  // {tool_name: bool, ...}
};

ChatSend.send = function() {
  if (ChatSend._sending) return;
  var input = document.getElementById('input');
  if (!input) return;
  var text = input.value.trim();
  if (!text) { input.focus(); return; }

  ChatSend._sending = true;
  ChatSend._sessionSeq++;
  var thisSeq = ChatSend._sessionSeq;
  var msgDiv = document.getElementById('messages');

  // 重置 SSE + 思考面板，准备新一轮
  SSE.disconnect();
  SSE.clearHandlers();
  // 容错：think.js 可能未加载
  if (typeof RenderThink !== 'undefined' && RenderThink.setCurrentId) {
    RenderThink.setCurrentId(thisSeq);
  }

  // 清输入 + 加用户消息
  input.value = '';
  input.style.height = 'auto';
  RenderMsg.addUser(text);
  if (msgDiv) msgDiv.classList.add('streaming');

  // 发送/取消 二合一按钮
  var sendBtn = document.getElementById('send-btn');
  if (sendBtn) {
    sendBtn.disabled = false;
    sendBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>';
    sendBtn.onclick = ChatSend.cancel;
  }

  // Header 标题（取首条消息前 20 字做临时标题）
  if (typeof Panel !== 'undefined') {
    Panel.setSessionLabel(text.slice(0,15) + (text.length > 15 ? '...' : ''));
  }

  // ★ 添加来源标识（日志流风格）
  if (typeof RenderMsg !== 'undefined' && RenderMsg.addSourceLabel) {
    var now = new Date();
    var timeStr = ('0' + now.getHours()).slice(-2) + ':' + ('0' + now.getMinutes()).slice(-2);
    RenderMsg.addSourceLabel('DeepSeek', timeStr);
  }

  // 思考中
  RenderMsg.setStatus('思考中\u2026');

  // 超时
  if (ChatSend._replyTimeout) clearTimeout(ChatSend._replyTimeout);
  ChatSend._replyTimeout = setTimeout(function() {
    ChatSend._replyTimeout = null;
    if (ChatSend._sending) {
      RenderMsg.addAlert('warn', '\u54cd\u5e94\u8d85\u65f6\uff0c\u8bf7\u91cd\u8bd5');
      ChatSend._finish();
    }
  }, 120000);

  // SSE 订阅
  try {
    SSE.connect();
    SSE.on('think', function(d) { if (ChatSend.tags.thinking && typeof RenderThink !== 'undefined') RenderThink.append(d.content || ''); });
    SSE.on('think_done', function() { if (ChatSend.tags.thinking && typeof RenderThink !== 'undefined') RenderThink.done(); });
    SSE.on('chunk', function(d) {
      if (d.content) RenderMsg.appendChunk(d.content);
    });
    SSE.on('message', function(d) {
      if (d.content) RenderMsg.setAiHtml(RenderContent.parseMarkdown(d.content));
    });
    SSE.on('tool', function(d) { RenderMsg.addTool(d.content || ''); });
    SSE.on('error', function(d) { RenderMsg.addAlert('error', d.content || ''); });
    SSE.on('warn', function(d) { RenderMsg.addAlert('warn', d.content || ''); });
    SSE.on('status', function(d) { RenderMsg.setStatus(d.content || ''); });
    SSE.on('stats', function(d) { RenderMsg.setStatus(d.content || ''); });
    SSE.on('usage', function(d) {
      RenderMsg.updateUsage(d);
    });
    SSE.on('title', function(d) {
      if (d.content && typeof Panel !== 'undefined') {
        Panel.setSessionLabel(d.content);
      }
    });
    SSE.on('done', function() { ChatSend._finish(); });
  } catch(e) {
    ChatSend._finish();
    return;
  }

  // 组装标签
  var body = {
    message: text,
    thinking: ChatSend.tags.thinking,
    model: ChatSend.tags.model || undefined,
    stream_output: true
  };
  if (ChatSend.tags.temperature !== null) body.temperature = ChatSend.tags.temperature;
  if (ChatSend.tags.top_p !== null) body.top_p = ChatSend.tags.top_p;
  body.reasoning_effort = ChatSend.tags.reasoning_effort;
  if (ChatSend.tags.profile) body.profile = ChatSend.tags.profile;
  if (ChatSend.tags.tools) body.tools = ChatSend.tags.tools;

  // 发送
  Utils.apiFetch('/chat', {
    method: 'POST',
    body: JSON.stringify(body),
    headers: {'Content-Type': 'application/json'}
  }).then(function(r) {
    if (!r.ok) { throw new Error('HTTP ' + r.status); }
    return r.json();
  }).then(function(d) {
    if (d.error) {
      RenderMsg.addAlert('error', d.error);
      ChatSend._finish();
    }
  }).catch(function(e) {
    RenderMsg.addAlert('error', '\u53d1\u9001\u5931\u8d25: ' + e.message);
    ChatSend._finish();
  });
};

ChatSend.cancel = function() {
  if (!ChatSend._sending) return;
  Utils.apiFetch('/cancel', {method:'POST'}).catch(function(){});
  ChatSend._finish();
  RenderMsg.addAlert('warn', '\u5df2\u53d6\u6d88\u53d1\u9001');
};

ChatSend._finish = function() {
  if (ChatSend._replyTimeout) { clearTimeout(ChatSend._replyTimeout); ChatSend._replyTimeout = null; }
  ChatSend._sending = false;
  SSE.disconnect();
  RenderMsg.clearStatus();

  var sendBtn = document.getElementById('send-btn');
  if (sendBtn) {
    sendBtn.disabled = false;
    sendBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="width:18px;height:18px"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>';
    sendBtn.onclick = ChatSend.send;
  }

  RenderContent.flushMarkdown();
  var msgDiv = document.getElementById('messages');
  if (msgDiv) msgDiv.classList.remove('streaming');
  Utils.scrollToBottom(true);
};
