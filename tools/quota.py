# tools/quota.py - 工具调用配额追踪
# 默认关闭（无限制），通过 /quota <N> 设定额度
# 额度用完后工具调用被拒绝，直到重置或调高额度
import threading
from typing import Optional

_quota_limit = 0       # 0 = 无限制
_quota_used = 0
_quota_lock = threading.Lock()


def set_quota(limit: int):
  """设置额度上限，0 = 无限制"""
  global _quota_limit, _quota_used
  with _quota_lock:
    _quota_limit = limit
    _quota_used = 0


def get_quota() -> tuple:
  """返回 (limit, used)"""
  with _quota_lock:
    return _quota_limit, _quota_used


def check_quota() -> bool:
  """检查是否还有额度，消耗一次调用。返回 True=允许, False=额度耗尽"""
  global _quota_used
  with _quota_lock:
    if _quota_limit == 0:
      return True
    if _quota_used >= _quota_limit:
      return False
    _quota_used += 1
    return True
