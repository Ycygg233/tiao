/* render/content.js — 真流式渲染：分段式 DOM + 增量更新 */
var RenderContent = {};

// ===== 流式状态机 =====
RenderContent._state = 'text';       // 'text' | 'code'
RenderContent._codeBuffer = '';       // 当前代码块累积内容
RenderContent._codeLang = '';         // 当前代码块语言
RenderContent._codeCard = null;       // 当前代码块卡片 DOM
RenderContent._codeSlotIndex = 0;     // 代码块自增索引

// 纯文本分段渲染
RenderContent._plainBuffer = '';      // 当前文本段的累积 markdown
RenderContent._debounceTimer = null;  // 防抖定时器
RenderContent._currentTextSeg = null; // 当前文本段 DOM 元素
RenderContent._containerEl = null;    // 消息容器引用



RenderContent.reset = function() {
  RenderContent._state = 'text';
  RenderContent._codeBuffer = '';
  RenderContent._codeLang = '';
  RenderContent._codeCard = null;
  RenderContent._codeSlotIndex = 0;
  RenderContent._plainBuffer = '';
  RenderContent._currentTextSeg = null;
  RenderContent._containerEl = null;
  if (RenderContent._debounceTimer) {
    clearTimeout(RenderContent._debounceTimer);
    RenderContent._debounceTimer = null;
  }
};

