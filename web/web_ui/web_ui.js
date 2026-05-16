/* web_ui.js — 入口 + 事件绑定 */
(function() {

// ===== 侧边栏 =====
document.getElementById('header-sidebar-btn').onclick = Sidebar.toggle;
document.getElementById('sidebar-close-btn').onclick = Sidebar.close;

var overlay = document.getElementById('sidebar-overlay');
if (overlay) overlay.onclick = Sidebar.close;
var _ignoreKeyUntil = 0;

// ===== 发送 =====
document.getElementById('send-btn').onclick = function(e) { e.preventDefault(); ChatSend.send(); };
document.getElementById('input').onkeydown = function(e) {
  if (Date.now() < _ignoreKeyUntil) return;
  if (e.key === 'Enter' && e.ctrlKey) { e.preventDefault(); ChatSend.send(); }
  else if (e.key === 'Enter' && !e.shiftKey) { /* Enter = 换行，textarea 默认行为 */ }
  if (e.key === 'Escape' && ChatSend._sending) ChatSend.cancel();
};
document.getElementById('input').oninput = function() {
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 120) + 'px';
};

// 全局快捷键
document.addEventListener('keydown', function(e) {
  if (e.key === '/' && !e.ctrlKey && !e.metaKey &&
      document.activeElement !== document.getElementById('input') &&
      !e.target.closest('#settings-overlay')) {
    e.preventDefault();
    document.getElementById('input').focus();
  }
});

// ===== 深度思考标签 =====
document.getElementById('tag-think').onclick = function() {
  ChatSend.tags.thinking = !ChatSend.tags.thinking;
  this.classList.toggle('active');
};

// ===== 模型切换（Flash ↔ Pro）=====
document.getElementById('tag-model').onclick = function() {
  var label = document.getElementById('tag-model-label');
  var isPro = ChatSend.tags.model === 'deepseek-v4-pro';
  ChatSend.tags.model = isPro ? 'deepseek-v4-flash' : 'deepseek-v4-pro';
  label.textContent = isPro ? 'Flash' : 'Pro';
  this.classList.toggle('active', !isPro);
};

// ===== 模型面板 → 已改为历史会话面板 =====
Panel.openSessions = function() {
  var panel = document.getElementById('sessions-panel');
  if (!panel) return;
  panel.classList.add('open');
  Panel.loadSessions();
  var input = document.getElementById('sessions-search');
  if (input) input.value = '';
};
Panel.closeSessions = function() {
  var panel = document.getElementById('sessions-panel');
  if (panel) panel.classList.remove('open');
};
// 更新顶栏标签（状态机：历史会话/对话标题/新会话）
Panel.setSessionLabel = function(name) {
  var el = document.getElementById('header-model');
  if (!el) return;
  if (!name) el.textContent = '新会话';
  else if (name === 'history') el.textContent = '历史会话';
  else el.textContent = name.length > 18 ? name.slice(0, 18) + '…' : name;
};
Panel._sessionsCache = [];
Panel.loadSessions = function() {
  Utils.apiFetch('/sessions?offset=0&limit=50').then(function(r) { return r.json(); }).then(function(d) {
    Panel._sessionsCache = d.sessions || [];
    Panel._renderSessions();
  }).catch(function(){});
};
Panel._selectedIds = {};
Panel._renderSessions = function() {
  var list = document.getElementById('sessions-list');
  if (!list) return;
  var filter = (document.getElementById('sessions-search') && document.getElementById('sessions-search').value || '').toLowerCase();
  var filtered = Panel._sessionsCache.filter(function(s) {
    return (s.title || s.name || '').toLowerCase().indexOf(filter) !== -1;
  });
  list.innerHTML = '';
  if (!filtered.length) {
    list.innerHTML = '<div style="text-align:center;padding:24px;color:var(--text-secondary);font-size:14px">暂无历史会话</div>';
    document.getElementById('sessions-batch').style.display = 'none';
    return;
  }
  // 显示批量工具条
  var batchBar = document.getElementById('sessions-batch');
  if (batchBar) batchBar.style.display = 'flex';
  // 渲染会话项
  filtered.forEach(function(s) {
    var name = s.title || s.name;
    var div = document.createElement('div');
    div.className = 'model-item';
    // 勾选框
    var cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.style.width = '16px';
    cb.style.height = '16px';
    cb.style.accentColor = 'var(--accent-cyan)';
    cb.style.cursor = 'pointer';
    cb.style.flexShrink = '0';
    cb.checked = !!Panel._selectedIds[s.id];
    cb.onclick = function(e) { e.stopPropagation(); };
    cb.onchange = function() {
      if (cb.checked) Panel._selectedIds[s.id] = true;
      else delete Panel._selectedIds[s.id];
      document.getElementById('sessions-select-all').checked = 
        Object.keys(Panel._selectedIds).length === filtered.length;
    };
    div.appendChild(cb);
    // 会话名
    var nameSpan = document.createElement('span');
    nameSpan.className = 'model-name';
    nameSpan.textContent = name;
    nameSpan.style.flex = '1';
    nameSpan.style.cursor = 'pointer';
    nameSpan.onclick = function() {
      Utils.apiFetch('/sessions/switch', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id: s.id})})
        .then(function(r) { return r.json(); }).then(function(d) {
          if (d.error) return;
          Panel.closeSessions();
          Panel.setSessionLabel(name);
          RenderMsg.clearAll();
          if (d.messages) {
            // 单向遍历：按消息顺序生成 DOM，每条 assistant 消息前加 source-label
            var _toolResultIdx = 0;
            var _toolEntries = [];
            d.messages.forEach(function(m) {
              if (m.role === 'user' && m.content) {
                RenderMsg.addUser(m.content);
              }
              else if (m.role === 'assistant') {
                // 来源标识
                var _ts = '';
                if (m.timestamp) {
                  var _d = new Date(m.timestamp);
                  _ts = ('0' + _d.getHours()).slice(-2) + ':' + ('0' + _d.getMinutes()).slice(-2);
                }
                RenderMsg.addSourceLabel('DeepSeek', _ts);

                // 处理思考内容
                if (m.reasoning_content) {
                  var _hid = 'hist-' + Date.now() + '-' + Math.random().toString(36).slice(2,6);
                  var _thinkKey = RenderThink.create(_hid);
                  if (_thinkKey) {
                    var _thinkEntry = RenderThink._panels[_thinkKey];
                    if (_thinkEntry) {
                      var _body = _thinkEntry.querySelector('.process-body');
                      if (_body) _body.textContent = m.reasoning_content;
                      // 更新摘要行
                      var _summary = _thinkEntry.querySelector('.thinking-summary');
                      if (_summary) {
                        var _label = _summary.querySelector('.think-label');
                        if (_label) {
                          var _fl = m.reasoning_content.split('\n')[0].trim();
                          if (_fl.length > 60) _fl = _fl.slice(0, 60) + '\u2026';
                          _label.textContent = _fl || '思考过程';
                        }
                        var _status = _summary.querySelector('.think-status');
                        if (_status) _status.textContent = '\u2713 完成';
                        _summary.classList.remove('expanded');
                      }
                      // 完成后收起
                      if (_body) _body.classList.remove('open');
                      _thinkEntry.classList.add('done');
                    }
                  }
                }

                // 处理正文内容
                if (m.content) {
                  RenderMsg.getOrCreateAi();
                  RenderMsg.setAiHtml(RenderContent.parseMarkdown(m.content));
                }

                // 处理 tool_calls（紧跟当前 assistant）
                if (m.tool_calls) {
                  m.tool_calls.forEach(function(tc) {
                    if (!tc.function) return;
                    var args = {};
                    try { args = JSON.parse(tc.function.arguments); } catch(e) {}
                    var argStr = Object.keys(args).map(function(k) { return k + '=' + String(args[k]).slice(0,80); }).join(', ');
                    RenderMsg.addTool(tc.function.name + '(' + argStr + ')');
                    // 记录最后一个 tool entry，用于后续 tool result 配对
                    _toolEntries.push(document.querySelector('.log-entry:last-child'));
                  });
                }
              }
              else if (m.role === 'tool' && m.content) {
                // 配对 tool result
                var _targetEntry = _toolEntries[_toolResultIdx];
                if (_targetEntry) {
                  _targetEntry.dataset.toolResult = m.content;
                }
                _toolResultIdx++;
              }
            });
          }
        }).catch(function(){});
    };
    div.appendChild(nameSpan);
    // 三点菜单
    (function(sid, btnDiv) {
      var btn = document.createElement('button');
      btn.className = 'session-dot-btn';
      btn.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><circle cx="12" cy="5" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="12" cy="19" r="2"/></svg>';
      btn.onclick = function(e) {
        e.stopPropagation();
        var menu = document.getElementById('session-menu');
        var rect = btn.getBoundingClientRect();
        menu.style.display = 'block';
        menu.style.top = (rect.bottom + 4) + 'px';
        menu.style.right = (window.innerWidth - rect.right) + 'px';
        menu.dataset.sid = sid;
      };
      btnDiv.appendChild(btn);
    })(s.id, div);
    list.appendChild(div);
  });
};
// 全选
document.getElementById('sessions-select-all').onchange = function() {
  var filter = (document.getElementById('sessions-search') && document.getElementById('sessions-search').value || '').toLowerCase();
  var filtered = Panel._sessionsCache.filter(function(s) {
    return (s.title || s.name || '').toLowerCase().indexOf(filter) !== -1;
  });
  if (this.checked) {
    filtered.forEach(function(s) { Panel._selectedIds[s.id] = true; });
  } else {
    Panel._selectedIds = {};
  }
  Panel._renderSessions();
};
// 删除选中
document.getElementById('sessions-delete-btn').onclick = function() {
  var ids = Object.keys(Panel._selectedIds);
  if (!ids.length) return;
  Panel.showConfirm('确认删除 ' + ids.length + ' 个会话？此操作不可撤销。', function(ok) {
    if (!ok) return;
    var done = 0;
    ids.forEach(function(id) {
      Utils.apiFetch('/sessions/delete', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id: parseInt(id)})})
        .then(function() {
          done++;
          if (done === ids.length) {
            Panel._selectedIds = {};
            Panel.loadSessions();
          }
        }).catch(function(){});
    });
  });
};
// 重命名选中
document.getElementById('sessions-rename-btn').onclick = function() {
  var ids = Object.keys(Panel._selectedIds);
  if (!ids.length) return;
  var overlay = document.getElementById('rename-overlay');
  var input = document.getElementById('rename-input');
  if (!overlay || !input) return;
  input.value = '';
  overlay.style.display = 'flex';
  setTimeout(function() { input.focus(); }, 100);
  // 保存时统一处理
  var onSave = function() {
    var newTitle = input.value.trim();
    if (!newTitle) { input.focus(); return; }
    overlay.style.display = 'none';
    var done = 0;
    ids.forEach(function(id) {
      var s = Panel._sessionsCache.find(function(s) { return s.id === parseInt(id); });
      if (!s) { done++; return; }
      Utils.apiFetch('/sessions/rename', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({name: s.name, title: newTitle})
      }).then(function() {
        done++;
        if (done === ids.length) {
          Panel._selectedIds = {};
          Panel.loadSessions();
        }
      }).catch(function(){ done++; });
    });
  };
  document.getElementById('rename-save').onclick = onSave;
  document.getElementById('rename-cancel').onclick = function() { overlay.style.display = 'none'; };
  input.onkeydown = function(e) { if (e.key === 'Enter') onSave(); if (e.key === 'Escape') overlay.style.display = 'none'; };
  overlay.onclick = function(e) { if (e.target === overlay) overlay.style.display = 'none'; };
};
// 关闭按钮绑定
document.getElementById('sessions-panel-close').onclick = Panel.closeSessions;
// 搜索会话（客户端过滤）
document.getElementById('sessions-search').oninput = function() {
  Panel._renderSessions();
};
// 点击空白关闭会话面板
document.addEventListener('click', function(e) {
  var panel = document.getElementById('sessions-panel');
  if (panel && panel.classList.contains('open') && !panel.contains(e.target) &&
      e.target !== document.getElementById('header-model-btn') &&
      !document.getElementById('header-model-btn').contains(e.target)) {
    Panel.closeSessions();
  }
});
// 点击模型按钮打开会话面板
document.getElementById('header-model-btn').onclick = Panel.openSessions;

