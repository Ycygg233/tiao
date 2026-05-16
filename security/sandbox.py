"""security/sandbox.py"""
import os
import ast
import io
import sys as _sys
import shutil
import stat
import time as _time; _real_time = _time
import threading
import platform
from datetime import datetime
from typing import Optional
from security.dialog import _confirm_or_skip, set_auto_confirm
from security.checkpoint import _backup_file

_PROTECTED_ROOT = os.path.normpath(
  os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
).replace("\\", "/")

# ========== 零宽字符防护 ==========

_ZERO_WIDTH_CHARS = frozenset(
  "\u200B\u200C\u200D\u200E\u200F\uFEFF\u2060\u2061\u2062\u2063\u2064"
)


def has_zero_width(text: str) -> bool:
  return any(c in _ZERO_WIDTH_CHARS for c in text)


# ========== 路径白名单 ==========

_BASE_SANDOX_DIR = os.path.normpath(
  os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)

ALLOWED_PATHS = [
  "/storage/emulated/0/Download",
  "/sdcard/Download",
  "/storage/emulated/0/Documents",
  "/sdcard/Documents",
  "/storage/emulated/0/Pictures",
  "/sdcard/Pictures",
  "/storage/emulated/0/Music",
  "/sdcard/Music",
  "/storage/emulated/0/Movies",
  "/sdcard/Movies",
  "/storage/emulated/0/DCIM",
  "/sdcard/DCIM",
  "/data/data/com.termux/files/home",
  _BASE_SANDOX_DIR,
]

DEFAULT_ALLOWED_PATHS = [
  "/storage/emulated/0/Documents",
  "/sdcard/Documents",
  "/data/data/com.termux/files/home",
  _BASE_SANDOX_DIR,
]


EXEC_WHITELIST = [
  "/data/data/com.termux/files/usr/bin/",
  "/data/data/com.termux/files/home/.tiao_tools/bin/",
  "/storage/emulated/0/.tiao_tools/bin/",
  "/sdcard/.tiao_tools/bin/",
]


def _sandbox_check_exec(binary: str) -> tuple:
  if not binary.startswith("/"):
    return False, "可执行路径必须以 / 开头"
  allowed = any(_path_startswith(binary, p) for p in EXEC_WHITELIST)
  if not allowed:
    return False, f"可执行文件不在白名单内: {binary}。允许路径: {EXEC_WHITELIST}"
  if not os.path.isfile(binary):
    return False, f"可执行文件不存在: {binary}"
  if not os.access(binary, os.X_OK):
    return False, f"文件不可执行: {binary}"
  return True, "ok"

_SYSTEM_BLOCKED = [
  "/system", "/data/data/com.termux", "/vendor", "/etc", "/proc",
]

# ========== 提权状态（全局，线程安全） ==========
# 注意：必须用全局变量而非 threading.local()，因为 Web 模式下
# HTTP 请求由线程池的不同线程处理，threading.local() 会导致
# 在一个线程设了 su+，另一个线程读取时仍然是默认值。

_SUDO_PERSIST_FILE = os.path.join(os.path.expanduser("~"), ".tiao_sudo.json")
_SUDO_KEY_FILE = os.path.join(os.path.expanduser("~"), ".tiao_key")

_sudo_level = ""
_sudo_lock = threading.Lock()


def set_sudo_level(level: str):
  global _sudo_level
  with _sudo_lock:
    _sudo_level = level


def get_sudo_level() -> str:
  with _sudo_lock:
    return _sudo_level


def is_sudo_min(min_level: str) -> bool:
  current = get_sudo_level()
  order = {"su": 1, "su+": 2}
  return order.get(current, 0) >= order.get(min_level, 0)


def save_sudo_persist(level: str):
  import json as _json
  try:
    data = {"level": level, "updated": datetime.now().isoformat()}
    with open(_SUDO_PERSIST_FILE, "w", encoding="utf-8") as f:
      _json.dump(data, f, ensure_ascii=False, indent=2)
  except Exception:
    pass


def clear_sudo_persist():
  try:
    if os.path.isfile(_SUDO_PERSIST_FILE):
      os.remove(_SUDO_PERSIST_FILE)
  except Exception:
    pass


# ========== __exec__ 沙箱内命令执行 ==========

_EXEC_CMD_WHITELIST = {
  "date", "whoami", "git",
  # P1 扩展：日常 CLI 工具
  "ls", "echo", "cat", "pwd", "which", "head", "tail",
  "grep", "find", "wc", "sort", "uniq", "mkdir", "touch",
  "mv", "cp", "rm",
}
# 某些 shell 逃逸工具是 su+ 级能力的唯一通道，su 级别不可调用

