# web_server.py - 可选 Web UI（FastAPI + SSE）
import os
import sys
import json
import uuid
import threading
import webbrowser
import asyncio
import queue
import atexit
import logging
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional
from fastapi import Request

# ── Web 日志（文件，按启动轮转） ──
from config import DATA_DIR

_web_log_dir = os.path.join(DATA_DIR, "logs")
os.makedirs(_web_log_dir, exist_ok=True)

# 启动时清理旧 web 日志：保留最近 5 个 或 3 天内
from utils.cleanup import clean_expired
clean_expired(os.path.join(_web_log_dir, "web_*.log"), max_files=5, max_days=3)

_web_log_path = os.path.join(_web_log_dir, datetime.now().strftime("web_%Y%m%d_%H%M%S.log"))
_web_logger = logging.getLogger("tiao.web.file")
_web_handler = logging.FileHandler(_web_log_path, encoding="utf-8")
_web_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
_web_logger.addHandler(_web_handler)
_web_logger.setLevel(logging.DEBUG)
_web_logger.info(" Web 日志启动: %s", _web_log_path)

def _web_log(level, msg, *args):
  getattr(_web_logger, level, _web_logger.info)("[Web] " + (msg % args if args else msg))

from config import CONFIG, valert
from chat.chat_core import (
  chat_stream, set_output_sink, clear_output_sink,
)
from chat._shared import _messages_lock
from session import try_fetch_models, get_session_entries, load_session, save_session, delete_session_file, delete_session_by_id, get_session_name_by_id, rename_session_file, set_session_title, generate_session_title

# ========== 全局状态 ==========

class _AppState:
  def __init__(self):
    self.api_key = ""
    self.auth_token = ""
    self.models_cache = []
    self.init_lock = threading.Lock()
    self.workspace = ""
    self.tools_state = None

_app_state = _AppState()

# ── 标签页级会话状态 ──
# 每个浏览器标签页/设备在打开时通过 /new_tab 获得一个独立 token,
# 后端按 token 路由到各自的 SessionData，实现状态隔离。
# 关键属性:
#   messages:     当前对话消息列表
#   sse_queue:    该标签页独立的 SSE 事件队列
#   cancel_token: 用于取消正在进行的 API 请求
#   needs_init:   首次 /chat 前是否需要构建 system prompt
#   session_id:   关联的数据库会话 id（用于 save_session）
#   session_name: 关联的数据库会话名（用于 save_session）

@dataclass
class SessionData:
  messages: list = field(default_factory=list)
  sse_queue: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=500))
  cancel_token: str = ""
  needs_init: bool = True
  session_id: Optional[int] = None
  session_name: str = ""
  tools_state: Optional[dict] = None

_TAB_SESSIONS: dict[str, SessionData] = {}
_TAB_SESSIONS_LOCK = threading.Lock()

def _new_tab_session() -> SessionData:
  """创建新的标签页会话"""
  s = SessionData(cancel_token=uuid.uuid4().hex)
  return s

def _get_tab_session(request: Request) -> Optional[SessionData]:
  """从请求中提取 tab_token 并返回对应的 SessionData"""
  tab_token = request.headers.get("X-Tab-Token") or ""
  if not tab_token:
    tab_token = request.query_params.get("tab_token", "")
  if not tab_token:
    return None
  with _TAB_SESSIONS_LOCK:
    return _TAB_SESSIONS.get(tab_token)

def _require_auth(request):
  if not _app_state.auth_token:
    return True
  auth = request.headers.get("Authorization", "")
  expected = f"Bearer {_app_state.auth_token}"
  if auth == expected:
    return True
  token_param = request.query_params.get("token", "")
  return token_param == _app_state.auth_token

def _make_tab_sink(tab_session: SessionData):
  """创建绑定到指定标签页的 SSE 输出函数。"""
  q = tab_session.sse_queue
  _CRITICAL_TYPES = frozenset({"done", "error"})
  def _sink(data: dict):
    _web_log("debug", "SSE %s", data.get("type", "?") + (" · " + str(data.get("content",""))[:60] if data.get("content") else ""))
    try:
      q.put_nowait(data)
    except queue.Full:
      if data.get("type") in _CRITICAL_TYPES:
        try:
          dropped = q.get_nowait()
          if dropped.get("type") not in _CRITICAL_TYPES:
            q.put_nowait(data)
          else:
            q.put_nowait(dropped)
        except queue.Empty:
          pass
      else:
        try:
          q.get_nowait()
          q.put_nowait(data)
        except queue.Empty:
          pass
  return _sink

