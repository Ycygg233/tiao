# tool_dispatch.py - @ 工具调度（路由 + 统一执行框架）
# P0-13 修复：统一使用 errors.is_error_result() 判断工具返回的错误/警告
import os
import json
import logging

from rich.console import Console
from rich.markup import escape
from tools import get_tool, get_tool_entry, list_tools
from security.dialog import _confirm_or_skip
from tools.executors import ExecutionContext
from tools.errors import is_error_result

from styles import TIAO_THEME

console = Console(theme=TIAO_THEME)
log = logging.getLogger("tiao")


def handle_tool_call(text: str):
  if not text or not text.startswith("@"):
    return text

  raw = text[1:].strip()
  if not raw:
    console.print("[yellow]⚠ @ 后不能为空[/yellow]")
    return None

  if raw.startswith("/"):
    return _handle_path(raw)

  if raw.startswith("summarize"):
    return _handle_summarize(raw[len("summarize"):].strip())

  parts = raw.split(maxsplit=1)
  tool_name = parts[0]
  tool_arg = parts[1] if len(parts) > 1 else ""

  entry = get_tool_entry(tool_name)
  if not entry:
    console.print(f"[yellow]⚠ 未知工具: {tool_name}[/yellow]")
    console.print(f"[dim]可用工具: {', '.join(sorted(list_tools().keys()))}, summarize[/dim]")
    return None

  schema = entry["schema"]
  executor = entry["executor"]

  _MAX_JSON_BYTES = 100_000
  parser = schema.metadata.get("parser")
  try:
    if parser:
      args = parser(tool_arg)
    elif tool_arg:
      if len(tool_arg) > _MAX_JSON_BYTES:
        console.print(f"[red]✗ JSON 参数过大 ({len(tool_arg)}B)，超过 {_MAX_JSON_BYTES}B 限制，已拒绝[/red]")
        return None
      try:
        args = json.loads(tool_arg)
      except json.JSONDecodeError:
        console.print(f"[red]✗ 参数 JSON 解析失败，已拒绝执行。原始参数: {tool_arg[:80]}[/red]")
        return None
    else:
      args = {}
  except ValueError as e:
    console.print(f"[red]✗ 参数错误: {e}[/red]")
    return None

  try:
    result = executor.run(schema, args, ExecutionContext())
  except Exception as e:
    log.error("工具执行异常 %s: %s", tool_name, e)
    console.print(f"[red]✗ 执行失败: {e}[/red]")
    return None

  # 审计钩子
  try:
    from security.audit import get_engine
    get_engine().log_event("tool_call", f"tools.{tool_name}",
                 json.dumps({"args": args, "result": str(result)[:200]},
                       ensure_ascii=False))
  except Exception:
    pass

  if is_error_result(result):
    prefix_icon = "✗" if result.startswith("错误:") else "⚠"
    console.print(f"[color(167)]✗ {escape(str(result))}[/color(167)]")
    return None

  return (f"工具 `{tool_name}` 返回：\n```\n{result}\n```\n\n"
      "【注意】请基于以上实际内容回答，不要编造不存在的代码或文件。")


# ---- 路径分支 ----

def _auto_set_workspace(path: str):
  try:
    from security.permissions import get_workspace, set_workspace
    current = get_workspace()
    if not current:
      set_workspace(path)
      console.print(f"[dim]工作区已自动设为: {path}[/dim]")
  except Exception:
    pass


def _handle_path(raw: str):
  quoted_path = None
  if raw.startswith('"') or raw.startswith("'"):
    quote = raw[0]
    end = raw.find(quote, 1)
    if end > 1:
      quoted_path = raw[1:end]
      raw = raw[end + 1:].strip()

  if quoted_path:
    path = quoted_path
    user_query = raw
  else:
    parts = raw.split(maxsplit=1)
    path = parts[0]
    user_query = parts[1] if len(parts) > 1 else ""

  if not path or path == "/":
    console.print("[yellow]⚠ 路径不能为空[/yellow]")
    return None

  try:
    if os.path.isdir(path):
      result = get_tool("scan_dir")(path)
      tool_used = "scan_dir"
      head = f" 目录 `{path}` 扫描："
      _auto_set_workspace(path)
    else:
      result = get_tool("read_file")(path)
      tool_used = "read_file"
      head = f"分析以下文件 `{path}`：\n```"
  except Exception as e:
    log.error("路径访问异常: %s", e)
    console.print(f"[red]✗ 访问失败: {e}[/red]")
    return None

  # 审计钩子
  try:
    from security.audit import get_engine
    get_engine().log_event("tool_call", f"tools.{tool_used}",
                 json.dumps({"args": {"path": path}, "result": str(result)[:200]},
                       ensure_ascii=False))
  except Exception:
    pass

  # P0-13 修复：统一使用 is_error_result() 判断
  if is_error_result(result):
    prefix_icon = "✗" if result.startswith("错误:") else ""
    console.print(f"[red]{prefix_icon}{result}[/red]")
    return None

  msg = f"{head}\n{result}"
  if not os.path.isdir(path):
    msg += "\n```"
  if user_query:
    msg += f"\n\n用户附加提问: {user_query}"
  msg += "\n\n【注意】请基于以上实际内容回答，不要编造不存在的代码或文件。"
  return msg


# ---- @summarize 语法糖 ----

def _handle_summarize(path: str):
  if not path or not os.path.isdir(path):
    console.print("[yellow]⚠ summarize 需要有效的目录路径[/yellow]")
    return None
  scan_result = get_tool("scan_dir")(path)
  # P0-13 修复：统一使用 is_error_result() 判断
  if is_error_result(scan_result):
    return scan_result
  return (
    f"请基于以下项目目录扫描结果，生成一份项目摘要：\n\n"
    f"{scan_result}\n\n"
    f"请总结：1) 项目用途 2) 技术栈 3) 主要模块和入口文件 "
    f"4) 关键依赖。不要编造不存在的内容。"
  )