// 会话参数已放在侧边栏 body 中

// ===== 顶栏新建会话 =====
document.getElementById('header-new-btn').onclick = function() {
  Utils.apiFetch('/new', {method:'POST', headers:{'Content-Type':'application/json'}}).then(function() {
    RenderMsg.clearAll();
    Panel.setSessionLabel('');
  }).catch(function(){});
};

// ===== 设置面板 =====
document.getElementById('settings-btn').onclick = Panel.openSettings;
// 关闭：背景点击 + 关闭按钮
document.getElementById('settings-overlay').onclick = function(e) {
  if (e.target === this) Panel.closeSettings();
};
document.getElementById('op-close-btn').onclick = Panel.closeSettings;

// ===== 服务端设置 =====
document.getElementById('op-restart').onclick = function() {
  Utils.apiFetch('/restart', {method:'POST'}).catch(function(){});
};
document.getElementById('op-shutdown').onclick = function() {
  Utils.apiFetch('/shutdown', {method:'POST'}).catch(function(){});
};
document.getElementById('op-about').onclick = function() {
  window.open('https://github.com/your-username/tiao', '_blank');
};

// ===== 主题切换 =====
var themeBtn = document.getElementById('theme-btn');
if (themeBtn) {
  themeBtn.onclick = function() {
    var html = document.documentElement;
    var cur = html.getAttribute('data-theme') || 'light';
    var next = cur === 'dark' ? 'light' : 'dark';
    html.setAttribute('data-theme', next);
    try { localStorage.setItem('tiao_theme', next); } catch(e) {}
  };
  // 恢复上次主题
  try {
    var saved = localStorage.getItem('tiao_theme');
    if (saved) document.documentElement.setAttribute('data-theme', saved);
  } catch(e) {}
}

