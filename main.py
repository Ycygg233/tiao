#!/usr/bin/env python3
"""
main.py - 鲦 (tiao)
REPL + 流式渲染 + Agent 循环
"""

import os
import sys
import time
import socket
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text
from styles import ERROR, SOURCE, MUTED, SEPARATOR, TIAO_THEME
from prompt_toolkit import PromptSession

from config import CONFIG, valert

from chat import chat_core as chat_core
from chat.chat_core import chat_stream
from tools.tool_dispatch import handle_tool_call

from session import (
  show_recent_sessions, save_session, try_fetch_models,
  generate_session_title,
)
from skills.prompts import load_skills, build_system_prompt
from commands import TiaoCompleter, dispatch as cmd_dispatch, DispatchResult

__version__ = "2.1.0"

# ========== 插件目录扫描 ==========

_PLUGIN_DIR = os.path.join(os.path.expanduser("~"), ".tiao_tools")


def _load_plugins(logger=None):
  if not os.path.isdir(_PLUGIN_DIR):
    return []
  loaded = []
  from tools.loader import load_tools_from_dir
  loaded.extend(load_tools_from_dir(_PLUGIN_DIR))
  for fname in sorted(os.listdir(_PLUGIN_DIR)):
    if not fname.endswith(".py") or fname.startswith("_"):
      continue
    fpath = os.path.join(_PLUGIN_DIR, fname)
    try:
      schema = _load_py_plugin(fpath)
      if schema:
        from tools.registry import register_schema
        register_schema(schema)
        loaded.append(schema.name)
        if logger:
          logger.debug("插件已注册: %s → %s", fname, schema.name)
    except Exception as e:
      if logger:
        logger.warning("跳过插件 %s: %s", fname, e)
  if loaded and logger:
    logger.debug("已加载 %d 个插件", len(loaded))
  return loaded


def _load_py_plugin(fpath: str):
  """加载 .py 插件文件，通过子进程隔离执行。"""
  import ast as _ast
  import subprocess as _sp
  import json as _json
  
  with open(fpath, "r", encoding="utf-8") as f:
    source = f.read()

  tree = _ast.parse(source)
  has_register_call = False

  for node in _ast.walk(tree):
    if isinstance(node, _ast.Call):
      if isinstance(node.func, _ast.Name) and node.func.id == "register":
        has_register_call = True
        continue
    if isinstance(node, (_ast.Import, _ast.ImportFrom)):
      modules = []
      if isinstance(node, _ast.ImportFrom) and node.module:
        modules = [node.module.split(".")[0]]
      else:
        for alias in node.names:
          modules.append(alias.name.split(".")[0])
      for m in set(modules):
        if m not in ("tools", "typing", "os", "pathlib", "json",
               "datetime", "re", "math", "collections"):
          raise ValueError(f"插件中禁止导入: {m}")

  if not has_register_call:
    raise ValueError("插件未找到 register() 调用")

  tree2 = _ast.parse(source)
  cleaned_lines = list(source.splitlines())
  for node in _ast.walk(tree2):
    if isinstance(node, (_ast.Import, _ast.ImportFrom)):
      if node.lineno == node.end_lineno:
        line = cleaned_lines[node.lineno - 1]
        before = line[:node.col_offset]
        after = line[node.end_col_offset:]
        cleaned_lines[node.lineno - 1] = before + after
      else:
        for lineno in range(node.lineno, node.end_lineno + 1):
          cleaned_lines[lineno - 1] = ""
  cleaned = "\n".join(cleaned_lines)

  project_dir = os.path.dirname(os.path.abspath(__file__))
  payload = _json.dumps({"cleaned": cleaned, "project_dir": project_dir})

  runner = r'''
import sys, json
args = json.loads(sys.stdin.read())
sys.path.insert(0, args["project_dir"])
from tools.schema import ToolSchema

_result = None
def _plugin_register(schema=None):
  global _result
  if isinstance(schema, ToolSchema):
    _result = schema.to_dict()
  elif isinstance(schema, dict):
    _result = schema

_builtins = {
  "True": True, "False": False, "None": None,
  "str": str, "int": int, "float": float, "bool": bool,
  "list": list, "dict": dict, "set": set, "tuple": tuple,
  "len": len, "range": range, "print": print,
  "isinstance": isinstance,
  "Exception": Exception, "ValueError": ValueError,
}

try:
  exec(args["cleaned"], {
    "__builtins__": _builtins,
    "register": _plugin_register,
    "ToolSchema": ToolSchema,
  })
except Exception as e:
  err_msg = str(e)
  if isinstance(e, NameError):
    available = ", ".join(sorted(_builtins.keys()))
    err_msg = f"{e}\n可用 builtins: {available}"
  print(json.dumps({"error": err_msg}))
  sys.exit(1)

if _result is None:
  print(json.dumps({"error": "插件未生成有效的 ToolSchema"}))
  sys.exit(1)

print(json.dumps(_result, ensure_ascii=False))
'''

  try:
    r = _sp.run(
      [sys.executable, "-c", runner],
      input=payload, capture_output=True, text=True, timeout=10,
    )
  except _sp.TimeoutExpired:
    raise ValueError("插件加载超时 (10s)")

  if r.returncode != 0 or not r.stdout.strip():
    err = "插件未生成有效的 ToolSchema"
    try:
      err_data = _json.loads(r.stderr) if r.stderr else {}
      if isinstance(err_data, dict):
        err = err_data.get("error", err)
    except (_json.JSONDecodeError, TypeError):
      if r.stderr.strip():
        err = r.stderr.strip()
    raise ValueError(f"插件加载失败: {err}")

  try:
    data = _json.loads(r.stdout.strip())
  except (_json.JSONDecodeError, TypeError):
    raise ValueError(f"插件输出解析失败")

  if isinstance(data, dict) and "error" in data:
    raise ValueError(f"插件错误: {data['error']}")

  from tools.schema import ToolSchema
  return ToolSchema.from_dict(data)

