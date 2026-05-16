"""security/permissions.py — 零宽字符防护 + 从 sandbox.py 统一 re-export

所有路径白名单、沙箱检查、提权状态等安全逻辑的唯一实现在 sandbox.py。
此模块仅保留 has_zero_width，其余符号从 sandbox.py 透传。
"""
# ========== 零宽字符防护 ==========

_ZERO_WIDTH_CHARS = frozenset(
  "\u200B" # 零宽空格
  "\u200C" # 零宽非连接符
  "\u200D" # 零宽连接符
  "\u200E" # 从左到右标记
  "\u200F" # 从右到左标记
  "\uFEFF" # BOM
  "\u2060" # 单词连接符
  "\u2061" # 函数应用
  "\u2062" # 隐形乘号
  "\u2063" # 隐形分隔符
  "\u2064" # 隐形加号
)


def has_zero_width(text: str) -> bool:
  return any(c in _ZERO_WIDTH_CHARS for c in text)


# ========== 以下符号唯一实现在 sandbox.py，此处透传 ==========

from .sandbox import ( # noqa: E402, F401
  has_zero_width,
  set_sudo_level,
  get_sudo_level,
  is_sudo_min,
  save_sudo_persist,
  clear_sudo_persist,
  _path_startswith,
  _resolve_path,
  sandbox_check,
  set_workspace,
  get_workspace,
  is_in_workspace,
  _get_workspace_context,
  ALLOWED_PATHS,
  DEFAULT_ALLOWED_PATHS,
)