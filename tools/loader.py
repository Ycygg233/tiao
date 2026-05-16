# tools/loader.py - YAML/JSON 工具定义加载器
"""从 YAML/JSON 文件加载工具定义，生成 ToolSchema + Executor 并注册。"""

import os
import json
from typing import Optional, Tuple

from .schema import ToolSchema, ToolPermissions, ParamDef
from .executors import BaseExecutor, NativeExecutor, SandboxExecutor, create_executor
from .registry import register_schema, register_session_tool
from .errors import ValidationError, SandboxError


# ========== 加载入口 ==========

def load_tool_from_file(filepath: str, session_id: str = "") -> Tuple[ToolSchema, BaseExecutor]:
  """从 YAML 或 JSON 文件加载工具定义。
  返回 (schema, executor)，调用方决定注册到 global 或 session。
  """
  if not os.path.isfile(filepath):
    raise ValidationError(f"文件不存在: {filepath}", field="filepath")

  with open(filepath, "r", encoding="utf-8") as f:
    raw = f.read()

  ext = os.path.splitext(filepath)[1].lower()
  if ext in (".yaml", ".yml"):
    data = _parse_yaml(raw)
  elif ext == ".json":
    data = json.loads(raw)
  else:
    raise ValidationError(
      f"不支持的文件格式: {ext}，请使用 .yaml/.yml/.json",
      field="filepath"
    )

  return _build_tool(data, filepath, session_id)


def load_tool_from_yaml(raw: str, session_id: str = "") -> Tuple[ToolSchema, BaseExecutor]:
  """从 YAML 字符串加载工具定义"""
  data = _parse_yaml(raw)
  return _build_tool(data, filepath="<inline>", session_id=session_id)


def load_tool_from_json(raw: str, session_id: str = "") -> Tuple[ToolSchema, BaseExecutor]:
  """从 JSON 字符串加载工具定义"""
  data = json.loads(raw)
  return _build_tool(data, filepath="<inline>", session_id=session_id)


# ========== 内部实现 ==========

def _parse_yaml(raw: str) -> dict:
  try:
    import yaml
    return yaml.safe_load(raw)
  except ImportError:
    raise ValidationError(
      "需要安装 PyYAML 才能解析 YAML: pip install PyYAML",
      field="format"
    )


def _build_tool(data: dict, filepath: str, session_id: str) -> Tuple[ToolSchema, BaseExecutor]:
  if not isinstance(data, dict):
    raise ValidationError("工具定义必须是字典", field="root")

  name = data.get("name", "").strip()
  if not name:
    raise ValidationError("工具名 (name) 不能为空", field="name")

  description = data.get("description", "")
  permissions = ToolPermissions.from_dict(data.get("permissions", {}))
  executor_type = data.get("executor_type") or (data.get("executor") or {}).get("type", "native")
  scope = data.get("scope", "global")
  needs_confirm = data.get("needs_confirm", False)
  safe_for_ai = data.get("safe_for_ai", False)

  params = {}
  for pname, pdef in data.get("parameters", {}).items():
    if isinstance(pdef, str):
      params[pname] = ParamDef(type="string", description=pdef)
    else:
      params[pname] = ParamDef(
        type=pdef.get("type", "string"),
        description=pdef.get("description", ""),
        required=pdef.get("required", False),
        default=pdef.get("default"),
        enum=pdef.get("enum"),
      )

  executor_config = data.get("executor")
  if executor_config is None:
    executor_config = data

  metadata = {
    "yaml_path": filepath if filepath != "<inline>" else None,
    "language": executor_config.get("language", "python"),
    "code": executor_config.get("code", ""),
    "steps": executor_config.get("steps", []),
  }

  schema = ToolSchema(
    name=name,
    description=description,
    parameters=params,
    permissions=permissions,
    executor_type=executor_type,
    scope=scope,
    needs_confirm=needs_confirm,
    safe_for_ai=safe_for_ai,
    metadata=metadata,
  )

  if executor_type == "sandbox" and metadata["code"]:
    _validate_sandbox_code(schema)

  executor = create_executor(schema)
  return schema, executor


