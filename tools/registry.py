# tools/registry.py - 工具注册表（Schema 驱动 + session/global 分层）
import os
import shlex
import threading
from typing import Optional, Callable

from .schema import ToolSchema, ToolPermissions, ParamDef
from .executors import BaseExecutor, NativeExecutor, create_executor, ExecutionContext

# ========== 分层注册表 ==========

_ToolEntry = dict # {schema: ToolSchema, executor: BaseExecutor}

_TOOL_REGISTRY: dict[str, dict[str, _ToolEntry]] = {
  "global": {},
  "session": {}, # {session_id: {name: entry}}
}

_CURRENT_SESSION = ""
# _CURRENT_SESSION 访问加锁，避免并发读到错误的 session 工具集
_current_session_lock = threading.Lock()


def set_current_session(session_id: str):
  global _CURRENT_SESSION
  with _current_session_lock:
    _CURRENT_SESSION = session_id


def register_schema(schema: ToolSchema, executor: Optional[BaseExecutor] = None, fn: Callable = None):
  """注册一个 Schema 驱动的新工具。
  - 如果传 fn，自动用 NativeExecutor 包装
  - 如果传 executor，直接使用
  """
  if executor is None and fn is not None:
    executor = NativeExecutor(fn)
  elif executor is None:
    from .executors import create_executor
    executor = create_executor(schema, fn=fn)

  # 自动推导 safe_for_ai
  if not schema.safe_for_ai:
    schema.safe_for_ai = schema.compute_safe_for_ai()

  layer = "session" if schema.scope == "session" else "global"
  _TOOL_REGISTRY[layer][schema.name] = {
    "schema": schema,
    "executor": executor,
  }


def register(name: str, fn, desc: str = "", params: dict = None,
       safe_for_ai: bool = False, needs_confirm: bool = False,
       parser: Optional[Callable] = None, scope: str = "global"):
  """向后兼容的注册接口：自动从旧参数构建 ToolSchema"""
  param_defs = {}
  for pname, pdesc in (params or {}).items():
    param_defs[pname] = ParamDef(type="string", description=pdesc)
  schema = ToolSchema(
    name=name,
    description=desc,
    parameters=param_defs,
    safe_for_ai=safe_for_ai,
    needs_confirm=needs_confirm,
    scope=scope,
    metadata={"parser": parser} if parser else {},
  )
  register_schema(schema, fn=fn)


def _resolve(name: str) -> Optional[_ToolEntry]:
  """分层查找：session → global"""
  with _current_session_lock:
    current = _CURRENT_SESSION
  if current:
    entry = _TOOL_REGISTRY["session"].get(current, {}).get(name)
    if entry:
      return entry
  return _TOOL_REGISTRY["global"].get(name)


def get_tool(name: str) -> Optional[Callable]:
  entry = _resolve(name)
  if not entry:
    return None
  executor = entry["executor"]
  schema = entry["schema"]
  if isinstance(executor, NativeExecutor) and hasattr(executor, '_fn'):
    fn = executor._fn
    def _validated_runner(**kwargs):
      validated = dict(kwargs)
      ok, err = schema.validate_args(validated)
      if not ok:
        from .errors import ValidationError
        raise ValidationError(err, detail={"schema": schema.name, "args": kwargs})
      return str(fn(**validated))
    return _validated_runner
  def _tool_runner(**kwargs):
    from .executors import ExecutionContext
    return executor.run(schema, kwargs, ExecutionContext())
  return _tool_runner


def get_tool_entry(name: str) -> Optional[dict]:
  entry = _resolve(name)
  return entry


def get_tool_schema(name: str) -> Optional[ToolSchema]:
  entry = _resolve(name)
  return entry["schema"] if entry else None


