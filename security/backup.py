# tools/backup.py — 项目备份引擎（开发者工具）
"""
BackupEngine:
 - tar.gz 打包项目源文件（排除 pycache/sessions/search_cache/daemon 数据）
 - 双槽滚动: old ← new, new ← fresh
 - 审计联动: high 告警时自动紧急备份
 - 大版本开关: /update 前保留快照（默认关闭）
 - 输出: /storage/emulated/0/_BACKUPS_/
"""
import os
import tarfile
import logging
from pathlib import Path
from datetime import datetime

log = logging.getLogger("tiao.backup")

BACKUP_ROOT = Path("/storage/emulated/0/_BACKUPS_")

EXCLUDE = {
  ".git", "__pycache__", ".pytest_cache",
  "sessions", "search_cache",
  ".tiao", "pool.db", "pool.pid", "pool.sock",
  "*.pyc", "*.tmp", "*.bak", ".gitignore",
}

SOURCE_FILES = {"requirements.txt", ".gitignore"}


class BackupEngine:

  def __init__(self, root: Path = None):
    self.root = root or BACKUP_ROOT

  @property
  def old_path(self) -> Path:
    return self.root / "tiao_old.tar.gz"

  @property
  def new_path(self) -> Path:
    return self.root / "tiao_new.tar.gz"

  # ── 滚动备份 ──

  def backup(self, reason: str = "manual"):
    self.root.mkdir(parents=True, exist_ok=True)
    # roll: old ← new
    if self.new_path.is_file():
      try:
        self.new_path.rename(self.old_path)
      except OSError:
        log.warning("滚动备份失败: %s → %s", self.new_path, self.old_path)
    path = self.new_path
    self._create(path)
    log.info("备份完成 (%s): %s (%s)", reason, path.name,
         self._fmt_size(path.stat().st_size))
    # 触发自动清理
    try:
      from config import CONFIG, valert
      if CONFIG.get("backup_auto_cleanup", False):
        days = CONFIG.get("backup_auto_cleanup_days", 7)
        self.auto_cleanup(days)
    except Exception:
      pass

  # ── 紧急备份（不滚动） ──

  def backup_alert(self, msg: str):
    self.root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = self.root / f"alert_{ts}.tar.gz"
    self._create(path)
    log.warning("紧急备份 (%s): %s (%s)", msg[:60], path.name,
           self._fmt_size(path.stat().st_size))

  # ── 大版本快照 ──

  def backup_version(self, tag: str):
    self.root.mkdir(parents=True, exist_ok=True)
    path = self.root / f"version_before_{tag}.tar.gz"
    self._create(path)
    log.info("版本快照: %s (%s)", path.name,
         self._fmt_size(path.stat().st_size))

  # ── 内部 ──

  def _create(self, path: Path):
    project = Path(__file__).resolve().parent.parent
    files = self._gather(project)
    # 原子写入：先写 .tmp，完成后 rename，防止中途失败产生残损文件
    tmp = path.with_suffix(".tmp.gz")
    with tarfile.open(str(tmp), "w:gz") as tar:
      for file_path, arc_name in files:
        tar.add(str(file_path), arcname=arc_name)
    tmp.rename(path)

  def _gather(self, project: Path):
    entries = []
    for root, dirs, filenames in os.walk(str(project)):
      dirs[:] = [d for d in dirs if d not in EXCLUDE]

      # Skip files matching exclude patterns
      for fname in filenames:
        if self._should_skip(fname):
          continue
        full = Path(root) / fname
        arc = full.relative_to(project)
        entries.append((full, str(arc)))
    return entries

  def _should_skip(self, fname: str) -> bool:
    # Exclude by pattern
    for pat in EXCLUDE:
      if pat in fname:
        return True
      if pat.startswith("*") and fname.endswith(pat[1:]):
        return True
    return False

  # ── 自动清理（备份后触发） ──

  def auto_cleanup(self, days: int = 7):
    """删除超过 N 天的 alert 和 version 备份，保留滚动备份。"""
    if not self.root.is_dir():
      return
    now = datetime.now()
    cutoff = now.timestamp() - days * 86400
    count = 0
    for f in self.root.glob("*.tar.gz"):
      # 跳过滚动备份
      if f.name in ("tiao_new.tar.gz", "tiao_old.tar.gz"):
        continue
      if f.stat().st_mtime < cutoff:
        f.unlink()
        count += 1
    if count:
      log.info("自动清理: 删除 %d 个超过 %d 天的备份", count, days)

  # ── 查询 ──

  def list_snapshots(self) -> list:
    if not self.root.is_dir():
      return []
    result = []
    for f in sorted(self.root.glob("*.tar.gz"), key=lambda x: x.stat().st_mtime, reverse=True):
      st = f.stat()
      result.append({
        "name": f.name,
        "size": self._fmt_size(st.st_size),
        "time": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
      })
    return result

  def cleanup(self, keep_alert: bool = True, keep: int = 0):
    """清理备份，保留最近 N 个。keep=0 时全部删除。"""
    if not self.root.is_dir():
      return
    snaps = sorted(self.root.glob("*.tar.gz"), key=lambda x: x.stat().st_mtime, reverse=True)
    if keep > 0 and len(snaps) <= keep:
      return
    to_delete = snaps[keep:] if keep > 0 else snaps
    for f in to_delete:
      if keep_alert and f.name.startswith("alert_"):
        continue
      f.unlink()
    log.info("备份已清理 (保留 %d 个)", keep)

  @staticmethod
  def _fmt_size(n: int) -> str:
    if n < 1024:
      return f"{n}B"
    if n < 1024 ** 2:
      return f"{n / 1024:.1f}KB"
    return f"{n / 1024 ** 2:.1f}MB"


# ── 全局函数（供外部模块直接调用） ──

_backup_engine = None


def get_backup_engine() -> BackupEngine:
  global _backup_engine
  if _backup_engine is None:
    _backup_engine = BackupEngine()
  return _backup_engine


def backup_now():
  get_backup_engine().backup("manual")


def backup_alert(msg: str):
  get_backup_engine().backup_alert(msg)


def backup_version(tag: str):
  get_backup_engine().backup_version(tag)
