"""utils/cleanup.py — 统一数据清理

双线正交策略：保留最近 N 个文件 ∪ 保留最近 N 天内的文件
（取并集，多保留不误删）

用法:
  from utils.cleanup import clean_expired

  # 保留最近 5 个 web 日志 或 3 天内（取并集）
  clean_expired("~/.tiao_data/logs/web_*.log", max_files=5, max_days=3)

  # 仅按天数
  clean_expired("~/.tiao_data/logs/logs.db", max_days=90)

  # 仅按数量
  clean_expired("~/.tiao_data/sessions/*.db", max_files=200)
"""

import os
import glob as _glob
import logging
from datetime import datetime, timezone

_log = logging.getLogger("tiao.cleanup")


def clean_expired(pattern: str, max_files: int = 0, max_days: int = 0) -> int:
  """双线清理：保留最近 N 个文件 ∪ 保留最近 N 天内的文件。

  参数:
    pattern: 文件匹配模式（支持 ~ 和 glob）
    max_files: 保留最近 N 个文件（0=不限）
    max_days: 保留最近 N 天内的文件（0=不限）

  返回:
    删除的文件数
  """
  expanded = os.path.expanduser(pattern)
  files = _glob.glob(expanded)

  if not files or (max_files <= 0 and max_days <= 0):
    return 0

  # 按 mtime 倒序排列（最新的在前）
  files_with_mtime = []
  for f in files:
    try:
      mtime = os.path.getmtime(f)
      files_with_mtime.append((f, mtime))
    except OSError:
      continue

  files_with_mtime.sort(key=lambda x: x[1], reverse=True)
  total = len(files_with_mtime)

  # 计算保留集（取并集）
  keep = set()

  if max_files > 0:
    # 保留最近 N 个
    for i in range(min(max_files, total)):
      keep.add(files_with_mtime[i][0])

  if max_days > 0:
    # 保留最近 N 天内的
    cutoff = datetime.now().timestamp() - max_days * 86400
    for f, mtime in files_with_mtime:
      if mtime >= cutoff:
        keep.add(f)

  # 删除不在保留集中的
  deleted = 0
  for f, _ in files_with_mtime:
    if f not in keep:
      try:
        os.remove(f)
        deleted += 1
      except OSError as e:
        _log.warning("清理失败 %s: %s", f, e)

  if deleted:
    _log.debug("清理 %d 个过期文件 (%d→%d) %s", deleted, total, len(keep), pattern)
  return deleted
