# tools/executors.py - 执行器抽象层
"""所有工具的执行都通过 Executor 完成，实现执行逻辑与 Schema 定义解耦。"""

from __future__ import annotations
import os
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Callable

from .schema import ToolSchema


# ========== 执行上下文 ==========

@dataclass
class ToolMetrics:
  start_ns: int = 0
  end_ns: int = 0
  output_bytes: int = 0
  status: str = "pending" # pending | ok | error | timeout

  @property
  def elapsed_ms(self) -> float:
    return (self.end_ns - self.start_ns) / 1_000_000 if self.end_ns else 0

  @property
  def output_kb(self) -> float:
    return self.output_bytes / 1024


@dataclass
class ExecutionContext:
  session_id: str = ""
  dry_run: bool = False
  workspace: str = ""
  confirm_func: Optional[Callable] = None
  metadata: dict = field(default_factory=dict)
  metrics: ToolMetrics = field(default_factory=ToolMetrics)


# ========== 执行器基类 ==========

class BaseExecutor(ABC):
  executor_type: str = "base"

  @abstractmethod
  def _do_validate(self, schema: ToolSchema, args: dict) -> tuple[bool, Optional[str]]:
    """子类实现参数校验"""
    return schema.validate_args(args)

  @abstractmethod
  def _do_run(self, schema: ToolSchema, args: dict, context: ExecutionContext) -> str:
    """子类实现执行逻辑"""

  def validate(self, schema: ToolSchema, args: dict) -> tuple[bool, Optional[str]]:
    return self._do_validate(schema, args)

  def run(self, schema: ToolSchema, args: dict, context: ExecutionContext) -> str:
    import time as _t
    context.metrics.start_ns = _t.perf_counter_ns()
    result = ""
    try:
      result = self._do_run(schema, args, context)
      context.metrics.status = "ok"
      return result
    except Exception:
      context.metrics.status = "error"
      raise
    finally:
      context.metrics.end_ns = _t.perf_counter_ns()
      try:
        context.metrics.output_bytes = len(str(result).encode("utf-8", errors="replace"))
      except Exception:
        context.metrics.output_bytes = 0


# ========== Native 执行器（调用现有 Python 函数）==========

class NativeExecutor(BaseExecutor):
  executor_type = "native"

  def __init__(self, fn: Callable):
    self._fn = fn

  def _do_validate(self, schema: ToolSchema, args: dict) -> tuple[bool, Optional[str]]:
    return schema.validate_args(args)

  def _do_run(self, schema: ToolSchema, args: dict, context: ExecutionContext) -> str:
    return str(self._fn(**args))


# ========== Sandbox 执行器（AST 沙箱 + 超时）==========

class SandboxExecutor(BaseExecutor):
  executor_type = "sandbox"

  def __init__(self, code: str = "", language: str = "python"):
    self.code = code
    self.language = language

  def _do_validate(self, schema: ToolSchema, args: dict) -> tuple[bool, Optional[str]]:
    ok, err = schema.validate_args(args)
    if not ok:
      return ok, err
    if not self.code:
      return False, "sandbox 执行器缺少 code 字段"
    return True, None

  def _do_run(self, schema: ToolSchema, args: dict, context: ExecutionContext) -> str:
    from security.sandbox import run_python as _sandbox_run
    return _sandbox_run(self.code, exec_vars=args)


# ========== Dry Run 执行器（装饰器模式）==========

class DryRunExecutor(BaseExecutor):
  executor_type = "dryrun"

  def __init__(self, inner: BaseExecutor):
    self._inner = inner

  def _do_validate(self, schema: ToolSchema, args: dict) -> tuple[bool, Optional[str]]:
    return self._inner.validate(schema, args)

  def _do_run(self, schema: ToolSchema, args: dict, context: ExecutionContext) -> str:
    if schema.permissions.write:
      return self._simulate_write(schema, args)
    return self._inner.run(schema, args, context)

  def _simulate_write(self, schema: ToolSchema, args: dict) -> str:
    path = args.get("path", args.get("target", "unknown"))
    content = args.get("content", args.get("code", ""))
    preview = str(content)[:200]
    if len(str(content)) > 200:
      preview += "..."
    from utils.diff import unified_diff
    original = ""
    try:
      if _check_file_exists(path):
        with open(path, "r", encoding="utf-8") as f:
          original = f.read()
    except Exception:
      pass
    diff = unified_diff(original, content, path)
    if diff:
      return f"[Dry Run] 将修改 {path}:\n{diff}"
    return (
      f"[Dry Run] 将写入 {len(str(content)):,} 字符到 {path}\n"
      f"预览: {preview}"
    )