// ===== 核心：处理流式 chunk =====
RenderContent.processChunk = function(chunk, containerEl) {
  if (!chunk) return;
  RenderContent._containerEl = containerEl;

  var i = 0;
  var len = chunk.length;

  while (i < len) {
    if (RenderContent._state === 'text') {
      var idx = chunk.indexOf('```', i);
      if (idx === -1) {
        RenderContent._appendTextLive(chunk.substring(i), containerEl);
        break;
      }
      RenderContent._appendTextLive(chunk.substring(i, idx), containerEl);
      i = idx + 3;
      RenderContent._state = 'code';
      RenderContent._codeLang = '';
      RenderContent._codeBuffer = '';

      // 读取语言名（到行尾），一次性校验
      var lineEnd = chunk.indexOf('\n', i);
      var candidate = '';
      if (lineEnd !== -1) {
        candidate = chunk.substring(i, lineEnd).trim();
        i = lineEnd + 1;
      } else {
        candidate = chunk.substring(i).trim();
        i = len;
      }
      // ★ 只有合法语言名才认，否则视为无标注（candidate 还回代码缓冲区）
      if (/^[a-zA-Z][a-zA-Z0-9+#-]*$/.test(candidate)) {
        RenderContent._codeLang = candidate;
      } else {
        RenderContent._codeLang = '';
        if (candidate) {
          RenderContent._codeBuffer += candidate + '\n';
        }
      }

      // 在创建代码块之前：立即刷新当前文本段
      RenderContent._flushTextSegmentImmediate({ resetBuffer: true });

      // 创建并插入代码块卡片（直接挂载到 DOM）
      RenderContent._codeCard = RenderContent._createCard(containerEl);
    }
    else if (RenderContent._state === 'code') {
      var closeIdx = chunk.indexOf('```', i);
      if (closeIdx === -1) {
        var codeText = chunk.substring(i);
        RenderContent._codeBuffer += codeText;
        RenderContent._appendCodeLive(codeText);
        break;
      }
      var beforeClose = chunk.substring(i, closeIdx);
      RenderContent._codeBuffer += beforeClose;
      RenderContent._appendCodeLive(beforeClose);
      i = closeIdx + 3;
      // 代码块完成
      RenderContent._finalizeCard();
      RenderContent._state = 'text';
    }
  }
};

// ===== 纯文本增量渲染 =====
RenderContent._appendTextLive = function(text, containerEl) {
  if (!text) return;
  RenderContent._plainBuffer += text;
  RenderContent._ensureTextSegment(containerEl);
  RenderContent._debounceFlush();
};

RenderContent._ensureTextSegment = function(containerEl) {
  if (!containerEl) return;
  if (!RenderContent._currentTextSeg || RenderContent._currentTextSeg.parentNode !== containerEl) {
    var seg = document.createElement('div');
    seg.className = 'md-segment';
    containerEl.appendChild(seg);
    RenderContent._currentTextSeg = seg;
  }
};

RenderContent._debounceFlush = function() {
  if (RenderContent._debounceTimer) clearTimeout(RenderContent._debounceTimer);
  RenderContent._debounceTimer = setTimeout(function() {
    RenderContent._doFlushTextSegment({ resetBuffer: false });
  }, 30);
};

RenderContent._flushTextSegmentImmediate = function(opts) {
  if (RenderContent._debounceTimer) {
    clearTimeout(RenderContent._debounceTimer);
    RenderContent._debounceTimer = null;
  }
  RenderContent._doFlushTextSegment(opts || { resetBuffer: false });
};

RenderContent._doFlushTextSegment = function(opts) {
  var seg = RenderContent._currentTextSeg;
  var text = RenderContent._plainBuffer;
  if (!seg) return;

  if (typeof marked !== 'undefined' && marked.parse) {
    try {
      seg.innerHTML = marked.parse(text);
      if (typeof Prism !== 'undefined') {
        seg.querySelectorAll('pre code[class*="language-"]').forEach(function(el) {
          try { Prism.highlightElement(el); } catch(e) {}
        });
      }
    } catch(e) {
      seg.textContent = text;
      Utils.logToServer('error', 'flushTextSegment', String(e));
    }
  } else {
    seg.textContent = text;
  }

  if (opts && opts.resetBuffer) {
    RenderContent._plainBuffer = '';
    RenderContent._currentTextSeg = null;
  }
};

RenderContent.flushMarkdown = function() {
  if (RenderContent._state === 'code') {
    RenderContent._finalizeCard();
    RenderContent._state = 'text';
    RenderContent._codeBuffer = '';
  }
  if (RenderContent._debounceTimer) {
    clearTimeout(RenderContent._debounceTimer);
    RenderContent._debounceTimer = null;
  }
  RenderContent._doFlushTextSegment({ resetBuffer: false });
  if (RenderContent._containerEl) {
    RenderContent.highlight(RenderContent._containerEl);
  }
};

// ===== 代码块卡片 =====
RenderContent._createCard = function(containerEl) {
  if (!containerEl) return null;

  var card = document.createElement('div');
  card.className = 'code-block streaming';

  var header = document.createElement('div');
  header.className = 'code-header';

  var langTag = document.createElement('span');
  langTag.className = 'lang-tag';
  langTag.textContent = Utils.E(RenderContent._codeLang || '');
  header.appendChild(langTag);

  var pre = document.createElement('pre');
  pre.style.cssText = 'height:160px;overflow:auto;max-width:100%;min-width:0;box-sizing:border-box;word-break:break-word;overflow-wrap:anywhere;white-space:pre-wrap;';

  var code = document.createElement('code');
  code.className = 'language-' + (RenderContent._codeLang || 'none');
  pre.appendChild(code);
  card.appendChild(header);
  card.appendChild(pre);

  RenderContent._codeSlotIndex++;

  containerEl.appendChild(card);
  Utils.scrollToBottom();
  return card;
};

RenderContent._finalizeCard = function() {
  var card = RenderContent._codeCard;
  if (!card) return;
  card.classList.remove('streaming');

  var pre = card.querySelector('pre');
  var code = card.querySelector('code');
  if (!pre || !code) return;

  code.textContent = RenderContent._codeBuffer;

  // 清理 className / lang-tag，确保 DOM 回读基于干净状态。
  code.className = '';
  var tagEl = card.querySelector('.lang-tag');
  if (tagEl) tagEl.textContent = '';

  // FIX 1: 语法高亮 —— 从 DOM 回读 className，不再依赖 _codeLang 变量
  var lang = RenderContent._codeLang;
  // 无效的 lang 视为空，走后续 fallback
  if (lang && !/^[a-zA-Z][a-zA-Z0-9+#-]*$/.test(lang)) lang = '';
  if (!lang) {
    var match = code.className.match(/language-(\S+)/);
    if (match) lang = match[1];
  }
  if (!lang || lang === 'none') lang = '';
  // FIX 2: 内容启发式 —— lang 为空时从代码内容推测语言
  if (!lang && RenderContent._codeBuffer) {
    var head = RenderContent._codeBuffer.slice(0, 150).replace(/\s/g, '');
    if (/^<svg[\s>]/i.test(head)) lang = 'svg';
    else if (/^<!DOCTYPE\s+html/i.test(head) || /^<html[\s>]/i.test(head)) lang = 'html';
    else if (/^<[a-z]+[\s>]/i.test(head) && /<\/[a-z]+>/i.test(RenderContent._codeBuffer.slice(0, 300))) lang = 'html';
  }
  // FIX 3: 从代码内容特征推断语言
  if (!lang && RenderContent._codeBuffer) {
    var buf = RenderContent._codeBuffer;
    if (/\b(def |import |from |class |print\(|if\s+__name__|raise |try:|except |return |yield |elif )/.test(buf)) {
      lang = 'python';
    } else if (/\b(function |const |let |var |=> |console\.|document\.|window\.|import\s+\{)/.test(buf)) {
      lang = 'javascript';
    } else if (/\b(package |func |import \(|fmt\.|go func|:= )/.test(buf)) {
      lang = 'go';
    } else if (/\b(fn |let mut |impl |pub fn|unwrap\(\)|-> )/.test(buf)) {
      lang = 'rust';
    } else if (/\b(public class |private |void main|System\.out|@Override)/.test(buf)) {
      lang = 'java';
    } else if (/^#!/m.test(buf)) {
      lang = 'bash';
    }
  }
  // ★ 所有兜底跑完再写标签，保证 tagEl 显示的是最终推断值
  if (tagEl) tagEl.textContent = lang || '';

  if (typeof Prism !== 'undefined' && lang) {
    code.className = 'language-' + lang;
    // ★ rAF 延迟高亮，避免流式收尾帧卡顿
    requestAnimationFrame(function() {
      try { Prism.highlightElement(code); } catch(e) {}
    });
  }

  pre.style.height = 'auto';
  pre.style.maxHeight = '400px';

  var header = card.querySelector('.code-header');
  if (header) {
    var btnGroup = document.createElement('div');
    btnGroup.style.cssText = 'display:flex;gap:10px;flex-shrink:0;align-items:center;';

    var viewBtn = document.createElement('button');
    viewBtn.className = 'copy-btn';
    viewBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>';
    viewBtn.title = '展开代码';
    viewBtn.style.cssText = 'flex-shrink:0;white-space:nowrap;';
    (function(lang, code) {
      viewBtn.onclick = function() {
        RenderContent._showFullCode(lang, code);
      };
    })(lang, RenderContent._codeBuffer);
    btnGroup.appendChild(viewBtn);

    // HTML 预览按钮
    if (lang === 'html' || lang === 'xml' || lang === 'svg') {
      var previewBtn = document.createElement('button');
      previewBtn.className = 'copy-btn';
      previewBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>';
      previewBtn.title = '预览 HTML';
      previewBtn.style.cssText = 'flex-shrink:0;white-space:nowrap;';
      (function(code) {
        previewBtn.onclick = function() {
          RenderContent._showHtmlPreview(code);
        };
      })(RenderContent._codeBuffer);
      btnGroup.appendChild(previewBtn);
    }

    var copyBtn = document.createElement('button');
    copyBtn.className = 'copy-btn';
    copyBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
    copyBtn.title = '复制代码';
    copyBtn.style.cssText = 'flex-shrink:0;white-space:nowrap;';
    (function(code) {
      copyBtn.onclick = function() {
        Utils.copyToClipboard(code, function() {
          copyBtn.textContent = '已复制';
          copyBtn.classList.add('copied');
          setTimeout(function() {
            copyBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
            copyBtn.classList.remove('copied');
          }, 2000);
        });
      };
    })(RenderContent._codeBuffer);
    btnGroup.appendChild(copyBtn);

    header.appendChild(btnGroup);
  }

  RenderContent._codeCard = null;
  Utils.scrollToBottom();
};

RenderContent._appendCodeLive = function(text) {
  var card = RenderContent._codeCard;
  if (!card) return;
  var code = card.querySelector('code');
  if (code) code.textContent += text;
  var pre = card.querySelector('pre');
  if (pre) pre.scrollTop = pre.scrollHeight;
};

// ===== FIX 2: 增强裸代码块（历史会话 / message 事件等非流式路径） =====
RenderContent.enhanceCodeBlocks = function(container) {
  if (!container) return;
  var pres = container.querySelectorAll('pre');
  pres.forEach(function(pre) {
    var code = pre.querySelector('code');
    if (!code) return;
    if (pre.parentElement && pre.parentElement.classList.contains('code-block')) return;

    var lang = '';
    var match = code.className.match(/language-(.*?)(?:\s|$)/);
    if (match) lang = match[1].trim();
    if (!lang || lang === 'none') lang = '';
    var codeText = code.textContent;
    // ★ P0② 修复：从代码内容启发式推测语言
    if (!lang && codeText) {
      var head = codeText.slice(0, 150).replace(/\s/g, '');
      if (/^<svg[\s>]/i.test(head)) lang = 'svg';
      else if (/^<!DOCTYPE\s+html/i.test(head) || /^<html[\s>]/i.test(head)) lang = 'html';
      else if (/^<[a-z]+[\s>]/i.test(head) && /<\/[a-z]+>/i.test(codeText.slice(0, 300))) lang = 'html';
    }

    var card = document.createElement('div');
    card.className = 'code-block';

    var header = document.createElement('div');
    header.className = 'code-header';

    var langTag = document.createElement('span');
    langTag.className = 'lang-tag';
    langTag.textContent = Utils.E(lang || 'code');
    header.appendChild(langTag);

    var btnGroup = document.createElement('div');
    btnGroup.style.cssText = 'display:flex;gap:10px;flex-shrink:0;align-items:center;';

    var viewBtn = document.createElement('button');
    viewBtn.className = 'copy-btn';
    viewBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>';
    viewBtn.title = '展开代码';
    viewBtn.style.cssText = 'flex-shrink:0;white-space:nowrap;';
    (function(lang, code) {
      viewBtn.onclick = function() {
        RenderContent._showFullCode(lang, code);
      };
    })(lang, codeText);
    btnGroup.appendChild(viewBtn);

    var copyBtn = document.createElement('button');
    copyBtn.className = 'copy-btn';
    copyBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
    copyBtn.title = '复制代码';
    copyBtn.style.cssText = 'flex-shrink:0;white-space:nowrap;';
    (function(code) {
      copyBtn.onclick = function() {
        Utils.copyToClipboard(code, function() {
          copyBtn.textContent = '已复制';
          copyBtn.classList.add('copied');
          setTimeout(function() {
            copyBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
            copyBtn.classList.remove('copied');
          }, 2000);
        });
      };
    })(codeText);
    btnGroup.appendChild(copyBtn);

    header.appendChild(btnGroup);
    card.appendChild(header);

    pre.style.cssText = 'height:auto;max-height:400px;max-width:100%;min-width:0;box-sizing:border-box;word-break:break-word;overflow-wrap:anywhere;white-space:pre-wrap;';
    if (pre.parentNode) pre.parentNode.insertBefore(card, pre);
    card.appendChild(pre);
  });
};

// ===== 全屏查看代码 =====
RenderContent._showFullCode = function(lang, code) {
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
  var langSpan = document.createElement('span');
  langSpan.className = 'lang-tag';
  langSpan.textContent = Utils.E(lang || 'code');
  header.appendChild(langSpan);

  var headerActions = document.createElement('div');
  headerActions.style.cssText = 'display:flex;gap:8px;align-items:center;flex-shrink:0;';

  var copyBtn = document.createElement('button');
  copyBtn.className = 'code-viewer-copy';
  copyBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
  copyBtn.title = '复制';
  copyBtn.onclick = function() {
    Utils.copyToClipboard(code, function() {
      copyBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><polyline points="20 6 9 17 4 12"/></svg>';
      setTimeout(function() {
        copyBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:14px;height:14px"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
      }, 2000);
    });
  };
  headerActions.appendChild(copyBtn);

  var closeBtn = document.createElement('button');
  closeBtn.className = 'code-viewer-close';
  closeBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
  closeBtn.title = '关闭 (ESC)';
  closeBtn.onclick = close;
  headerActions.appendChild(closeBtn);

  header.appendChild(headerActions);

  var body = document.createElement('div');
  body.className = 'code-viewer-body';
  var pre = document.createElement('pre');
  pre.style.cssText = 'margin:0;min-width:0;';
  var codeEl = document.createElement('code');
  codeEl.className = 'language-' + (lang || 'none');
  codeEl.textContent = code;
  codeEl.style.cssText = 'display:inline-block;max-width:100%;word-break:break-word;overflow-wrap:anywhere;';
  pre.appendChild(codeEl);
  body.appendChild(pre);

  card.appendChild(header);
  card.appendChild(body);
  overlay.appendChild(card);
  document.body.appendChild(overlay);

  if (typeof Prism !== 'undefined' && lang) {
    try { Prism.highlightElement(codeEl); } catch(e) {}
  }
  setTimeout(function() { closeBtn.focus(); }, 50);
};

// ===== Markdown 解析 =====
RenderContent.parseMarkdown = function(text) {
  if (!text) return '';
  if (typeof marked !== 'undefined' && marked.parse) {
    try { return marked.parse(text); } catch(e) { return Utils.E(text); }
  }
  return '<pre><code>' + Utils.E(text) + '</code></pre>';
};

// ===== 语法高亮 =====
RenderContent.highlight = function(container) {
  if (typeof Prism === 'undefined') return;
  if (!container) container = document.getElementById('messages');
  if (!container) return;
  container.querySelectorAll('pre code[class*="language-"]').forEach(function(el) {
    try { Prism.highlightElement(el); } catch(e) {}
  });
};

// ===== Diff 处理 =====
RenderContent.isDiff = function(text) {
  return text && (text.indexOf('--- a/') !== -1 || text.indexOf('diff --git') !== -1 || text.indexOf('@@ ') === 0);
};

RenderContent.renderDiff = function(unifiedDiff, targetEl) {
  if (typeof Diff2Html === 'undefined') {
    targetEl.textContent = unifiedDiff;
    return;
  }
  if (!unifiedDiff || unifiedDiff.length < 5000) {
    try {
      var cfg = {drawFileList:false, matching:'lines', outputFormat:'line-by-line'};
      targetEl.innerHTML = Diff2Html.html(unifiedDiff, cfg);
      targetEl.querySelectorAll('pre code.language-diff').forEach(function(el) {
        try { Prism.highlightElement(el); } catch(e) {}
      });
    } catch(e) {
      targetEl.textContent = unifiedDiff;
    }
    return;
  }
  targetEl.textContent = '渲染中 (' + (unifiedDiff.length/1024).toFixed(0) + 'KB)...';
  var lines = unifiedDiff.split('\n'), idx = 0, chunkSize = 200;
  function nextChunk() {
    var chunk = lines.slice(idx, idx + chunkSize).join('\n');
    if (!chunk) return;
    try {
      var html = Diff2Html.html(chunk, {drawFileList:false, matching:'lines', outputFormat:'line-by-line'});
      var frag = document.createElement('div');
      frag.innerHTML = html;
      targetEl.appendChild(frag);
      frag.querySelectorAll('pre code.language-diff').forEach(function(el) {
        try { Prism.highlightElement(el); } catch(e) {}
      });
    } catch(e) {
      var p = document.createElement('div');
      p.textContent = chunk;
      targetEl.appendChild(p);
    }
    idx += chunkSize;
    if (idx < lines.length) requestAnimationFrame(nextChunk);
  }
  targetEl.innerHTML = '';
  requestAnimationFrame(nextChunk);
};

// ===== HTML 预览 =====
RenderContent._showHtmlPreview = function(htmlCode) {
  var overlay = document.createElement('div');
  overlay.className = 'code-viewer-overlay';
  overlay.style.alignItems = 'center';
  overlay.onclick = function(e) { if (e.target === this) close(); };

  function close() {
    if (overlay.parentNode) document.body.removeChild(overlay);
    document.removeEventListener('keydown', onKey);
  }
  function onKey(e) { if (e.key === 'Escape') close(); }
  document.addEventListener('keydown', onKey);

  var card = document.createElement('div');
  card.className = 'html-preview-card';
  card.onclick = function(e) { e.stopPropagation(); };

  var header = document.createElement('div');
  header.className = 'html-preview-header';
  var titleSpan = document.createElement('span');
  titleSpan.textContent = 'HTML 预览';
  header.appendChild(titleSpan);
  var closeBtn = document.createElement('button');
  closeBtn.className = 'code-viewer-close';
  closeBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
  closeBtn.onclick = close;
  header.appendChild(closeBtn);
  card.appendChild(header);

  var body = document.createElement('div');
  body.className = 'html-preview-body';
  var iframe = document.createElement('iframe');
  iframe.sandbox = 'allow-scripts';
  iframe.style.cssText = 'width:100%;height:100%;border:none;background:white';
  iframe.srcdoc = htmlCode;
  body.appendChild(iframe);
  card.appendChild(body);

  overlay.appendChild(card);
  document.body.appendChild(overlay);
  setTimeout(function() { closeBtn.focus(); }, 50);
};