// ===== 侧边栏设置：温度 =====
var ssTemp = document.getElementById('ss-temp-slider');
if (ssTemp) {
  ssTemp.oninput = function() {
    ChatSend.tags.temperature = parseFloat(this.value);
    var val = document.getElementById('ss-temp-val');
    if (val) val.textContent = this.value;
  };
}

// ===== 侧边栏设置：top_p =====
var ssTopp = document.getElementById('ss-topp-slider');
if (ssTopp) {
  ssTopp.oninput = function() {
    ChatSend.tags.top_p = parseFloat(this.value);
    var val = document.getElementById('ss-topp-val');
    if (val) val.textContent = this.value;
  };
}
var ssToppToggle = document.getElementById('ss-topp-toggle');
if (ssToppToggle) {
  ssToppToggle.onclick = function() {
    var on = this.classList.toggle('active');
    this.textContent = on ? '开' : '关';
    document.getElementById('ss-topp-row').classList.toggle('disabled', !on);
    var slider = document.getElementById('ss-topp-slider');
    slider.disabled = !on;
    ChatSend.tags.top_p = on ? parseFloat(slider.value) : null;
  };
}

// ===== 侧边栏设置：场景预设 =====
document.getElementById('ss-presets').onclick = function(e) {
  var btn = e.target.closest('.ss-preset');
  if (!btn) return;
  document.querySelectorAll('.ss-preset').forEach(function(b) { b.classList.remove('active'); });
  btn.classList.add('active');
  ChatSend.tags.profile = btn.getAttribute('data-profile');
};