_EXEC_TERMUX_PREFIX = "termux-"


def _check_exec_cmd(cmd_name: str) -> str:
  if is_sudo_min("su+"):
    return ""
  if cmd_name.startswith(_EXEC_TERMUX_PREFIX) or cmd_name in _EXEC_CMD_WHITELIST:
    return ""
  return f"✗ __exec__ 白名单拒绝: {cmd_name}"


def __exec__(command: str) -> str:
  import subprocess as _sp
  import shlex as _shlex
  cmd_parts = command.split(maxsplit=1)
  if not cmd_parts:
    return "✗ __exec__ 命令为空"
  cmd_name = cmd_parts[0]
  err = _check_exec_cmd(cmd_name)
  if err:
    return err
  args = _shlex.split(command)
  if not is_sudo_min("su+"):
    _path_args = [a for a in args[1:] if a.startswith("/")]
    for idx, arg in enumerate(args[1:], 1):
      if arg.startswith("/"):
        if cmd_name == "mv":
          _path_idx = _path_args.index(arg)
          action = "delete" if _path_idx == 0 else "write"
        elif cmd_name in ("rm",):
          action = "delete"
        elif cmd_name in ("cp", "touch"):
          action = "write"
        else:
          action = "read"
        ok, reason = sandbox_check(action, arg)
        if not ok:
          return f"✗ __exec__ 路径拒绝: {arg} — {reason}"
  import logging as _log
  _log.getLogger("tiao").warning("SU-%s: __exec__(%s)", get_sudo_level(), command)
  exec_timeout = None if is_sudo_min("su+") else 300
  try:
    r = _sp.run(args, shell=False, capture_output=True, text=True, timeout=exec_timeout)
    out = r.stdout.strip()
    err_out = r.stderr.strip()
    if err_out:
      out += ("\n" if out else "") + err_out
    return out or "(无输出)"
  except _sp.TimeoutExpired:
    limit_str = "无限制" if exec_timeout is None else f"{exec_timeout}s"
    return f"✗ __exec__ 超时（{limit_str}）"
  except Exception as e:
    return f"✗ __exec__ 失败: {e}"

# ========== 全局工作区（线程安全）==========
# 与 sudo 同理：Web 模式下线程池跨线程，必须用全局变量 + 锁

_workspace_value: Optional[str] = None
_workspace_lock = threading.Lock()


def set_workspace(path: Optional[str]):
  global _workspace_value
  with _workspace_lock:
    if path:
      abspath = os.path.abspath(path)
      if os.path.exists(abspath):
        abspath = os.path.realpath(abspath)
      _workspace_value = abspath
    else:
      _workspace_value = None


def get_workspace() -> Optional[str]:
  with _workspace_lock:
    return _workspace_value


def is_in_workspace(path: str) -> bool:
  ws = get_workspace()
  if not ws:
    return False
  try:
    abs_ws = os.path.abspath(ws)
    abs_path = os.path.abspath(path)
    if os.path.exists(abs_path):
      abs_path = os.path.realpath(abs_path)
    return _path_startswith(abs_path, abs_ws + "/") or abs_path == abs_ws
  except Exception:
    return _path_startswith(path, ws + "/") or path == ws


def _get_workspace_context(target: str) -> Optional[dict]:
  ws = get_workspace()
  if not ws:
    return None
  try:
    resolved = _resolve_path(target)
    rel = os.path.relpath(resolved, ws)
    if rel.startswith(".."):
      return None
    return {"workspace": ws, "relative": rel}
  except Exception:
    return None

# ========== 路径白名单 ==========


def _path_startswith(path: str, prefix: str) -> bool:
  """路径前缀匹配（统一分隔符，Windows 上忽略大小写）"""
  a = path.replace("\\", "/").rstrip("/") + "/"
  b = prefix.replace("\\", "/").rstrip("/") + "/"
  if platform.system() == "Windows":
    return a.casefold().startswith(b.casefold())
  return a.startswith(b)


def _resolve_path(target: str) -> str:
  """正规化路径并尽可能解析符号链接，防 ../ 遍历和软链逃逸"""
  try:
    resolved = os.path.normpath(target)
    if platform.system() == "Windows":
      resolved = resolved.replace("\\", "/")
    if os.path.exists(resolved):
      real = os.path.realpath(resolved)
      if real:
        real_str = real.replace("\\", "/") if platform.system() == "Windows" else real
        resolved = real_str
    return resolved
  except (OSError, ValueError):
    return target