# ========== FastAPI ==========

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

_static_dir = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="tiao")

# P1-3 修复：添加 CORS 中间件，限制来源为本地
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
  CORSMiddleware,
  allow_origins=["*"],
  allow_credentials=True,
  allow_methods=["*"],
  allow_headers=["*"],
)

@app.get("/")
async def index():
  ui_path = os.path.join(_static_dir, "web_ui", "web_ui.html")
  try:
    with open(ui_path, encoding="utf-8") as f:
      html = f.read()
  except FileNotFoundError:
    html = "<h1>web_ui.html 未找到</h1>"
  global _app_state
  if _app_state.auth_token and '<meta name="api-token"' not in html:
    meta_tag = f'<meta name="api-token" content="{_app_state.auth_token}">'
    html = html.replace("</head>", meta_tag + "\n</head>")
  return HTMLResponse(html, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

@app.post("/chat")
async def chat(request: Request):
  if not _require_auth(request):
    return {"error": "未认证"}
  tab = _get_tab_session(request)
  if not tab:
    return {"error": "无效的 tab_token"}

  body = await request.json()
  user_input = body.get("message", "").strip()
  if not user_input:
    return {"error": "消息不能为空"}

  if tab.needs_init:
    with _app_state.init_lock:
      if tab.needs_init:
        from skills.prompts import load_skills, build_system_prompt
        loop = asyncio.get_event_loop()
        skills_text = await loop.run_in_executor(None, load_skills, CONFIG)
        sp_content = build_system_prompt(CONFIG, "default", skills_text)
        system_prompt = {"role": "system", "content": sp_content}
        tab.messages.clear()
        tab.messages.append(system_prompt)
        tab.needs_init = False

  thinking = body.get("thinking", False)
  model_override = body.get("model", "").strip()
  stream_output = body.get("stream_output", True)
  workspace = body.get("workspace", _app_state.workspace)

  # ── 情景切换（仅重建 system prompt，不写 CONFIG） ──
  profile = body.get("profile", "").strip()
  if profile and profile in CONFIG.get("profiles", {}):
    from skills.prompts import load_skills, build_system_prompt
    loop = asyncio.get_event_loop()
    skills_text = await loop.run_in_executor(None, load_skills, CONFIG)
    sp_content = build_system_prompt(CONFIG, profile, skills_text)
    if tab.messages:
      tab.messages[0] = {"role": "system", "content": sp_content}

  temp = body.get("temperature")
  topp = body.get("top_p")
  effort = body.get("reasoning_effort")
  if temp is not None:
    try: temp = float(temp)
    except (ValueError, TypeError): temp = None
  if topp is not None:
    try: topp = float(topp)
    except (ValueError, TypeError): topp = None
  if effort not in ("high", "max"):
    effort = None

  tools_override = body.get("tools")
  if tools_override:
    tab.tools_state = tools_override

  # 清空该标签页的 SSE 队列残余（来自旧对话的未消费事件）
  while not tab.sse_queue.empty():
    try:
      tab.sse_queue.get_nowait()
    except queue.Empty:
      break

  def run():
    # 应用工具管理面板的开关
    _apply_tool_toggles(tab.tools_state)
    tab_sink = _make_tab_sink(tab)
    # 将输出 sink 设为当前标签页的队列（按线程 ID 路由，不影响其他标签页）
    set_output_sink(tab_sink)
    _last_reply_wrap = [""]
    try:
      chat_stream(user_input, tab.messages, _last_reply_wrap,
            token=tab.cancel_token, thinking=thinking, model=model_override,
            stream_output=stream_output, workspace=workspace,
            temperature=temp, top_p=topp, reasoning_effort=effort)
    except Exception as e:
      import traceback
      import logging as _log
      _err = _log.getLogger("tiao")
      _err.error("chat_stream 异常: %s\n%s", e, traceback.format_exc())
      tab_sink({"type": "error", "content": f"✗ 内部错误: {e}"})
    finally:
      clear_output_sink()
    # 自动保存（每轮对话结束立即保存）
    _do_tab_save(tab)
    # 自动标题（首次）
    if not tab.session_name and len(tab.messages) >= 3:
      from session import generate_session_title as _gst
      title = _gst(tab.messages)
      # 降级：AI 生成失败时取首条用户消息前 15 字
      if not title:
        for m in tab.messages:
          if m.get("role") == "user":
            txt = m.get("content", "")
            if txt and not txt.startswith("@"):
              title = txt[:15].strip()
              break
      if title:
        tab.session_name = title
        tab_sink({"type": "title", "content": title})
    with _messages_lock:
      total_chars = sum(len(m.get("content", "")) for m in tab.messages)
    tab_sink({"type": "stats", "content": f"≈{total_chars // 3:,} tokens"})
    tab_sink({"type": "done"})

  t = threading.Thread(target=run, daemon=True)
  t.start()

  return {"status": "ok"}

def _do_tab_save(tab: SessionData):
  """保存标签页的当前会话到数据库。"""
  if len(tab.messages) <= 1:
    return
  from session import save_session as _save
  _save(tab.messages, CONFIG, session_name=tab.session_name or "")

def _save_all_tabs():
  # 退出前保存所有标签页会话
  for _token, _tab in list(_TAB_SESSIONS.items()):
    try:
      _do_tab_save(_tab)
    except Exception:
      pass

atexit.register(_save_all_tabs)

def _apply_tool_toggles(tools_state):
  """根据工具管理面板的开关，过滤 AI 可见的工具列表。"""
  if not tools_state:
    return
  from tools import get_openai_tools
  all_tools = get_openai_tools()
  blocked = [n for n, enabled in tools_state.items() if not enabled]
  filtered = [t for t in all_tools if t.get("function", {}).get("name", "") not in blocked]
  import chat._stream as _cs
  _cs.chat_stream._tool_cache = filtered

@app.post("/cancel")
async def cancel_chat(request: Request):
  tab = _get_tab_session(request)
  if tab:
    from chat._shared import invalidate_token
    invalidate_token(tab.cancel_token)
    tab.cancel_token = uuid.uuid4().hex
  return {"status": "cancelled"}

@app.get("/stream")
async def stream(request: Request):
  if not _require_auth(request):
    return StreamingResponse(
      iter([f"data: {json.dumps({'type': 'error', 'content': '未认证'})}\n\n"]),
      media_type="text/event-stream"
    )
  tab = _get_tab_session(request)
  if not tab:
    return StreamingResponse(
      iter([f"data: {json.dumps({'type': 'error', 'content': '缺少 tab_token'})}\n\n"]),
      media_type="text/event-stream"
    )

  q = tab.sse_queue

  async def generate():
    loop = asyncio.get_event_loop()
    try:
      while True:
        try:
          data = await loop.run_in_executor(None, q.get, True, 30)
        except queue.Empty:
          yield f"data: {json.dumps({'type': 'ping'})}\n\n"
          continue
        yield f"data: {json.dumps(data)}\n\n"
        if data.get("type") == "done":
          break
    except asyncio.CancelledError:
      pass

  return StreamingResponse(generate(), media_type="text/event-stream")

# ========== 模型列表 ==========

@app.get("/models")
async def get_models(refresh: bool = False):
  global _app_state
  if refresh or not _app_state.models_cache:
    try:
      from session import get_available_models
      _app_state.models_cache = get_available_models()
    except Exception as e:
      return {"error": str(e), "models": _app_state.models_cache}
  return {"models": _app_state.models_cache}

# ========== 设置 ==========

# ========== 工作区 ==========

# ========== 对话导出 ==========

# ========== 新会话 ==========

@app.post("/new")
async def new_session(request: Request):
  tab = _get_tab_session(request)
  if not tab:
    return {"error": "无效的 tab_token"}

  tab.cancel_token = uuid.uuid4().hex

  from tools.registry import clear_session_tools
  clear_session_tools(tab.cancel_token)

  # 保存当前会话再清空
  _do_tab_save(tab)
  tab.messages.clear()
  tab.needs_init = True
  tab.session_name = ""
  tab.session_id = None
  return {"status": "ok"}

# ========== 会话管理 API ==========

@app.get("/sessions")
async def list_sessions(offset: int = 0, limit: int = 15):
  """获取会话列表（支持分页）。"""
  entries = get_session_entries(offset=offset, limit=limit)
  return {"sessions": entries, "has_more": len(entries) == limit}

@app.post("/sessions/switch")
async def switch_session(request: Request):
  """切换会话：保存当前 → 加载目标 → 替换 messages。"""
  tab = _get_tab_session(request)

  body = await request.json()
  sid = body.get("id")
  name = body.get("name", "").strip()
  if sid is not None:
    name = get_session_name_by_id(int(sid)) or name
  if not name:
    return {"error": "会话不存在"}

  # 保存当前会话（有 tab 才保存）
  if tab:
    _do_tab_save(tab)

  # 加载目标会话
  data = load_session(name)
  if not data:
    return {"error": f"会话不存在: {name}"}

  loaded = data["messages"]
  if tab:
    tab.messages.clear()
    tab.messages.extend(loaded)
    tab.needs_init = False
    tab.session_name = name
    tab.session_id = sid
    tab.cancel_token = uuid.uuid4().hex

  return {"status": "ok", "id": sid, "name": name, "meta": data.get("meta", {}),
      "messages": loaded}

@app.post("/sessions/delete")
async def delete_session(request: Request):
  """删除指定会话（支持 id 或 name）。"""
  body = await request.json()
  sid = body.get("id")
  name = body.get("name", "").strip()
  if sid is not None:
    ok = delete_session_by_id(int(sid))
  elif name:
    ok = delete_session_file(name)
  else:
    return {"error": "参数不完整"}
  return {"status": "ok" if ok else "error"}

@app.post("/sessions/rename")
async def rename_session(request: Request):
  """重命名会话标题。先设 title 再改 name，避免 WHERE 找不到。"""
  body = await request.json()
  name = body.get("name", "").strip()
  title = body.get("title", "").strip()
  if not name or not title:
    return {"error": "参数不完整"}
  # 先设 title（此时 name 还在，WHERE 可匹配）
  set_session_title(name, title)
  # 再改 name（可选，用于列表展示）
  ok = rename_session_file(name, title)
  return {"status": "ok" if ok else "error", "new_name": title}

@app.post("/sessions/regenerate-title")
async def regenerate_title(request: Request):
  """用 AI 重新生成会话标题。"""
  body = await request.json()
  sid = body.get("id")
  if sid is None:
    return {"error": "参数不完整"}
  name = get_session_name_by_id(int(sid))
  if not name:
    return {"error": "会话不存在"}
  msgs = load_session(name)
  if not msgs:
    return {"error": "会话数据为空"}
  title = generate_session_title(msgs.get("messages", msgs))
  if title:
    set_session_title(name, title)
    return {"status": "ok", "title": title}
  return {"status": "error", "error": "标题生成失败"}

# ========== Sudo 提权 API ==========

@app.get("/sudo")
async def get_sudo():
  """获取当前权限级别和持久化状态"""
  from security.permissions import get_sudo_level
  import os
  level = get_sudo_level()
  persist = os.path.isfile(os.path.join(os.path.expanduser("~"), ".tiao_sudo.json"))
  return {"level": level or "default", "persist": persist}

@app.post("/sudo")
async def set_sudo(request: Request):
  """设置权限级别和持久化状态"""
  from security.permissions import set_sudo_level, save_sudo_persist, clear_sudo_persist
  body = await request.json()
  level = body.get("level", "default")
  persist = body.get("persist", False)

  if level == "default":
    set_sudo_level("")
    clear_sudo_persist()
  elif level in ("su", "su+"):
    set_sudo_level(level)
    if persist:
      save_sudo_persist(level)
    else:
      clear_sudo_persist()
  else:
    return {"error": f"无效的权限级别: {level}"}

  # 刷新 AI 工具缓存（提权后工具列表会变化）
  try:
    from commands.config_cmds import _clear_tool_cache
    _clear_tool_cache()
  except Exception:
    pass

  return {"status": "ok", "level": level, "persist": persist}

# ========== 文件树 API ==========

# ========== Change Queue API ==========

# ========== 前端日志收集 ==========

import atexit
import logging
_log_endpoint = logging.getLogger("tiao.web")

@app.post("/log")
async def client_log(request: Request):
  """P2-58 修复：接收前端错误/警告日志"""
  body = await request.json()
  level = body.get("level", "info")
  msg = body.get("message", "")
  data = body.get("data", "")
  log_line = f"[Web] {msg}" + (f" | {data}" if data else "")
  if level == "error":
    _log_endpoint.warning(log_line)
  elif level == "warn":
    _log_endpoint.warning(log_line)
  else:
    _log_endpoint.info(log_line)
  return {"status": "ok"}

# ========== 消息搜索 ==========

# ========== 健康检查 ==========

# ========== 标签页管理 ==========

@app.post("/new_tab")
async def new_tab():
  """创建新标签页会话，返回独立 token。"""
  token = uuid.uuid4().hex
  with _TAB_SESSIONS_LOCK:
    _TAB_SESSIONS[token] = _new_tab_session()
  return {"token": token}

# ========== 静态文件服务 ==========

app.mount("/static", StaticFiles(directory=os.path.join(_static_dir, "web_ui")), name="static")
_icon_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "icon")
if os.path.isdir(_icon_dir):
  app.mount("/icon", StaticFiles(directory=_icon_dir), name="icon")