from config import DATA_DIR

# ========== 日志 ==========

LOG_DIR = Path(DATA_DIR) / "logs"
LOG_DIR.mkdir(exist_ok=True)

# 文件 handler：按天轮转，保留 30 天
_file_handler = TimedRotatingFileHandler(
  filename=LOG_DIR / "tiao.log",
  when="midnight",
  interval=1,
  backupCount=30,
  encoding="utf-8",
)
_file_handler.setLevel(logging.INFO)
_file_handler.setFormatter(logging.Formatter(
  "%(asctime)s [%(levelname)s] %(message)s",
  datefmt="%Y-%m-%d %H:%M:%S",
))

# 控制台 handler
_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.INFO)
_console_handler.setFormatter(logging.Formatter(
  "%(asctime)s [%(levelname)s] %(message)s",
  datefmt="%H:%M:%S",
))

logging.basicConfig(
  level=logging.INFO,
    handlers=[_file_handler, _console_handler],
)

log = logging.getLogger("tiao")
logging.getLogger("httpx").setLevel(logging.WARNING)
log.info(" 鲦 (tiao) 启动，日志记录到 %s", LOG_DIR / "tiao.log")

# ========== 常量 ==========

console = Console(theme=TIAO_THEME)





def _get_display_name() -> str:
  name = CONFIG.get("display_name")
  if name:
    return name
  model = CONFIG.get("model", "").lower()
  if "deepseek" in model:
    return "DeepSeek"
  if "gpt" in model:
    return "GPT"
  if "claude" in model:
    return "Claude"
  if "gemini" in model:
    return "Gemini"
  return model.split("-")[0].capitalize() if "-" in model else model.capitalize()


def main():
  # 支持环境变量 TIAO_PROFILE 指定默认场景（用于 widget 快捷启动）
  current_profile = os.environ.get("TIAO_PROFILE", "default")
  if current_profile not in CONFIG.get("profiles", {}):
    current_profile = "default"
  CONFIG["current_profile"] = current_profile

  # 初始化审计引擎
  # 初始化审计引擎 + 注册备份回调