// ===== 侧边栏设置：思考深度 =====
document.getElementById('ss-reasoning').onclick = function(e) {
  var btn = e.target.closest('.ss-preset');
  if (!btn) return;
  document.querySelectorAll('#ss-reasoning .ss-preset').forEach(function(b) { b.classList.remove('active'); });
  btn.classList.add('active');
  ChatSend.tags.reasoning_effort = btn.getAttribute('data-effort');
};

// ===== Sudo 提权 =====
document.getElementById('ss-sudo').onclick = function(e) {
  var btn = e.target.closest('.ss-preset');
  if (!btn) return;
  var level = btn.getAttribute('data-level');
  Utils.apiFetch('/sudo', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({level: level, persist: document.getElementById('ss-sudo-persist').textContent === '开'})})
    .then(function() {
      document.querySelectorAll('#ss-sudo .ss-preset').forEach(function(b) { b.classList.remove('active'); });
      btn.classList.add('active');
    }).catch(function(){});
};
document.getElementById('ss-sudo-persist').onclick = function() {
  var on = this.textContent === '开';
  this.textContent = on ? '关' : '开';
  this.classList.toggle('active', !on);
};
// 初始化：从后端加载当前权限状态
(function() {
  Utils.apiFetch('/sudo').then(function(r) { return r.json(); }).then(function(d) {
    if (d.level) {
      var btn = document.querySelector('#ss-sudo [data-level="' + d.level + '"]');
      if (btn) {
        document.querySelectorAll('#ss-sudo .ss-preset').forEach(function(b) { b.classList.remove('active'); });
        btn.classList.add('active');
      }
    }
    if (d.persist) {
      var pBtn = document.getElementById('ss-sudo-persist');
      if (pBtn) { pBtn.textContent = '开'; pBtn.classList.add('active'); }
    }
  }).catch(function(){});
})();

// ===== 确认弹窗 =====
document.getElementById('confirm-ok').onclick = function() { Panel._onConfirm(true); };
document.getElementById('confirm-cancel').onclick = function() { Panel._onConfirm(false); };

// 确认弹窗逻辑
Panel._confirmCallback = null;
Panel._onConfirm = function(result) {
  var cb = Panel._confirmCallback;
  Panel._confirmCallback = null;
  document.getElementById('confirm-overlay').classList.remove('active');
  if (cb) cb(result);
};
// 暴露给工具调用等需要确认的场景
Panel.showConfirm = function(msg, callback) {
  document.getElementById('confirm-desc').textContent = msg;
  Panel._confirmCallback = callback || null;
  document.getElementById('confirm-overlay').classList.add('active');
};

