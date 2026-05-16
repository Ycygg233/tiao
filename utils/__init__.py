# utils/__init__.py - 通用工具函数
# P0-15 修复：count_tokens_messages 中 content 为 None 时导致的 TypeError
import json

def fmt_size(byte_size: int) -> str:
  if byte_size < 1024:
    return f"{byte_size}B"
  elif byte_size < 1024 ** 2:
    return f"{byte_size/1024:.1f}KB"
  elif byte_size < 1024 ** 3:
    return f"{byte_size/1024**2:.1f}MB"
  return f"{byte_size/1024**3:.2f}GB"


# ========== Token 精确计数（可选 tiktoken）= ==========

_tokenizer = None


def _get_tokenizer(model: str = ""):
  global _tokenizer
  if _tokenizer is not None:
    return _tokenizer
  try:
    import tiktoken
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as _TimeoutError
    with ThreadPoolExecutor(max_workers=1) as _pool:
      future = _pool.submit(tiktoken.get_encoding, "cl100k_base")
      _tokenizer = future.result(timeout=10)
  except Exception:
    _tokenizer = False
  return _tokenizer if _tokenizer is not False else None


def count_tokens(text: str) -> int:
  enc = _get_tokenizer()
  if enc:
    return len(enc.encode(text))
  from config import CONFIG, valert
  ratio = CONFIG.get("char_to_token_ratio", 3.0)
  return int(len(text) / ratio)


def count_tokens_messages(messages: list) -> int:
  """计算消息列表的 token 数量。修复：content 为 None 时安全处理。"""
  enc = _get_tokenizer()
  if enc:
    total = 0
    for m in messages:
      cached = m.get("_tc") if isinstance(m, dict) else None
      if cached is not None:
        total += cached
        continue
      content = m.get("content") or "" if isinstance(m, dict) else ""
      tc = len(enc.encode(content))
      if m.get("role") == "system":
        tc += 4
      if m.get("tool_calls"):
        tc += len(enc.encode(json.dumps(m["tool_calls"], ensure_ascii=False)))
      if m.get("reasoning_content"):
        reasoning = m.get("reasoning_content") or ""
        tc += len(enc.encode(reasoning))
      if isinstance(m, dict):
        m["_tc"] = tc
      total += tc
    return total
  from config import CONFIG, valert
  ratio = CONFIG.get("char_to_token_ratio", 3.0)
  chars = 0
  for m in messages:
    # P0-15 修复：同步修复 chars 计算分支
    content = m.get("content") or "" if isinstance(m, dict) else ""
    chars += len(content)
    if m.get("tool_calls"):
      chars += len(json.dumps(m["tool_calls"], ensure_ascii=False))
    if m.get("reasoning_content"):
      chars += len(m.get("reasoning_content") or "")
  return int(chars / ratio)


# ========== 256 色语义色板 ==========

class STYLE:
  """语义-样式映射（Rich 256 色）

  用法:
    console.print("成功", style=STYLE.success)
    console.print("警告", style=STYLE.warning)
  """
  border = "dim color(240)"     # 边框/结构
  separator = "color(238)"     # 分隔线
  meta = "color(245) italic"    # 次要文本/时间戳
  source = "color(67)"       # 钢蓝 · 来源标识
  keyword = "color(73)"       # 柔和青蓝 · 技术关键词
  action = "bold color(80)"     # 降刺青 · 工具调用
  waiting = "color(245)"      # 灰白 · 等待/思考中
  success = "color(78)"       # 柔和绿 · 成功确认
  warning = "color(172)"      # 暗金 · 警告
  error = "color(167) bold"     # 柔和红 · 错误
  fatal = "bold color(167)"     # 加粗 · 致命错误
  tag = "white bold"        # P0/P1 标签
  highlight = "bold"        # 高亮/标题
  code_bg = "color(250) on color(235)" # 代码/路径背景