def _validate_sandbox_code(schema: ToolSchema):
  code = schema.metadata.get("code", "")
  if not code:
    return
  import ast
  try:
    tree = ast.parse(code)
  except SyntaxError as e:
    raise SandboxError(f"工具 {schema.name} 语法错误: {e}", detail={"tool": schema.name})
  _FATAL_FUNCTIONS = frozenset({"exec", "eval", "compile", "__import__"})
  _DANGEROUS_ATTRS = frozenset({
    "__class__", "__bases__", "__subclasses__", "__globals__",
    "__code__", "__builtins__", "__import__", "__reduce__",
    "__mro__", "__getattribute__", "__del__", "__setattr__",
    "__delattr__", "__init_subclass__", "__class_getitem__",
    "__base__", "__mro_entries__", "__subclasshook__",
    "__getattr__", "__getitem__", "__get__",
    "tb_frame", "tb_next", "f_globals", "f_locals", "f_back",
  })
  _BUILTINS_ALIASES = frozenset({"__builtins__", "builtins"})
  for node in ast.walk(tree):
    if isinstance(node, ast.Call):
      if isinstance(node.func, ast.Name) and node.func.id in _FATAL_FUNCTIONS:
        raise SandboxError(
          f"工具 {schema.name} 检测到禁止的函数: {node.func.id}",
          detail={"tool": schema.name, "function": node.func.id}
        )
      if isinstance(node.func, ast.Attribute) and node.func.attr in _DANGEROUS_ATTRS:
        raise SandboxError(
          f"工具 {schema.name} 检测到禁止的属性访问: {node.func.attr}",
          detail={"tool": schema.name, "attr": node.func.attr}
        )
      if isinstance(node.func, ast.Name) and node.func.id == "getattr":
        args_names = []
        for arg in node.args:
          if isinstance(arg, ast.Name):
            args_names.append(arg.id)
          elif isinstance(arg, ast.Attribute):
            args_names.append(arg.attr)
          elif isinstance(arg, ast.Constant):
            args_names.append(str(arg.value))
        if any(a in _BUILTINS_ALIASES for a in args_names) and \
          any(a in _FATAL_FUNCTIONS for a in args_names):
          raise SandboxError(
            f"工具 {schema.name} 检测到通过 getattr 绕过: {args_names}",
            detail={"tool": schema.name}
          )
      if isinstance(node.func, ast.Attribute):
        if isinstance(node.func.value, ast.Name) and \
          node.func.value.id in _BUILTINS_ALIASES and \
          node.func.attr in _FATAL_FUNCTIONS:
          raise SandboxError(
            f"工具 {schema.name} 检测到 builtins 调用: builtins.{node.func.attr}",
            detail={"tool": schema.name, "attr": node.func.attr}
          )
    if isinstance(node, ast.Attribute) and node.attr in _DANGEROUS_ATTRS:
      raise SandboxError(
        f"工具 {schema.name} 检测到禁止的属性: {node.attr}",
        detail={"tool": schema.name, "attr": node.attr}
      )
    if isinstance(node, ast.Subscript):
      if isinstance(node.value, ast.Name) and \
        node.value.id in _BUILTINS_ALIASES:
        if isinstance(node.slice, ast.Constant):
          val = str(node.slice.value)
          if val in _FATAL_FUNCTIONS:
            raise SandboxError(
              f"工具 {schema.name} 检测到 builtins 下标访问: {node.value.id}[{val!r}]",
              detail={"tool": schema.name}
            )


# ========== 便捷注册 ==========

def load_and_register(filepath: str, session_id: str = ""):
  """从文件加载工具并自动注册"""
  schema, executor = load_tool_from_file(filepath, session_id)
  if session_id:
    register_session_tool(session_id, schema, executor)
  else:
    register_schema(schema, executor=executor)
  return schema


def load_and_register_yaml(raw: str, session_id: str = ""):
  """从 YAML 字符串加载工具并自动注册"""
  schema, executor = load_tool_from_yaml(raw, session_id)
  if session_id:
    register_session_tool(session_id, schema, executor)
  else:
    register_schema(schema, executor=executor)
  return schema


# ========== 目录扫描 ==========

def load_tools_from_dir(directory: str, session_id: str = "") -> list[ToolSchema]:
  """扫描目录中所有 .yaml/.yml/.json 文件并注册"""
  schemas = []
  if not os.path.isdir(directory):
    return schemas
  for fname in sorted(os.listdir(directory)):
    if not fname.endswith((".yaml", ".yml", ".json")):
      continue
    fpath = os.path.join(directory, fname)
    try:
      schema, executor = load_tool_from_file(fpath, session_id)
      if session_id:
        register_session_tool(session_id, schema, executor)
      else:
        register_schema(schema, executor=executor)
      schemas.append(schema)
    except Exception as e:
      # 单个文件加载失败不影响其他文件
      import logging
      log = logging.getLogger("tiao")
      log.warning("跳过工具文件 %s: %s", fname, e)
  return schemas
