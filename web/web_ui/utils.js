/* utils.js — DOM 工具 + 日志 + apiFetch */
var Utils = {};

Utils.E = function(t) {
  if (!t) return '';
  return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
};

Utils.scrollToBottom = function(force) {
  var msgDiv = document.getElementById('messages');
  if (!msgDiv) return;
  if (force || msgDiv.scrollHeight - msgDiv.scrollTop - msgDiv.clientHeight < 120) {
    msgDiv.scrollTop = msgDiv.scrollHeight;
  }
  // 内容增长后同步更新按钮可见性
  var btn = document.getElementById('scroll-down-btn');
  if (btn) btn.classList.toggle('visible', msgDiv.scrollHeight - msgDiv.scrollTop - msgDiv.clientHeight >= 120);
};

Utils.logToServer = function(level, msg, data) {
  try {
    var body = {level:level, message:String(msg).slice(0,200)};
    if (data) body.data = String(data).slice(0,500);
    navigator.sendBeacon('/log', JSON.stringify(body));
  } catch(e) {}
};

// 跨浏览器复制（execCommand 主路径 + Clipboard API 回退，兼容 Android 碎片化）
// execCommand 必须在用户手势的同步流中调用，故优先于异步的 Clipboard API
Utils.copyToClipboard = function(text, onSuccess, onError) {
  // 同步主路径：execCommand（用户手势上下文中最可靠）
  var ok = Utils._execCopy(text);
  if (ok) {
    if (onSuccess) onSuccess();
    return;
  }
  // 异步回退：Clipboard API（需要安全上下文）
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(function() {
      if (onSuccess) onSuccess();
    }).catch(function(err) {
      if (onError) onError(err);
    });
  } else {
    if (onError) onError(new Error('剪贴板不可用'));
  }
};

Utils._execCopy = function(text) {
  var textarea = document.createElement('textarea');
  textarea.value = text;
  // 放在视口内（但极小），部分 WebView 对移出视口的元素拒绝交互
  textarea.style.position = 'fixed';
  textarea.style.top = '0';
  textarea.style.left = '0';
  textarea.style.width = '1px';
  textarea.style.height = '1px';
  textarea.style.opacity = '0.01';  // opacity:0 在某些 WebView 中被视为不可交互
  textarea.style.pointerEvents = 'none';
  textarea.style.zIndex = '-1';
  document.body.appendChild(textarea);
  try {
    textarea.focus();
    textarea.select();
    return document.execCommand('copy');
  } catch(err) {
    return false;
  } finally {
    document.body.removeChild(textarea);
  }
};

Utils.apiFetch = function(url, options) {
  options = options || {};
  options.headers = options.headers || {};
  // Auth token（来自 meta 标签，用于 API 安全）
  var token = (function(){
    var meta = document.querySelector('meta[name="api-token"]');
    return meta ? meta.getAttribute('content') || '' : '';
  })();
  if (token) options.headers['Authorization'] = 'Bearer ' + token;
  // Tab token（来自 sessionStorage，用于标签页隔离）
  var tabToken = '';
  try { tabToken = localStorage.getItem('tab_token') || ''; } catch(e) {}
  if (tabToken) options.headers['X-Tab-Token'] = tabToken;
  // SSE stream 的 token 需要放在 URL 里（EventSource 不支持自定义 header）
  if (url === '/stream') {
    url += (url.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(token);
    if (tabToken) url += '&tab_token=' + encodeURIComponent(tabToken);
  }
  return fetch(url, options);
};