def execute(schema_name: str, args: dict = None, context: ExecutionContext = None,
      **kwargs) -> str:
  """Schema 驱动的新执行入口"""
  entry = _resolve(schema_name)
  if not entry:
    from .errors import NotFoundError
    raise NotFoundError(f"未知工具: {schema_name}", {"name": schema_name})

  schema = entry["schema"]
  executor = entry["executor"]
  ctx = context or ExecutionContext()
  merged_args = {**kwargs, **(args or {})}

  ok, err = executor.validate(schema, merged_args)
  if not ok:
    from .errors import ValidationError
    raise ValidationError(err, detail={"schema": schema_name, "args": merged_args})

  return executor.run(schema, merged_args, ctx)


def list_tools(session_id: str = ""):
  result = {}
  for name, entry in _TOOL_REGISTRY["global"].items():
    schema = entry["schema"]
    result[name] = {"desc": schema.description, "params": schema.parameters}
  if session_id and session_id in _TOOL_REGISTRY["session"]:
    for name, entry in _TOOL_REGISTRY["session"][session_id].items():
      schema = entry["schema"]
      result[name] = {"desc": schema.description, "params": schema.parameters}
  return result


def list_tool_schemas() -> list[ToolSchema]:
  schemas = [entry["schema"] for entry in _TOOL_REGISTRY["global"].values()]
  with _current_session_lock:
    current = _CURRENT_SESSION
  if current:
    session_tools = _TOOL_REGISTRY["session"].get(current, {})
    schemas.extend(entry["schema"] for entry in session_tools.values())
  return schemas


def tool_needs_confirm(name: str) -> bool:
  entry = _resolve(name)
  return entry["schema"].needs_confirm if entry else False


def get_tool_executor(name: str) -> Optional[BaseExecutor]:
  entry = _resolve(name)
  return entry["executor"] if entry else None


def _is_tool_allowed_at_level(name: str) -> bool:
  from security.permissions import get_sudo_level
  level = get_sudo_level()
  _blocked_default = {"run_python", "write_file", "delete", "rename", "replace", "create_dir"}
  if level == "" and name in _blocked_default:
    return False
  return True


def get_openai_tools() -> list:
  tools = []
  seen = set()
  for name, entry in _TOOL_REGISTRY["global"].items():
    schema = entry["schema"]
    if schema.safe_for_ai and name not in seen:
      if _is_tool_allowed_at_level(name):
        tools.append(schema.to_openai_function())
      seen.add(name)
  with _current_session_lock:
    current = _CURRENT_SESSION
  if current:
    session_tools = _TOOL_REGISTRY["session"].get(current, {})
    for name, entry in session_tools.items():
      schema = entry["schema"]
      if schema.safe_for_ai and name not in seen:
        if _is_tool_allowed_at_level(name):
          tools.append(schema.to_openai_function())
        seen.add(name)
  return tools


def _update_ai_safe_tools():
  """刷新 _AI_SAFE_TOOLS（原地更新，避免 import 绑定过期）"""
  _AI_SAFE_TOOLS.clear()
  for name, entry in _TOOL_REGISTRY["global"].items():
    if entry["schema"].safe_for_ai:
      _AI_SAFE_TOOLS.add(name)
  with _current_session_lock:
    current = _CURRENT_SESSION
  if current:
    session_tools = _TOOL_REGISTRY["session"].get(current, {})
    for name, entry in session_tools.items():
      if entry["schema"].safe_for_ai:
        _AI_SAFE_TOOLS.add(name)


_AI_SAFE_TOOLS: set = set()


# ========== Session 工具管理 ==========

def register_session_tool(session_id: str, schema: ToolSchema, executor: BaseExecutor):
  if session_id not in _TOOL_REGISTRY["session"]:
    _TOOL_REGISTRY["session"][session_id] = {}
  _TOOL_REGISTRY["session"][session_id][schema.name] = {
    "schema": schema,
    "executor": executor,
  }


def remove_session_tool(session_id: str, name: str) -> bool:
  if session_id in _TOOL_REGISTRY["session"]:
    return _TOOL_REGISTRY["session"][session_id].pop(name, None) is not None
  return False


def clear_session_tools(session_id: str):
  _TOOL_REGISTRY["session"].pop(session_id, None)
