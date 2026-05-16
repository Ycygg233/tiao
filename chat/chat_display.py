"""chat_display.py — 对话展示（工具调用格式化 + Token 用量着色）

从 chat_core.py 拆分。依赖 chat_core 的模块状态通过参数或导入获取。
"""
import os
import logging
from rich.console import Console
from config import CONFIG, valert
from utils import count_tokens, count_tokens_messages

from styles import TIAO_THEME

log = logging.getLogger("tiao")
console = Console(theme=TIAO_THEME)

def _fmt_tokens(n: int) -> str:
  if n >= 1_000_000:
    return f"{n/1_000_000:.1f}M"
  if n >= 1_000:
    return f"{n/1_000:.1f}k"
  return str(n)

def _format_tool_call(tool_name: str, args: dict) -> str:
  if not args:
    return f"{tool_name}(...)"

  param = ""
  if tool_name in ("read_file", "write_file", "replace", "delete", "rename", "path_info", "create_dir"):
    param = args.get("path", args.get("new_path", ""))
  elif tool_name in ("scan_dir",):
    param = args.get("path", "")
  elif tool_name in ("find",):
    param = args.get("pattern", "") or args.get("path", "")
  elif tool_name in ("grep_symbol",):
    param = args.get("symbol_name", "") or args.get("path", "")
  elif tool_name in ("run_python",):
    code = args.get("code", "")
    first_line = code.strip().split("\n")[0][:30]
    return f"{tool_name}({first_line})"

  if not param or not isinstance(param, str):
    return f"{tool_name}(...)"

  if tool_name in ("scan_dir",):
    display = os.path.basename(param.rstrip("/")) + "/"
  elif tool_name in ("find",):
    display = args.get("pattern", "") or os.path.basename(param)
  else:
    display = os.path.basename(param)

  if not display:
    return f"{tool_name}(...)"

  if len(display) > 25:
    name_part, ext = os.path.splitext(display)
    display = name_part[:15] + ".." + ext

  return f"{tool_name}({display})"

def _print_token_usage(messages: list, reply_content: str,
            reasoning_content: str = ""):
  if not CONFIG.get("show_token_usage", True):
    return

  import chat._shared as _sh

  in_tok = count_tokens_messages(messages)
  out_tok = count_tokens(reply_content)
  if reasoning_content:
    out_tok += count_tokens(reasoning_content)

  _sh._total_input_tokens += in_tok
  _sh._total_output_tokens += out_tok
  total_in = _sh._total_input_tokens
  total_out = _sh._total_output_tokens
  sink = _sh._output_sink

  if sink:
    max_tok = CONFIG.get("max_history_tokens", 1000000)
    pct = in_tok / max_tok * 100 if max_tok else 0
    if pct > 95:
      color = "color(167)"
    elif pct > 80:
      color = "color(172)"
    elif pct < 50:
      color = "color(78)"
    else:
      color = "color(245)"
    sink({"type": "usage", "input": in_tok, "output": out_tok,
       "total_input": total_in, "total_output": total_out})
  else:
    max_tok = CONFIG.get("max_history_tokens", 1000000)
    pct = in_tok / max_tok * 100 if max_tok else 0
    if pct > 95:
      color = "color(167)"
    elif pct > 80:
      color = "color(172)"
    elif pct < 50:
      color = "color(78)"
    else:
      color = "color(245)"
    console.print(
      f"[{color}] ↑{_fmt_tokens(in_tok)}  ↓{_fmt_tokens(out_tok)}  "
      f"(↑{_fmt_tokens(total_in)}/↓{_fmt_tokens(total_out)})[/{color}]"
    )
