# tools/schema.py - 核心数据模型：工具 Schema、参数定义、权限模型
"""不可变契约：所有工具必须遵循此 Schema 定义，后续所有动态能力建立在此层之上。"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Literal, Optional, Any
import json


# ========== 权限模型 ==========

@dataclass
class ToolPermissions:
  read: bool = True
  write: bool = False
  exec: bool = False
  network: bool = False

  @classmethod
  def read_only(cls) -> "ToolPermissions":
    return cls(read=True, write=False, exec=False, network=False)

  @classmethod
  def full(cls) -> "ToolPermissions":
    return cls(read=True, write=True, exec=True, network=False)

  @classmethod
  def sandbox(cls) -> "ToolPermissions":
    return cls(read=True, write=False, exec=True, network=False)

  def to_dict(self) -> dict:
    return asdict(self)

  @classmethod
  def from_dict(cls, d: dict) -> "ToolPermissions":
    return cls(
      read=d.get("read", True),
      write=d.get("write", False),
      exec=d.get("exec", False),
      network=d.get("network", False),
    )


# ========== 参数定义 ==========

ParamType = Literal["string", "integer", "boolean", "array", "object"]


@dataclass
class ParamDef:
  type: ParamType = "string"
  description: str = ""
  required: bool = False
  default: Optional[Any] = None
  enum: Optional[list] = None

  def to_dict(self) -> dict:
    d = {"type": self.type, "description": self.description}
    if self.enum is not None:
      d["enum"] = self.enum
    return d

  @classmethod
  def from_dict(cls, d: dict) -> "ParamDef":
    return cls(
      type=d.get("type", "string"),
      description=d.get("description", ""),
      required=d.get("required", False),
      default=d.get("default"),
      enum=d.get("enum"),
    )


# ========== 工具 Schema ==========

ExecutorType = Literal["native", "sandbox", "http", "chain", "multilang"]
ScopeType = Literal["global", "session"]


@dataclass
class ToolSchema:
  name: str
  description: str
  parameters: dict[str, ParamDef] = field(default_factory=dict)
  permissions: ToolPermissions = field(default_factory=ToolPermissions)
  executor_type: ExecutorType = "native"
  scope: ScopeType = "global"
  needs_confirm: bool = False
  safe_for_ai: bool = False
  metadata: dict = field(default_factory=dict)

  def __post_init__(self):
    for name, pdef in self.parameters.items():
      # 热重载兼容：仅裸 dict 需要转换，ParamDef 实例（含旧类实例）直接保留
      if isinstance(pdef, dict):
        self.parameters[name] = ParamDef.from_dict(pdef)

  # ---- 便捷方法 ----

  @property
  def python_fn(self) -> Optional[str]:
    return self.metadata.get("python_fn")

  @property
  def yaml_path(self) -> Optional[str]:
    return self.metadata.get("yaml_path")

  @property
  def required_params(self) -> list[str]:
    return [k for k, v in self.parameters.items() if v.required]

  @property
  def optional_params(self) -> list[str]:
    return [k for k, v in self.parameters.items() if not v.required]

  def validate_args(self, args: dict) -> tuple[bool, Optional[str]]:
    """参数校验：必填检查 + 类型检查 + 枚举校验。"""
    args = dict(args) # 浅拷贝，不污染调用方 dict
    # 必填检查
    for key in self.required_params:
      if key not in args or args[key] is None:
        return False, f"缺少必填参数: {key}"
    for key, val in args.items():
      pdef = self.parameters.get(key)
      if pdef is None:
        continue
      # 类型校验
      try:
        args[key] = _coerce(val, pdef.type)
      except (ValueError, TypeError) as e:
        return False, f"参数错误: {key} 应为 {pdef.type}，收到 {val}"
      # 枚举校验
      if pdef.enum is not None and args[key] not in pdef.enum:
        return False, f"参数 {key} 必须在 {pdef.enum} 内"
    # 默认值填充
    for key in self.optional_params:
      if key not in args or args[key] is None:
        pdef = self.parameters[key]
        if pdef.default is not None:
          args[key] = pdef.default
    return True, None

  # ---- 序列化 ----

  def to_dict(self) -> dict:
    return {
      "name": self.name,
      "description": self.description,
      "parameters": {k: v.to_dict() for k, v in self.parameters.items()},
      "permissions": self.permissions.to_dict(),
      "executor_type": self.executor_type,
      "scope": self.scope,
      "needs_confirm": self.needs_confirm,
      "safe_for_ai": self.safe_for_ai,
      "metadata": self.metadata,
    }

  def to_json(self) -> str:
    return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

  @classmethod
  def from_dict(cls, d: dict) -> "ToolSchema":
    params = {}
    for name, pdef in d.get("parameters", {}).items():
      params[name] = ParamDef.from_dict(pdef) if isinstance(pdef, dict) else pdef
    return cls(
      name=d["name"],
      description=d.get("description", ""),
      parameters=params,
      permissions=ToolPermissions.from_dict(d.get("permissions", {})),
      executor_type=d.get("executor_type", "native"),
      scope=d.get("scope", "global"),
      needs_confirm=d.get("needs_confirm", False),
      safe_for_ai=d.get("safe_for_ai", False),
      metadata=d.get("metadata", {}),
    )

  @classmethod
  def from_json(cls, raw: str) -> "ToolSchema":
    return cls.from_dict(json.loads(raw))

  # ---- OpenAI 兼容 ----

  def to_openai_function(self) -> dict:
    """生成 OpenAI Function Calling 格式的函数描述"""
    props = {}
    required = [k for k, v in self.parameters.items() if v.required]
    for name, pdef in self.parameters.items():
      prop = {"type": pdef.type, "description": pdef.description}
      if pdef.enum is not None:
        prop["enum"] = pdef.enum
      props[name] = prop
    return {
      "type": "function",
      "function": {
        "name": self.name,
        "description": self.description,
        "parameters": {
          "type": "object",
          "properties": props,
          "required": required,
        },
      },
    }

  # ---- AI 安全性推导 ----

  def compute_safe_for_ai(self) -> bool:
    """根据权限自动推导 safe_for_ai：只读且不需要确认的为 AI 安全"""
    if self.needs_confirm:
      return False
    return self.permissions.read and not (
      self.permissions.write or self.permissions.exec
    )


# ========== 类型转换 ==========

_TYPE_COERCE = {
  "string": str,
  "integer": int,
  "boolean": lambda v: v if isinstance(v, bool) else str(v).lower() in ("true", "1", "yes"),
  "array": lambda v: v if isinstance(v, list) else list(v),
  "object": lambda v: v if isinstance(v, dict) else dict(v),
}


def _coerce(val: Any, target_type: str) -> Any:
  """将值转换为目标类型，失败抛 ValueError"""
  if val is None:
    return None
  expected = _TYPE_COERCE.get(target_type)
  if expected is None:
    return val
  if target_type == "boolean":
    if isinstance(val, bool):
      return val
    if isinstance(val, str):
      if val.lower() in ("true", "1", "yes"):
        return True
      if val.lower() in ("false", "0", "no"):
        return False
    if isinstance(val, (int, float)):
      return val != 0
    raise ValueError(f"无法转为 boolean: {val}")
  if isinstance(val, expected):
    return val
  return expected(val)
