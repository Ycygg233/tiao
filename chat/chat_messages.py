"""chat_messages.py — 对话消息处理（裁剪 + 清洗）

从 chat_core.py 拆分，职责独立，无循环依赖。
"""
import threading
import logging
from config import CONFIG, valert
from utils import count_tokens_messages

log = logging.getLogger("tiao")


def _trim_messages(messages: list, messages_lock=None):
  if not CONFIG.get("context_limiter_enabled", True):
    return
  max_tokens = CONFIG.get("max_history_tokens", 1000000)
  min_rounds = CONFIG.get("min_history_rounds", 6)
  lock = messages_lock or threading.Lock()
  with lock:
    total_tokens = count_tokens_messages(messages)
    if total_tokens <= max_tokens:
      return
    log.debug("对话历史超过上限，开始裁剪 (tokens=%d, limit=%d)", total_tokens, max_tokens)
    if not messages:
      return
    system = messages[0]
    rest = messages[1:]
    token_counts = [count_tokens_messages([m]) for m in rest]
    keep = []
    total = count_tokens_messages([system])
    _rounds_kept = 0

    for i in range(len(rest) - 1, -1, -1):
      m = rest[i]
      tc = token_counts[i]
      role = m.get("role")
      if role == "user":
        _rounds_kept += 1
        keep.append(m)
        total += tc
      elif _rounds_kept < min_rounds:
        keep.append(m)
        total += tc
      elif total + tc <= max_tokens:
        keep.append(m)
        total += tc

    keep.reverse()

    while total > max_tokens and len(keep) > min_rounds:
      for idx in range(len(keep)):
        if keep[idx].get("role") != "user" and keep[idx].get("role") != "system":
          total -= count_tokens_messages([keep.pop(idx)])
          break
      else:
        break

    while total > max_tokens and keep:
      if keep[0].get("role") == "user":
        break
      total -= count_tokens_messages([keep.pop(0)])

    total_before = len(messages)
    messages.clear()
    messages.append(system)
    messages.extend(keep)
    log.debug("裁剪完成: %d 条 → %d 条 (tokens=%d, limit=%d, 保底=%d轮)",
          total_before, len(messages), total, max_tokens, _rounds_kept)


def _sanitize_messages(msgs: list, strip_reasoning: bool = False, model: str = "") -> list:
  allowed = {"role", "content", "tool_calls", "tool_call_id", "name", "reasoning_content"}
  _is_deepseek = "deepseek" in model.lower() if model else False
  msgs = [dict(m) for m in msgs]
  for m in msgs:
    if strip_reasoning and "reasoning_content" in m:
      if "tool_calls" not in m:
        del m["reasoning_content"]
    for k in list(m.keys()):
      if k not in allowed:
        del m[k]
    if _is_deepseek and m.get("role") == "assistant" and "tool_calls" in m and "reasoning_content" not in m:
      m["reasoning_content"] = ""
  cleaned = []
  pending_ids = {}
  for m in msgs:
    if m.get("role") == "assistant" and "tool_calls" in m:
      pending_ids = {tc.get("id", f"idx_{i}"): False for i, tc in enumerate(m["tool_calls"])}
      cleaned.append(m)
    elif m.get("role") == "tool":
      tc_id = m.get("tool_call_id", "")
      if tc_id in pending_ids:
        pending_ids[tc_id] = True
        cleaned.append(m)
      else:
        log.debug("丢弃孤立的 tool 消息: tool_call_id=%s", tc_id)
    else:
      if m.get("role") == "assistant":
        missing = [tid for tid, responded in pending_ids.items() if not responded]
        if missing:
          log.warning("移除不完整的 tool_calls 块: %d missing responses", len(missing))
          while cleaned and cleaned[-1].get("role") in ("assistant", "tool"):
            cleaned.pop()
        pending_ids = {}
      cleaned.append(m)
  missing = [tid for tid, responded in pending_ids.items() if not responded]
  if missing:
    log.warning("移除末尾不完整的 tool_calls 块: %d missing responses", len(missing))
    while cleaned and cleaned[-1].get("role") in ("assistant", "tool"):
      cleaned.pop()
  if cleaned != msgs:
    return cleaned
  return msgs