# 初始化审计引擎
  try:
    from security.audit import get_engine
    get_engine()
  except Exception:
    pass
  skills_text = load_skills(log, config=CONFIG)
  rules_text = ""
  sp_content = build_system_prompt(CONFIG, current_profile, skills_text)
  system_prompt = {"role": "system", "content": sp_content}
  messages = [system_prompt]

  last_reply_ref = [""]
  ctx = {
    "messages": messages,
    "session_name": "",
    "system_prompt": system_prompt,
    "last_reply_ref": last_reply_ref,
    "current_profile": current_profile,
    "workspace": "",
    "console": console,
    "log": log,
    "rules_text": rules_text,
    "dispatch": cmd_dispatch,
    "chat_stream": chat_stream,
    "handle_tool_call": handle_tool_call,
  }

  display_name = _get_display_name()

  # ── 启动画面 ──
  try:
    _rows = os.get_terminal_size().lines
    _cols = os.get_terminal_size().columns
  except (OSError, PermissionError):
    _rows = 24
    _cols = 80
  _card_w = max(36, _cols - 4)
  console.print("\n" * (50 if _rows > 30 else 35))

  # ── 上框：ASCII 大字符 ──
  _tiao_art = """\
████████╗██╗ █████╗  ██████╗
╚══██╔══╝██║██╔══██╗██╔═══██╗
   ██║   ██║███████║██║   ██║
   ██║   ██║██╔══██║██║   ██║
   ██║   ██║██║  ██║╚██████╔╝
   ╚═╝   ╚═╝╚═╝  ╚═╝ ╚═════╝"""
  console.print(Align.center(Text(_tiao_art, style=SOURCE)))
  console.print("")
  console.print(Align.center(Text("鲦 tíao  v{}".format(__version__), style="bold white")))
  console.print("")

  # ── 最近会话卡片（标题同款） ──
  from session import get_session_entries
  _session_colors = ["color(67)", "color(73)", "color(80)", "color(78)", "color(68)"]
  _recent_parts = []
  recent = get_session_entries()[:5]
  if recent:
    for i, e in enumerate(recent):
      name = e["name"]
      max_name_len = max(20, _card_w - 12)
      if len(name) > max_name_len:
        name = name[:max_name_len - 3] + "..."
      _recent_parts.append(Align.center(Text(name, style=_session_colors[i % 5])))
      _recent_parts.append(Text(""))
    _recent_parts.pop()  # 去掉末尾空行
  else:
    _recent_parts.append(Align.center(Text("(暂无会话，输入即创建)", style=MUTED)))
  console.print(Align.center(Panel(
    Group(*_recent_parts), title=" 最近会话 ",
    border_style="blue", padding=(1, 2), width=_card_w,
  )))
  console.print("")

  # ── 操作命令 ──
  console.print(Align.center(Text(
    "Esc+Enter 发送  ·  Tab 补全  ·  Ctrl+Z 中止  ·  Enter 换行",
    style="color(250)",
  )))
  console.print("")
  console.print("")

  # ── 分割线提示 ──
  from rich.rule import Rule
  console.print(Rule(Text(" 输入/help查看更多指令 ", style="color(244)"), style=SEPARATOR))

  plugins = _load_plugins(log)
  if plugins:
    console.print(f"[dim]ext 已加载 {len(plugins)} 个插件: {', '.join(plugins)}[/dim]")

  # ════════════════════════════════════════
  # REPL 主循环
  # ════════════════════════════════════════

  _prompt_session = globals()["session"] # 模块级，main() 之前已创建
  _total_since_save = 0

  def _do_save(exit_save=False):
    """统一保存入口。exit_save=True 时尝试生成标题并缓存。"""
    if len(messages) <= 1:
      return
    name = ctx.get("session_name", "")
    if exit_save and not name:
      # 失败冷却：1分钟内不重复请求 API
      now = time.time()
      last_try = ctx.get("_last_title_attempt", 0)
      if now - last_try >= 60:
        ctx["_last_title_attempt"] = now
        name = generate_session_title(messages) or ""
        if name:
          ctx["session_name"] = name
          ctx["_auto_titled"] = True
      else:
        log.debug("标题生成冷却中，跳过")
    if not name:
      # 降级兜底：取首条 user 消息前15字
      for m in messages:
        if m.get("role") == "user":
          c = m.get("content", "")
          if c and not c.startswith("@"):
            title = c[:15].strip()
            if title:
              name = title
              ctx["session_name"] = name
              ctx["_auto_titled"] = True
            break
    if not name:
      return  # 实在没名字就不保存
    save_session(messages, CONFIG, name)

  while True:
    try:
      user_input = _prompt_session.prompt(">>> ")
    except (KeyboardInterrupt, EOFError):
      log.debug("用户退出")
      break

    text = user_input.strip()
    if not text:
      continue

    result = ctx["dispatch"](text, ctx)
    if result == DispatchResult.BREAK:
      break
    if result == DispatchResult.HANDLED:
      continue

    ctx["current_profile"] = current_profile = ctx.get("current_profile", current_profile)
    CONFIG["current_profile"] = ctx["current_profile"]

    processed = ctx["handle_tool_call"](text)
    if processed is None:
      continue
    text = processed

    now = datetime.now().strftime("%H:%M")
    console.print(f"\n[{CONFIG.get('display_color', 'bold cyan')}] {display_name} · {now}[/]")
    try:
      ctx["chat_stream"](text, messages, last_reply_ref,
                workspace=ctx.get("workspace", ""))
    except Exception as e:
      log.error("对话流异常: %s", e)
      valert(console, ERROR, "✗", f"对话出错: {e}")
      console.print("[dim]消息已保留，可重试。如持续出错请 /clear 后继续。[/dim]")
      continue
    console.print()

    # ── 自动标题：取首条文字消息前 15 字（零 token 开销） ──
    if not ctx.get("_auto_titled") and not ctx.get("session_name"):
      for m in messages:
        if m.get("role") == "user":
          content = m.get("content", "")
          if content and not content.startswith("@"):
            title = content[:15].strip()
            if title:
              ctx["session_name"] = title
              log.info("[SESSION] session=%s", title)
              ctx["_auto_titled"] = True
              log.debug("自动标题: %s", title)
            break

    _total_since_save += 1
    if _total_since_save >= 5:
      _do_save()
      _total_since_save = 0

    _do_save(exit_save=True)
  log.debug("CLI 正常退出")


