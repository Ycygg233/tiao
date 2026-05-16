"""security/ — 安全基础设施

独立于 tools/ 的工具集，提供权限、沙箱、审计、备份等安全能力。
"""

from .permissions import (
  has_zero_width, set_sudo_level, get_sudo_level, is_sudo_min,
  save_sudo_persist, clear_sudo_persist,
  _path_startswith, _resolve_path, sandbox_check,
  ALLOWED_PATHS, DEFAULT_ALLOWED_PATHS,
)
from .audit import (
  get_engine,
)
from .dialog import (
  set_auto_confirm, _get_auto_confirm, _confirm_or_skip,
  _set_confirm_callback,
)
from .checkpoint import (
  _backup_file, undo_last, _prune_old_backups, _generate_diff,
)
from .sandbox import (
  run_python, __exec__, _check_dangerous_ast, _build_restricted_os,
  set_workspace, get_workspace, is_in_workspace, _get_workspace_context,
)
from .backup import (
  backup_now, backup_alert, backup_version,
  get_backup_engine,
)
