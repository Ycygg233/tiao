# tools/errors.py - 统一错误类型
"""所有工具执行器、沙箱、文件操作均通过此模块抛出异常。
sink 函数根据 code 决定渲染颜色和行为。"""

from dataclasses import dataclass, field
from typing import Optional


class ToolError(Exception):
  """工具执行错误的统一基类"""
  def __init__(self, code: str, message: str, detail: dict = None):
    super().__init__(message)
    self.code = code
    self.message = message
    self.detail = detail or {}

  def to_dict(self) -> dict:
    return {
      "type": "error",
      "code": self.code,
      "message": self.message,
      "detail": self.detail,
    }

  def to_user_string(self) -> str:
    """CLI 模式下用户可见的字符串"""
    prefix = _ERROR_PREFIX.get(self.code, "✗")
    return f"{prefix} {self.message}"


# ========== 具体错误类型 ==========

class PermissionDeniedError(ToolError):
  def __init__(self, message: str, detail: dict = None):
    super().__init__("permission_denied", message, detail)


class ValidationError(ToolError):
  def __init__(self, message: str, field: str = "", detail: dict = None):
    d = detail or {}
    if field:
      d["field"] = field
    super().__init__("validation_error", message, d)


class ExecutionError(ToolError):
  def __init__(self, message: str, detail: dict = None):
    super().__init__("execution_error", message, detail)


class TimeoutError(ToolError):
  def __init__(self, message: str = "执行超时", timeout_seconds: int = 5):
    super().__init__("timeout", message, {"timeout": timeout_seconds})


class SandboxError(ToolError):
  def __init__(self, message: str, detail: dict = None):
    super().__init__("sandbox_violation", message, detail)


class NotFoundError(ToolError):
  def __init__(self, message: str, detail: dict = None):
    super().__init__("not_found", message, detail)


# ========== 渲染映射 ==========

_ERROR_PREFIX = {
  "permission_denied": "✗",
  "validation_error": "✗",
  "execution_error": "✗",
  "timeout": "",
  "sandbox_violation": "",
  "not_found": "⚠",
}


def is_error_result(result) -> bool:
  if not isinstance(result, str):
    return False
  _error_prefixes = tuple(p for p in set(_ERROR_PREFIX.values()) | {"错误:"} if p)
  return any(result.startswith(p) for p in _error_prefixes)


def toolerror_to_result(e: Exception) -> str:
  """将异常转为用户可见字符串"""
  if isinstance(e, ToolError):
    return e.to_user_string()
  return f"✗ 执行错误: {e}"
