import threading
import logging

log = logging.getLogger("tiao")

"""security/dialog.py — 确认弹窗（Rich 终端提示）"""


_confirm_callback_lock = threading.Lock()
_confirm_callback = None
_auto_confirm_local = threading.local()


def set_auto_confirm(value: bool):
  _auto_confirm_local.value = value


def _get_auto_confirm() -> bool:
  return getattr(_auto_confirm_local, 'value', False)


def _set_confirm_callback(fn):
  global _confirm_callback
  _confirm_callback = fn


def _confirm_prompt(msg: str, options: str = "确认? (y/N)") -> str:
  """Rich 终端确认提示"""
  try:
    from rich.console import Console
    c = Console()
    ans = c.input(f"\n[yellow]\u26a0\ufe0f {msg}[/yellow]\n[bold]{options}[/bold] ").strip().lower()
    return ans
  except (KeyboardInterrupt, EOFError, Exception):
    return ""


def _confirm_or_skip(msg: str) -> bool:
  """确认弹窗：True=允许 | False=拒绝。选「不再询问」自动设 auto_confirm"""
  if _get_auto_confirm():
    return True
  cb = _confirm_callback
  if cb is not None:
    return cb(msg)
  ans = _confirm_prompt(msg, "允许 (y) | 不再询问 (a) | 取消 (N)")
  if ans == "a":
    set_auto_confirm(True)
    return True
  return ans in ("y", "yes")