def sandbox_check(action: str, target: str) -> tuple:
  if not target:
    return False, "路径不能为空"
  if has_zero_width(target):
    return False, "路径包含非法字符（零宽字符）"
  if not target.startswith("/"):
    is_windows_abs = platform.system() == "Windows" and len(target) >= 3 and target[1:3] == ":\\"
    if not is_windows_abs:
      return False, "路径必须以 / 开头"

  resolved = _resolve_path(target)

  if action in ("write", "delete", "create") and _path_startswith(resolved, _PROTECTED_ROOT):
    return False, "项目目录受保护，只允许读操作"

  if action == "exec":
    if is_sudo_min("su+"):
      return True, "ok"
    return _sandbox_check_exec(resolved)

  # API Key 文件硬保护（任何提权级别均不可覆盖写入）
  if action in ("write", "delete") and resolved in (_SUDO_KEY_FILE, _SUDO_PERSIST_FILE):
    return False, "API Key / 鉴权配置文件禁止覆盖，请先手动删除后再操作"

  if is_sudo_min("su+"):
    for banned in _SYSTEM_BLOCKED:
      if _path_startswith(resolved, banned):
        return False, f"禁止操作系统关键路径: {target}"
    return True, "ok"

  if not is_sudo_min("su") and action in ("write", "delete", "create"):
    return False, "默认级别只允许读操作，请使用 /su 或 /su+ 提权"

  # 默认级别：读走全路径，写走限定路径
  if action in ("write", "delete", "create") and not is_sudo_min("su"):
    paths = DEFAULT_ALLOWED_PATHS
  else:
    paths = ALLOWED_PATHS
  if paths:
    allowed = any(_path_startswith(resolved, p) for p in paths)
    if not allowed:
      ws = get_workspace()
      if ws and _path_startswith(resolved, ws):
        pass
      else:
        return False, f"路径不在白名单内: {target}"
  if action in ("delete", "write", "read", "create", "exec"):
    for banned in _SYSTEM_BLOCKED:
      if _path_startswith(resolved, banned):
        return False, f"禁止操作系统关键路径: {target}"
  return True, "ok"


# ========== AST 沙箱 + Python 执行 ==========

_run_python_lock = threading.Lock()


def _check_dangerous_ast(code: str) -> Optional[str]:
  try:
    tree = ast.parse(code)
  except SyntaxError as e:
    return f"语法错误: {e}"

  if is_sudo_min("su+"):
    return None

  if get_sudo_level() == "su":
    for node in ast.walk(tree):
      if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in (
          "exec", "eval", "__import__",
        ):
          return f"检测到危险函数调用: {node.func.id}"
    return None

  _DANGEROUS_ATTRS = frozenset({
    "__class__", "__bases__", "__subclasses__", "__globals__",
    "__code__", "__builtins__", "__import__", "__reduce__",
    "__mro__", "__getattribute__", "__del__", "__setattr__",
    "__delattr__", "__init_subclass__", "__class_getitem__",
    "__base__", "__mro_entries__", "__subclasshook__",
    "__getattr__", "__getitem__", "__get__",
    "tb_frame", "tb_next", "f_globals", "f_locals", "f_back",
    "gi_frame", "gi_code", "cr_frame", "cr_code",
    "__self__", "__func__", "__closure__",
  })

  for node in ast.walk(tree):
    if isinstance(node, ast.Attribute):
      if node.attr in _DANGEROUS_ATTRS:
        return f"检测到危险属性访问: {node.attr}"
    if isinstance(node, ast.Call):
      if isinstance(node.func, ast.Name) and node.func.id in (
        "exec", "eval", "compile", "__import__", "open",
        "getattr", "hasattr", "setattr", "vars", "dir",
        "breakpoint", "input",
      ):
        return f"检测到危险函数调用: {node.func.id}"
      if isinstance(node.func, ast.Attribute) and node.func.attr in (
        "__subclasses__", "__bases__", "__mro__", "__getattribute__",
        "__del__", "__setattr__", "__delattr__",
      ):
        return f"检测到危险方法调用: {node.func.attr}"
    if isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
      for alias in node.names:
        if alias.name in ("os", "sys", "subprocess", "shutil", "ctypes",
                 "builtins", "importlib", "code", "codeop",
                 "compileall", "py_compile", "sysconfig"):
          return f"检测到危险导入: {alias.name}"
  return None


