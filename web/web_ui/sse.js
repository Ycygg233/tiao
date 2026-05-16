/* sse.js — SSE 连接 + 事件路由 */
var SSE = {};
SSE._eventSource = null;
SSE._handlers = {};
SSE._shouldReconnect = true;

SSE.connect = function() {
  SSE._shouldReconnect = true;
  if (SSE._eventSource &&
      (SSE._eventSource.readyState === EventSource.OPEN ||
       SSE._eventSource.readyState === EventSource.CONNECTING)) return;
  var authToken = (function(){
    var meta = document.querySelector('meta[name="api-token"]');
    return meta ? meta.getAttribute('content') || '' : '';
  })();
  var tabToken = '';
  try { tabToken = localStorage.getItem('tab_token') || ''; } catch(e) {}
  var streamUrl = '/stream?token=' + encodeURIComponent(authToken);
  if (tabToken) streamUrl += '&tab_token=' + encodeURIComponent(tabToken);
  try {
    SSE._eventSource = new EventSource(streamUrl);
  } catch(e) {
    Utils.logToServer('error', 'SSE connect', String(e));
    return;
  }
  SSE._eventSource.onopen = function() {};
  SSE._eventSource.onmessage = function(e) {
    try {
      var d = JSON.parse(e.data);
      var handler = SSE._handlers[d.type];
      if (handler) handler(d);
    } catch(err) {
      Utils.logToServer('error', 'SSE parse', String(err));
    }
  };
  SSE._eventSource.onerror = function() {
    if (SSE._eventSource) { SSE._eventSource.close(); SSE._eventSource = null; }
    if (SSE._shouldReconnect) setTimeout(SSE.connect, 1500);
  };
};

SSE.disconnect = function() {
  SSE._shouldReconnect = false;
  if (SSE._eventSource) {
    SSE._eventSource.close();
    SSE._eventSource = null;
  }
};

SSE.on = function(type, handler) {
  SSE._handlers[type] = handler;
};

SSE.clearHandlers = function() {
  SSE._handlers = {};
};