def _check_file_exists(path: str) -> bool:
  import os
  return os.path.isfile(path)


# ========== Chain 执行器（工具流水线）==========

@dataclass
class ChainStep:
  tool: str
  args: dict = field(default_factory=dict)
  output_key: str = ""


class ChainExecutor(BaseExecutor):
  executor_type = "chain"

  def __init__(self, steps: list[dict] = None):
    self.steps = [ChainStep(**s) if isinstance(s, dict) else s for s in (steps or [])]

  def _do_validate(self, schema: ToolSchema, args: dict) -> tuple[bool, Optional[str]]:
    if not self.steps:
      return False, "chain 执行器至少需要一个 step"
    return True, None

  def _do_run(self, schema: ToolSchema, args: dict, context: ExecutionContext) -> str:
    from .registry import get_tool
    results = []
    step_outputs = {}

    for i, step in enumerate(self.steps):
      step_args = {k: self._resolve_value(v, step_outputs) for k, v in step.args.items()}

      tool_fn = get_tool(step.tool)
      if not tool_fn:
        return f"ChainError: step {i} 未知工具: {step.tool}"

      try:
        result = str(tool_fn(**step_args)) if callable(tool_fn) else str(tool_fn)
      except Exception as e:
        return f"ChainError: step {i} ({step.tool}) 执行失败: {e}"

      results.append(result)
      step_outputs[str(i) if not step.output_key else step.output_key] = \
        self._build_step_output(result)

    return "\n".join(
      f"--- Step {i}: {s.tool} ---\n{r}"
      for i, (s, r) in enumerate(zip(self.steps, results))
    )

  @staticmethod
  def _build_step_output(result: str) -> dict:
    truncated = result[:50000] if len(result) > 50000 else result
    lines = truncated.strip().split("\n") if truncated else []
    return {
      "output": truncated,
      "lines": lines,
      "count": len(lines),
      "first_line": lines[0] if lines else "",
    }

  def _resolve_value(self, val, outputs: dict):
    """结构化解析引用，返回 Python 原生对象，不做字符串拼接"""
    if isinstance(val, str):
      return self._resolve_string_ref(val, outputs)
    if isinstance(val, list):
      return [self._resolve_value(v, outputs) for v in val]
    if isinstance(val, dict):
      return {k: self._resolve_value(v, outputs) for k, v in val.items()}
    return val

  def _resolve_string_ref(self, text: str, outputs: dict):
    """解析单层引用: {{steps.N.key}} → 实际值"""
    import re
    pattern = r'^\{\{steps\.(\w+)\.(\w+)\}\}$'
    m = re.match(pattern, text.strip())
    if not m:
      return text
    step_key, sub_key = m.group(1), m.group(2)
    entry = outputs.get(step_key)
    if not entry:
      return text
    if sub_key == "output":
      return entry["output"]
    if sub_key == "first_line":
      return entry["first_line"]
    if sub_key == "count":
      return entry["count"]
    if sub_key.startswith("line_"):
      try:
        idx = int(sub_key.split("_")[1])
        return entry["lines"][idx] if idx < len(entry["lines"]) else ""
      except (ValueError, IndexError):
        return ""
    return entry.get(sub_key, text)


# ========== MultiLang 执行器（预编译二进制）==========

class MultiLangExecutor(BaseExecutor):
  executor_type = "multilang"

  def __init__(self, binary: str = ""):
    self.binary = binary

  def _do_validate(self, schema: ToolSchema, args: dict) -> tuple[bool, Optional[str]]:
    ok, err = schema.validate_args(args)
    if not ok:
      return ok, err
    binary = self.binary or schema.metadata.get("binary", "")
    if not binary:
      return False, "multilang 执行器缺少 binary 字段"
    from security.permissions import sandbox_check
    ok, reason = sandbox_check("exec", binary)
    if not ok:
      return False, reason
    return True, None

  def _do_run(self, schema: ToolSchema, args: dict, context: ExecutionContext) -> str:
    import subprocess, json, signal
    binary = self.binary or schema.metadata.get("binary", "")
    cwd = context.workspace or schema.metadata.get("workspace", ".")
    timeout = schema.metadata.get("timeout", 30)
    env = {**os.environ, "TIAO_TOOL_NAME": schema.name, "_TIAO_SANDBOX": "1"}
    try:
      proc = subprocess.run(
        [binary, "--json"],
        input=json.dumps(args, ensure_ascii=False),
        capture_output=True, text=True, timeout=timeout,
        cwd=cwd if os.path.isdir(cwd) else None,
        env=env,
        start_new_session=True if os.name == "posix" else False,
      )
      result = json.loads(proc.stdout)
      status = result.get("status", "error")
      if status == "ok":
        return str(result.get("result", result.get("output", "")))
      return f"✗ 工具返回错误: {result.get('error', result.get('message', 'unknown'))}"
    except subprocess.TimeoutExpired:
      return f" 工具执行超时 ({timeout}s): {binary}"
    except json.JSONDecodeError:
      return f"✗ 工具返回非 JSON 输出: {proc.stdout[:500] if 'proc' in dir() else ''}"
    except FileNotFoundError:
      return f"✗ 可执行文件不存在: {binary}"
    except Exception as e:
      return f"✗ 执行错误: {e}"