def _build_restricted_os():
  """返回受限 os 对象：只暴露无害函数，用于 /su 级别体验修复。
  所有文件/目录操作均经 sandbox_check，与 __exec__ 的白名单命令设计保持一致。"""
  _real_os = os
  class _RestrictedOS:
    @staticmethod
    def listdir(path):
      ok, reason = sandbox_check("read", path)
      if not ok:
        raise PermissionError(f"os.listdir 沙箱拒绝: {path} — {reason}")
      return _real_os.listdir(path)

    getenv = staticmethod(_real_os.getenv)

    @staticmethod
    def mkdir(path):
      ok, reason = sandbox_check("create", path)
      if not ok:
        raise PermissionError(f"os.mkdir 沙箱拒绝: {path} — {reason}")
      return _real_os.mkdir(path)

    path = _real_os.path
    sep = _real_os.sep
    environ = dict(_real_os.environ) # 快照副本

    def __getattr__(self, name):
      raise AttributeError(f"受限 os 不支持: os.{name}，如需使用请升级到 /su")
  return _RestrictedOS()


def _terminate_thread(thread: threading.Thread):
  import logging as _log
  _logger = _log.getLogger("tiao")
  thread.join(timeout=2)
  if thread.is_alive():
    _logger.warning("沙箱线程无法终止 (tid=%s)，残留后台运行", thread.ident)


def run_python(code: str, exec_vars: dict = None) -> str:
  if not is_sudo_min("su"):
    return "✗ 默认级别不允许执行 Python 代码，请使用 /su 或 /su+ 提权"
  with _run_python_lock:
    danger = _check_dangerous_ast(code)
    if danger:
      return f"✗ {danger}，执行已拒绝"

    safe_builtins = {
      "print": print, "len": len, "range": range,
      "int": int, "float": float, "str": str, "bool": bool,
      "list": list, "dict": dict, "set": set, "tuple": tuple,
      "enumerate": enumerate, "zip": zip, "map": map, "filter": filter,
      "sorted": sorted, "reversed": reversed,
      "min": min, "max": max, "sum": sum, "abs": abs,
      "type": type, "isinstance": isinstance,
      "True": True, "False": False, "None": None,
      "Exception": Exception, "ValueError": ValueError,
      "TypeError": TypeError, "KeyError": KeyError,
      "round": round, "chr": chr, "ord": ord, "repr": repr,
    }
    if is_sudo_min("su"):
      safe_builtins["__exec__"] = __exec__
      safe_builtins["__time__"] = lambda: _real_time.ctime()
      safe_builtins["__timestamp__"] = _real_time.time
      # P1：/su 级别预注入受限 os 对象（体验修复）
      safe_builtins["os"] = _build_restricted_os()
    else:
      # 非 su/su+ 级别不会走到这里（run_python 入口已拦截），此分支为防御性保留
      safe_builtins["__time__"] = lambda: _real_time.ctime()
      safe_builtins["__timestamp__"] = _real_time.time
    if is_sudo_min("su+"):
      safe_builtins["json"] = __import__("json")
      safe_builtins["open"] = open
      safe_builtins["__import__"] = __builtins__["__import__"]
    if is_sudo_min("su+"):
      import types
      safe_globals = {"__builtins__": dict(__builtins__)}
      safe_globals["__builtins__"].pop("breakpoint", None)
      safe_globals["__builtins__"].pop("help", None)
      safe_globals["__builtins__"].update({
        k: v for k, v in safe_builtins.items()
        if k not in safe_globals["__builtins__"]
      })
    else:
      safe_globals = {"__builtins__": safe_builtins}
      import types
      safe_globals["__builtins__"] = types.MappingProxyType(safe_builtins)
    safe_globals["__name__"] = "__sandbox__"
    safe_globals["__doc__"] = None
    safe_globals["__package__"] = None
    safe_globals["__spec__"] = None

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    result = [None]
    error = [None]
    done = [False]

    def _run():
      old_stdout = _sys.stdout
      old_stderr = _sys.stderr
      _sys.stdout = stdout_buf
      _sys.stderr = stderr_buf
      try:
        exec(code, safe_globals, exec_vars or {})
        result[0] = stdout_buf.getvalue()
      except Exception as e:
        error[0] = str(e)
      finally:
        _sys.stdout = old_stdout
        _sys.stderr = old_stderr
        done[0] = True

    thread = threading.Thread(target=_run, daemon=False)
    thread.start()
    timeout = None if is_sudo_min("su+") else 300
    thread.join(timeout=timeout)

    if not done[0]:
      _terminate_thread(thread)
      limit = "无限制" if timeout is None else f"{timeout}s"
      return f"错误: 执行超时（{limit}）"

    if error[0]:
      err_text = stderr_buf.getvalue()
      out = f"错误: {error[0]}"
      if err_text:
        out += f"\n{err_text.strip()}"
      return out

    output = (result[0] or "").strip()
    err_output = stderr_buf.getvalue().strip()
    if err_output:
      output += f"\n[stderr]\n{err_output}"
    return output or "(无输出)"