// ===== 工具管理 =====
document.getElementById('ss-tools-entry').onclick = Panel.openTools;

// ===== 会话菜单 =====
document.getElementById('session-menu-regenerate').onclick = function() {
  var menu = document.getElementById('session-menu');
  var sid = menu.dataset.sid;
  if (!sid) return;
  menu.style.display = 'none';
  Utils.apiFetch('/sessions/regenerate-title', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({id: parseInt(sid)})
  }).then(function(r) { return r.json(); }).then(function(d) {
    if (d.status === 'ok') Panel.loadSessions();
  }).catch(function(){});
};
// 点击空白关闭会话菜单
document.addEventListener('click', function(e) {
  var menu = document.getElementById('session-menu');
  if (menu && menu.style.display !== 'none' && !menu.contains(e.target) && !e.target.closest('.session-dot-btn')) {
    menu.style.display = 'none';
  }
});

// ===== 展开输入面板 =====
(function() {
  var expandBtn = document.getElementById('expand-btn');
  var overlay = document.getElementById('input-expand-overlay');
  var closeBtn = document.getElementById('input-expand-close');
  var expTextarea = document.getElementById('input-expand-textarea');
  var mainInput = document.getElementById('input');
  var expSend = document.getElementById('input-expand-send');

  if (!expandBtn || !overlay) return;

  function openExpand() {
    expTextarea.value = mainInput.value;
    overlay.classList.add('open');
    setTimeout(function() { expTextarea.focus(); }, 50);
  }

  function closeExpand() {
    _ignoreKeyUntil = Date.now() + 200;
    mainInput.value = expTextarea.value;
    overlay.classList.remove('open');
    mainInput.style.height = 'auto';
    mainInput.style.height = Math.min(mainInput.scrollHeight, 120) + 'px';
    setTimeout(function() { mainInput.focus(); }, 50);
  }

  expandBtn.onclick = openExpand;
  closeBtn.onclick = closeExpand;
  overlay.onclick = function(e) { if (e.target === overlay) closeExpand(); };

  // 展开态 textarea 实时同步到主输入
  expTextarea.oninput = function() {
    mainInput.value = this.value;
  };

  // 展开态发送
  expSend.onclick = function() {
    _ignoreKeyUntil = Date.now() + 200;
    closeExpand();
    setTimeout(function() { ChatSend.send(); }, 100);
  };

  // 展开态快捷键
  expTextarea.onkeydown = function(e) {
    if (e.key === 'Enter' && e.ctrlKey) { e.preventDefault(); _ignoreKeyUntil = Date.now() + 200; closeExpand(); setTimeout(function() { ChatSend.send(); }, 100); }
    if (e.key === 'Escape') { closeExpand(); }
  };

  // 展开态标签同步
  var expThink = document.getElementById('exp-tag-think');
  var expModel = document.getElementById('exp-tag-model');
  var expModelLabel = document.getElementById('exp-tag-model-label');
  if (expThink) {
    expThink.onclick = function() {
      var mainThink = document.getElementById('tag-think');
      if (mainThink) { mainThink.click(); }
      this.classList.toggle('active');
    };
  }
  if (expModel) {
    expModel.onclick = function() {
      var mainModel = document.getElementById('tag-model');
      if (mainModel) { mainModel.click(); }
      // 同步标签文字
      var mainLabel = document.getElementById('tag-model-label');
      if (mainLabel && expModelLabel) expModelLabel.textContent = mainLabel.textContent;
    };
  }
})();

// ===== 滚动监听 =====
(function() {
  var msgDiv = document.getElementById('messages');
  var btn = document.getElementById('scroll-down-btn');
  if (!msgDiv || !btn) return;
  msgDiv.addEventListener('scroll', function() {
    var atBottom = msgDiv.scrollHeight - msgDiv.scrollTop - msgDiv.clientHeight < 120;
    btn.classList.toggle('visible', !atBottom);
  });
})();

// ===== 初始化 =====
// ★ 应用日志流样式
(function() {
  var msgDiv = document.getElementById('messages');
  if (msgDiv) msgDiv.classList.add('chat-stream');
})();

// ★ 修复：每次刷新页面都获取新 token（localStorage 里的旧 token 可能已失效）
Utils.apiFetch('/new_tab', {method:'POST'}).then(function(r) { return r.json(); }).then(function(d) {
  if (d.token) {
    try { localStorage.setItem('tab_token', d.token); } catch(e) {}
  }
  SSE.connect();
}).catch(function() {
  // 降级：用旧 token 尝试
  SSE.connect();
});

})();
