import os
import shutil
import threading
import logging
from datetime import datetime
from typing import Optional, Tuple
import time as _time

log = logging.getLogger("tiao")

# tools/sandbox.py -> security/checkpoint.py — 事务回滚
"""security/checkpoint.py — 备份机制 + 撤销"""

# ========== 备份机制 ==========

from session import SESSION_DIR # FIXME: 避免循环依赖
_BACKUP_DIR = os.path.join(SESSION_DIR, "backups")
_last_backup: Optional[Tuple[str, str]] = None
_backup_lock = threading.Lock()
_backup_count = 0
_BACKUP_TTL_SECONDS = 7 * 24 * 3600 # 7 天


def _prune_old_backups():
  """每 50 次备份清理超过 7 天的旧备份"""
  try:
    if not os.path.isdir(_BACKUP_DIR):
      return
    cutoff = _time.time() - _BACKUP_TTL_SECONDS
    for fname in os.listdir(_BACKUP_DIR):
      fpath = os.path.join(_BACKUP_DIR, fname)
      try:
        if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
          os.remove(fpath)
      except OSError:
        pass
  except Exception:
    pass


def _backup_file(path: str) -> Optional[str]:
  global _last_backup, _backup_count
  if not os.path.isfile(path):
    return None
  try:
    os.makedirs(_BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe = path.replace("/", "_").replace("\\", "_")
    backup_path = os.path.join(_BACKUP_DIR, f"{ts}_{safe}")
    with _backup_lock:
      shutil.copy2(path, backup_path)
      _last_backup = (backup_path, path)
      _backup_count += 1
    if _backup_count % 50 == 0:
      _prune_old_backups()
    return backup_path
  except Exception:
    return None


def undo_last() -> str:
  global _last_backup
  with _backup_lock:
    if not _last_backup:
      return "⚠ 没有可撤销的操作"
    backup_path, original_path = _last_backup
  if not os.path.isfile(backup_path):
    return f"⚠ 备份文件不存在: {backup_path}"
  try:
    shutil.copy2(backup_path, original_path)
    with _backup_lock:
      _last_backup = None
    return f"✓ 已恢复: {original_path}（来自备份）"
  except Exception as e:
    return f"错误: 恢复失败 - {e}"


def _generate_diff(path: str, original: str, modified: str) -> str:
  from utils.diff import unified_diff
  return unified_diff(original, modified, path)

