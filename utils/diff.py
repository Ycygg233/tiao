# utils/diff.py - 统一 Diff 生成器
"""统一 diff 输出格式：--- a/path, +++ b/path, @@ ... @@。
同时提供 stats 解析，供前端展示变化统计。"""

import difflib
from typing import Optional


def unified_diff(old: str, new: str, path: str, context: int = 3) -> str:
  """生成标准 unified diff，格式与 diff2html 兼容"""
  if old == new:
    return ""
  orig_lines = old.splitlines(keepends=True)
  mod_lines = new.splitlines(keepends=True)
  diff = difflib.unified_diff(
    orig_lines, mod_lines,
    fromfile=f"a/{path}",
    tofile=f"b/{path}",
    n=context,
  )
  return "".join(diff)


def parse_diff_stats(diff_text: str) -> tuple[int, int, str]:
  """解析 diff 的增删行数，返回 (additions, deletions, summary)"""
  if not diff_text:
    return 0, 0, "no changes"
  adds = 0
  dels = 0
  for line in diff_text.splitlines():
    if line.startswith("+") and not line.startswith("+++"):
      adds += 1
    elif line.startswith("-") and not line.startswith("---"):
      dels += 1
  summary = f"+{adds} -{dels}"
  return adds, dels, summary


def is_diff_output(text: str) -> bool:
  """检测文本是否为 diff 输出"""
  if not text:
    return False
  return any(marker in text for marker in ("--- a/", "+++ b/", "@@ ", "diff --git"))