# ========== 入口 ==========

_KEY_FILE = os.path.join(os.path.expanduser("~"), ".tiao_key")


def _load_api_key() -> Optional[str]:
  # 1. 环境变量
  key = os.environ.get("TIAO_KEY", "").strip()
  if key:
    return key
  # 2. 密钥文件（检查权限）
  if os.path.isfile(_KEY_FILE):
    try:
      st = os.stat(_KEY_FILE)
      if st.st_mode & 0o077:
        valert(console, "yellow", "⚠", f"{_KEY_FILE} 权限过宽，建议 chmod 600")
      with open(_KEY_FILE, "rb") as f:
        encoded = f.read()
      # P1-12 修复：使用 XOR 简易混淆解码
      key = _decode_key(encoded)
      if key:
        return key
    except Exception:
      pass
  return None


# P1-12 修复：API Key 简易 XOR 混淆
_XOR_KEY = b"tiao_v1"


def _encode_key(key: str) -> bytes:
  import base64
  raw = key.encode("utf-8")
  obfuscated = bytes(b ^ _XOR_KEY[i % len(_XOR_KEY)] for i, b in enumerate(raw))
  return base64.b64encode(obfuscated)


def _decode_key(encoded: bytes) -> str:
  import base64
  try:
    obfuscated = base64.b64decode(encoded)
    raw = bytes(b ^ _XOR_KEY[i % len(_XOR_KEY)] for i, b in enumerate(obfuscated))
    return raw.decode("utf-8")
  except Exception:
    return ""


def _save_api_key(key: str):
  try:
    encoded = _encode_key(key)
    with open(_KEY_FILE, "wb") as f:
      f.write(encoded)
    os.chmod(_KEY_FILE, 0o600)
    console.print(f"[dim]key Key 已保存到 {_KEY_FILE}[/dim]")
  except Exception as e:
    valert(console, "yellow", "⚠", f"无法保存 Key: {e}")


if __name__ == "__main__":
  API_KEY = _load_api_key()
  if API_KEY:
    console.print(f"[dim]key 已从 {_KEY_FILE} / env 加载 Key[/dim]")
  else:
    console.print("[dim]粘贴 API Key（支持 #名称 + 空行 + key 格式），粘贴后按 Esc+Enter 确认[/dim]")
    try:
      raw = PromptSession(multiline=True, is_password=True).prompt("")
      console.clear()
    except (KeyboardInterrupt, EOFError):
      console.print("\n[blue]已取消[/blue]")
      sys.exit(1)
    lines = [line.strip() for line in raw.strip().split('\n') if line.strip()]
    key_lines = [l for l in lines if not l.startswith('#')]
    API_KEY = key_lines[-1] if key_lines else ""
    name_line = next((l for l in lines if l.startswith('#')), None)
    if name_line:
      console.print(f"[dim]检测到 Key 别名: {name_line[1:].strip()}[/dim]")
    if not API_KEY:
      console.print("[yellow]API Key 不能为空[/yellow]")
      sys.exit(1)
    _save_api_key(API_KEY)

  # Phase 3: api_key 写入 CONFIG，消费点统一从 CONFIG 读取（不持久化到 JSON，已有专用加密文件）
  CONFIG["api_key"] = API_KEY

  # 加载搜索平台 Key（metaso/tavily/jina/bocha）
  _ENV_FILE = os.path.join(os.path.expanduser("~"), ".tiao_providers_env")
  if os.path.isfile(_ENV_FILE):
    with open(_ENV_FILE) as _f:
      for _line in _f:
        if _line.startswith("export "):
          _parts = _line.strip()[7:].split("=", 1)
          if len(_parts) == 2:
            os.environ[_parts[0]] = _parts[1].strip('"')
    console.print(f"[dim]key 已加载搜索 Key: {_ENV_FILE}[/dim]")

  # 冷启动预热（后台并行，不阻塞启动流程）
  from chat.chat_core import warmup_connection, warmup_tokenizer
  import threading
  threading.Thread(target=warmup_connection, daemon=True).start()
  threading.Thread(target=warmup_tokenizer, daemon=True).start()

  session = PromptSession(multiline=True, completer=TiaoCompleter())

  # prompt_toolkit 默认只在插入文本时触发补全，退格时不触发。
  # 注册 on_text_changed 回调强制退格后刷新补全菜单。
  def _on_text_changed(buffer):
    if buffer.complete_state or buffer.text:
      buffer.start_completion()

  session.default_buffer.on_text_changed += _on_text_changed

  try_fetch_models(log=log)

  if "-web" in sys.argv:
    # Web 模式：启动 HTTP 服务
    from web.web_server import start as web_start
    web_start(api_key=API_KEY)
  else:
    main()
