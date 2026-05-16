"""chat/_shared.py — 共享状态 + 配置读写 + 工具执行核心"""
import json
import threading
import logging
from config import CONFIG, valert
from tools import get_tool
from tools.quota import get_quota
log = logging.getLogger("tiao")

_tid_to_sink: dict[int, callable] = {}
_tid_to_sink_lock = threading.Lock()


def _get_output_sink() -> callable:
  """获取当前线程的输出 sink"""
  tid = threading.current_thread().ident
  with _tid_to_sink_lock:
    return _tid_to_sink.get(tid)


class _OutputSink:
  """按线程 ID 路由的 output sink。
  
  __call__   → 发送数据到当前线程的 sink
  __bool__   → 当前线程是否有 sink
  """
  def __call__(self, data):
    fn = _get_output_sink()
    if fn:
      fn(data)
  def __bool__(self):
    return _get_output_sink() is not None


_output_sink = _OutputSink()


def set_output_sink(fn):
  """为当前线程设置输出 sink"""
  tid = threading.current_thread().ident
  with _tid_to_sink_lock:
    _tid_to_sink[tid] = fn


def clear_output_sink():
  """清除当前线程的输出 sink"""
  tid = threading.current_thread().ident
  with _tid_to_sink_lock:
    _tid_to_sink.pop(tid, None)
from security.dialog import _confirm_or_skip
_confirm_func = _confirm_or_skip

_messages_lock = threading.Lock()
_total_input_tokens = 0
_total_output_tokens = 0

def set_confirm_func(fn):
  global _confirm_func
  _confirm_func = fn
  from tools import _set_confirm_callback
  _set_confirm_callback(fn)

def set_thinking(state=""):
  if state == "":
    return _get_thinking_status()
  if state in ("on", "high", "max"):
    CONFIG["thinking"] = state
  elif state == "off":
    CONFIG["thinking"] = "off"
  elif state == "reset":
    CONFIG["thinking"] = "profile"
  else:
    return f"未知参数: {state}，可用: on|off|high|max|reset"
  return _get_thinking_status()

def _get_thinking_status():
  t = CONFIG.get("thinking", "profile")
  profile_name = CONFIG.get("current_profile", "default")
  profile = CONFIG.get("profiles", {}).get(profile_name, {})
  if t == "profile":
    if profile.get("thinking"):
      effort = profile.get("reasoning_effort", "high")
      return f" thinking on \u00b7 effort {effort}（跟随 profile: {profile_name}）"
    return f"\U0001f4a8 thinking off（跟随 profile: {profile_name}）"
  if t == "off":
    return "\U0001f4a8 thinking off（覆盖 profile）"
  effort = "high" if t == "on" else t
  return f" thinking {t} \u00b7 effort {effort}（覆盖 profile）"

def reset_thinking():
  CONFIG["thinking"] = "profile"

def get_agent_mode():
  return CONFIG.get("agent_mode", "ask")

def set_workspace(path: str):
  from security.permissions import set_workspace as _sw
  _sw(path)

def get_workspace():
  from security.permissions import get_workspace as _gw
  return _gw() or ""

def _get_config(key, default=None):
  """读取配置，优先从 CONFIG（已即时生效）"""
  return CONFIG.get(key, default)

def _sanitize_effort(val: str):
  if val in {"high", "max"}:
    return val
  log.warning("无效 reasoning_effort: %s，回退到 high", val)
  return "high"

def _build_api_kwargs(thinking=None, reasoning_effort=None):
  """构建 thinking/reasoning 相关 API 参数。

  Args:
    thinking: None=走 CONFIG（CLI 模式），True/False/str=显式指定（Web 模式）
    reasoning_effort: None=走默认，'high'/'max'=指定深度
  """
  kwargs = {}

  # 确定 thinking 状态
  if thinking is None:
    t = CONFIG.get("thinking", "profile")      # CLI 模式
  elif thinking is True:
    t = "on"
  elif thinking is False:
    t = "off"
  else:
    t = thinking

  profile_name = CONFIG.get("current_profile", "default")

  if t == "profile":
    profile = CONFIG.get("profiles", {}).get(profile_name, {})
    if profile.get("thinking"):
      effort = reasoning_effort or profile.get("reasoning_effort", "high")
      kwargs["reasoning_effort"] = _sanitize_effort(effort)
      kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
  elif t == "off":
    pass
  else:
    effort = reasoning_effort or ("high" if t == "on" else t)
    kwargs["reasoning_effort"] = _sanitize_effort(effort)
    kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
  return kwargs
_invalidated_tokens: set[str] = set()
_invalidated_tokens_lock = threading.Lock()


def invalidate_token(token: str):
  """将 token 标记为失效（用于跨线程取消）"""
  with _invalidated_tokens_lock:
    _invalidated_tokens.add(token)


def _token_valid(token: str) -> bool:
  with _invalidated_tokens_lock:
    if not _invalidated_tokens:
      return True
  if not token:
    return False
  with _invalidated_tokens_lock:
    return token not in _invalidated_tokens
def _execute_tool_core(tool_name, args, elapsed=0):
  from security.permissions import has_zero_width
  # 配额检查
  from tools.quota import check_quota
  if not check_quota():
    return "✗ 工具调用额度已用完，请使用 /quota 重置", False
  for key in ("path", "new_path"):
    val = args.get(key, "")
    if isinstance(val, str) and has_zero_width(val):
      return f"拒绝执行：{key} 包含非法字符", False
  try:
    fn = get_tool(tool_name)
    if not fn:
      return f"未知工具: {tool_name}", False
    result = fn(**args)
  except Exception as e:
    return f"执行错误: {e}", False
  # 审计钩子：记录工具调用
  try:
    from security.audit import get_engine
    get_engine().log_event("tool_call", f"tools.{tool_name}",
                 json.dumps({"args": args, "result": str(result)[:200]},
                       ensure_ascii=False))
  except Exception:
    pass
  # 配额已在入口 check_quota() 处消耗，这里不再重复处理
  result_bytes = len(str(result).encode("utf-8", errors="replace"))
  if _output_sink:
    _output_sink({"type":"metrics","tool":tool_name,"ms":int(elapsed*1000),"bytes":result_bytes})
  elif log.isEnabledFor(logging.DEBUG):
    log.debug("  \u21b3 %s: %dms \u00b7 %dB", tool_name, int(elapsed*1000), result_bytes)
  return str(result), True
