/* panel.js — 浮层面板 */
var Panel = {};

// ===== 侧边栏 =====
var Sidebar = {};
Sidebar.toggle = function() {
  var el = document.getElementById('sidebar');
  if (!el) return;
  if (window.innerWidth >= 768) el.classList.toggle('collapsed');
  else {
    el.classList.toggle('open');
    var ov = document.getElementById('sidebar-overlay');
    if (ov) ov.style.display = el.classList.contains('open') ? 'block' : 'none';
  }
};
Sidebar.close = function() {
  var el = document.getElementById('sidebar');
  if (!el) return;
  if (window.innerWidth >= 768) el.classList.add('collapsed');
  else el.classList.remove('open');
  var ov = document.getElementById('sidebar-overlay');
  if (ov) ov.style.display = 'none';
};

// ===== 设置 =====
Panel.openSettings = function() {
  var el = document.getElementById('settings-overlay');
  if (el) el.style.display = 'flex';
};
Panel.closeSettings = function() {
  var el = document.getElementById('settings-overlay');
  if (el) el.style.display = 'none';
};

// ===== 模型初始化（#tag-model 使用） =====
ChatSend.tags.model = 'deepseek-v4-flash';

// ===== 会话参数已在侧边栏 =====

// ===== 工具管理 =====
Panel._toolsCache = [];
Panel._toolsState = {};

Panel.openTools = function() {
  var panel = document.getElementById('tools-panel');
  if (panel) panel.style.display = 'block';
  Panel._loadTools();
};

Panel.closeTools = function() {
  var panel = document.getElementById('tools-panel');
  if (panel) panel.style.display = 'none';
};

Panel._loadTools = function() {
  // 从后端获取可用工具列表 — 先用内置列表（后续可扩展为 API）
  var builtinTools = [
    {name:'read_file', desc:'读取文件', write:false, defaultOn:true},
    {name:'write_file', desc:'写入文件', write:true, defaultOn:true},
    {name:'scan_dir', desc:'扫描目录', write:false, defaultOn:true},
    {name:'find', desc:'搜索文件', write:false, defaultOn:true},
    {name:'grep_symbol', desc:'查找符号', write:false, defaultOn:true},
    {name:'path_info', desc:'路径详情', write:false, defaultOn:true},
    {name:'create_dir', desc:'创建目录', write:true, defaultOn:true},
    {name:'replace', desc:'替换内容', write:true, defaultOn:true},
    {name:'delete', desc:'删除文件', write:true, defaultOn:true},
    {name:'rename', desc:'重命名', write:true, defaultOn:true},
    {name:'run_python', desc:'运行 Python', write:true, defaultOn:true},
    {name:'search_web', desc:'搜索网页', write:false, defaultOn:true},
    {name:'local_search', desc:'本地搜索', write:false, defaultOn:true},
    {name:'paste', desc:'读取剪贴板', write:false, defaultOn:true}
  ];
  Panel._toolsCache = builtinTools;
  // 初始化状态（未持久化过的取默认值）
  builtinTools.forEach(function(t) {
    if (Panel._toolsState[t.name] === undefined) {
      Panel._toolsState[t.name] = t.defaultOn;
    }
  });
  Panel._renderTools();
};

Panel._renderTools = function() {
  var list = document.getElementById('tools-list');
  if (!list) return;
  list.innerHTML = '';
  Panel._toolsCache.forEach(function(t) {
    var on = Panel._toolsState[t.name] !== false;
    var writeBadge = t.write ? ' <span style="font-size:10px;color:var(--accent-yellow);opacity:0.6">写</span>' : '';
    var row = document.createElement('div');
    row.className = 'model-item';
    row.style.display = 'flex';
    row.style.alignItems = 'center';
    row.style.padding = '8px 14px';
    row.style.gap = '8px';
    // 名称
    var nameSpan = document.createElement('span');
    nameSpan.className = 'model-name';
    nameSpan.style.flex = '1';
    nameSpan.innerHTML = Utils.E(t.name) + writeBadge;
    row.appendChild(nameSpan);
    // 描述
    var descSpan = document.createElement('span');
    descSpan.style.fontSize = '11px';
    descSpan.style.color = 'var(--text-secondary)';
    descSpan.textContent = t.desc;
    row.appendChild(descSpan);
    // Toggle 开关
    var toggle = document.createElement('button');
    toggle.className = 'mini-toggle' + (on ? ' active' : '');
    toggle.textContent = on ? '开' : '关';
    toggle.style.flexShrink = '0';
    (function(toolName) {
      toggle.onclick = function(e) {
        e.stopPropagation();
        Panel._toggleTool(toolName);
      };
    })(t.name);
    row.appendChild(toggle);
    list.appendChild(row);
  });
};

Panel._toggleTool = function(name) {
  var current = Panel._toolsState[name];
  Panel._toolsState[name] = current === false ? true : false;
  Panel._renderTools();
  // 同步到 ChatSend.tags
  if (typeof ChatSend !== 'undefined' && ChatSend.tags) {
    if (!ChatSend.tags.tools) ChatSend.tags.tools = {};
    ChatSend.tags.tools[name] = Panel._toolsState[name];
  }
};

Panel.toggleAllTools = function(on) {
  Panel._toolsCache.forEach(function(t) {
    Panel._toolsState[t.name] = on;
  });
  Panel._renderTools();
  if (typeof ChatSend !== 'undefined' && ChatSend.tags) {
    ChatSend.tags.tools = {};
    Panel._toolsCache.forEach(function(t) {
      ChatSend.tags.tools[t.name] = on;
    });
  }
};

Panel.resetTools = function() {
  Panel._toolsState = {};
  Panel._renderTools();
  if (typeof ChatSend !== 'undefined' && ChatSend.tags) {
    ChatSend.tags.tools = {};
    Panel._toolsCache.forEach(function(t) {
      ChatSend.tags.tools[t.name] = t.defaultOn;
      Panel._toolsState[t.name] = t.defaultOn;
    });
  }
  Panel._renderTools();
};