# ========== 快速重启 ==========

@app.post("/restart")
async def restart_server():
  import sys as _sys
  from threading import Thread
  def _restart():
    import time as _t
    _t.sleep(0.3)
    try:
      os.execv(_sys.executable, [_sys.executable] + _sys.argv)
    except AttributeError:
      import subprocess as _sp
      _sp.Popen([_sys.executable] + _sys.argv)
      os._exit(0)
  Thread(target=_restart, daemon=True).start()
  return {"status": "restarting"}

@app.post("/shutdown")
async def shutdown_server():
  import os as _os
  _os._exit(0)

# ========== 启动 ==========

def start(api_key: str = "", host: str = "0.0.0.0", port: int = 8080):

  # 加载 API Key（环境变量 → 密钥文件 → CONFIG → 参数）
  if not api_key:
    api_key = os.environ.get("TIAO_KEY", "")
  if not api_key:
    _key_file = os.path.join(os.path.expanduser("~"), ".tiao_key")
    if os.path.isfile(_key_file):
      try:
        with open(_key_file, "rb") as f:
          encoded = f.read()
        _xor_key = b"tiao_v1"
        import base64
        obfuscated = base64.b64decode(encoded)
        api_key = bytes(b ^ _xor_key[i % len(_xor_key)] for i, b in enumerate(obfuscated)).decode("utf-8")
      except Exception:
        api_key = CONFIG.get("api_key", "")
    else:
      api_key = CONFIG.get("api_key", "")
  _app_state.api_key = api_key
  _app_state.auth_token = uuid.uuid4().hex

  # 加载 Web 端独立配置（与 CLI 的 ~/.tiao_config.json 完全隔离）
  from config import load_web_config
  load_web_config()
  CONFIG["api_key"] = api_key

  # 不再创建全局 messages，由各标签页通过 /new_tab 自行创建

  # 无需设置全局 _output_sink，每个标签页的 run() 会通过 set_output_sink 设置

  try_fetch_models(log=logging.getLogger("tiao"))

  url = f"http://{host}:{port}"
  try:
    import subprocess
    subprocess.run(["termux-open-url", url], check=True, timeout=5)
  except Exception:
    try:
      webbrowser.open(url)
    except Exception:
      pass

  import signal
  _shutdown_event = threading.Event()
  def _handle_sigterm(signum, frame):
    print("\n\033[2m收到关闭信号，正在停止服务...\033[0m")
    _shutdown_event.set()
  try:
    signal.signal(signal.SIGTERM, _handle_sigterm)
  except AttributeError:
    pass
  signal.signal(signal.SIGINT, _handle_sigterm)

  print(f"\033[2mWeb 服务: {url}\033[0m")
  print(f"\033[2m输入 rs 回车可快速重启 | Ctrl+C 退出\033[0m")

  def _term_hotkey():
    import sys as _sys
    while not _shutdown_event.is_set():
      try:
        line = _sys.stdin.readline()
        if line.strip() == 'rs':
          print("\033[2m 正在重启...\033[0m")
          os.execv(_sys.executable, [_sys.executable] + _sys.argv)
      except Exception:
        break
  threading.Thread(target=_term_hotkey, daemon=True, name="term-hotkey").start()

  uvicorn.run(app, host=host, port=port, log_level="info")