# ========== HTTP 执行器（httpx 可选）==========

class HttpExecutor(BaseExecutor):
  executor_type = "http"

  def __init__(self, url: str = "", method: str = "POST", headers: dict = None):
    self.url = url
    self.method = method
    self.headers = headers or {}

  def _do_validate(self, schema: ToolSchema, args: dict) -> tuple[bool, Optional[str]]:
    if not self.url:
      self.url = schema.metadata.get("url", "")
    if not self.url:
      return False, "http 执行器缺少 url 配置"
    allowed_hosts = schema.metadata.get("allowed_hosts", [])
    if allowed_hosts:
      import urllib.parse as _up
      host = _up.urlparse(self.url).hostname or ""
      if host not in allowed_hosts:
        return False, f"不允许访问: {host}"
    return True, None

  def _do_run(self, schema: ToolSchema, args: dict, context: ExecutionContext) -> str:
    try:
      import httpx
      if self.method.upper() == "GET":
        resp = httpx.get(self.url, params=args, headers=self.headers, timeout=30)
      else:
        resp = httpx.post(self.url, json=args, headers=self.headers, timeout=30)
      resp.raise_for_status()
      return resp.text
    except ImportError:
      import urllib.request, urllib.parse as _urlparse, json as _j
      allowed_hosts = schema.metadata.get("allowed_hosts", [])
      if allowed_hosts:
        host = _urlparse.urlparse(self.url).hostname or ""
        if host not in allowed_hosts:
          return f"✗ 不允许访问: {host}"
      if self.method.upper() == "GET":
        qs = _urlparse.urlencode(args)
        req = urllib.request.Request(f"{self.url}?{qs}")
      else:
        data = _j.dumps(args).encode()
        req = urllib.request.Request(self.url, data=data, headers={"Content-Type": "application/json"})
      with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode()
    except Exception as e:
      return f"✗ HTTP 错误: {e}"


# ========== 执行器注册 ==========

_BUILTIN_EXECUTORS: dict[str, type[BaseExecutor]] = {
  "native": NativeExecutor,
  "sandbox": SandboxExecutor,
  "chain": ChainExecutor,
  "multilang": MultiLangExecutor,
  "http": HttpExecutor,
}


def register_executor_type(name: str, cls: type[BaseExecutor]):
  _BUILTIN_EXECUTORS[name] = cls


def create_executor(schema: ToolSchema, fn: Callable = None, **kwargs) -> BaseExecutor:
  executor_cls = _BUILTIN_EXECUTORS.get(schema.executor_type)
  if executor_cls is None:
    raise ValueError(f"未知执行器类型: {schema.executor_type}")
  if schema.executor_type == "native":
    if fn is None:
      raise ValueError(
        f"native 执行器需要 fn 参数 (工具: {schema.name})。"
        f"动态定义的工具请使用 executor_type: sandbox 并在 executor.code 中提供代码。"
      )
    return NativeExecutor(fn)
  if schema.executor_type == "sandbox":
    code = schema.metadata.get("code", "")
    if not code:
      code = kwargs.get("code", "")
    return SandboxExecutor(
      code=code,
      language=schema.metadata.get("language", kwargs.get("language", "python")),
    )
  if schema.executor_type == "chain":
    steps = kwargs.get("steps") or schema.metadata.get("steps", [])
    return ChainExecutor(steps=steps)
  if schema.executor_type == "multilang":
    binary = kwargs.get("binary") or schema.metadata.get("binary", "")
    return MultiLangExecutor(binary=binary)
  if schema.executor_type == "http":
    url = kwargs.get("url") or schema.metadata.get("url", "")
    return HttpExecutor(url=url, method=schema.metadata.get("method", "POST"))
  raise ValueError(f"不支持的执行器: {schema.executor_type}")
