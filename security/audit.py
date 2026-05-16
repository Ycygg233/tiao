# security/audit.py — 结构化日志引擎
# 统一入口：log_event(type, module, data, level)
# 写入策略：buffer.jsonl（追加）→ 批量 flush → logs.db
import os
import json
import time
import logging
import threading
import sqlite3
from datetime import datetime
from typing import Optional

from config import DATA_DIR

_log = logging.getLogger("tiao.audit")

_LOG_DIR = os.path.join(DATA_DIR, "logs")
_DB_PATH = os.path.join(_LOG_DIR, "logs.db")
_BUFFER_FILE = os.path.join(_LOG_DIR, "buffer.jsonl")
_FLUSH_INTERVAL = 30       # 秒
_FLUSH_BATCH = 100          # 条数
_MAX_RESULTS = 200


def _ensure_db():
  os.makedirs(_LOG_DIR, exist_ok=True)
  db = sqlite3.connect(_DB_PATH, check_same_thread=False)
  db.execute("""
    CREATE TABLE IF NOT EXISTS logs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      event_type TEXT NOT NULL,
      module TEXT NOT NULL,
      data TEXT DEFAULT '',
      level TEXT DEFAULT 'info',
      created_at TEXT NOT NULL
    )""")
  db.execute("CREATE INDEX IF NOT EXISTS idx_logs_type ON logs(event_type)")
  db.execute("CREATE INDEX IF NOT EXISTS idx_logs_time ON logs(created_at)")
  db.commit()
  return db


class AuditEngine:
  def __init__(self):
    self._lock = threading.Lock()
    self._buffer_count = 0
    self._last_flush = time.time()
    self._db = None
    self._buf_fh = None
    self._dir_ready = False
    self._launch_time = datetime.now().isoformat()
    self._retention_days = 3
    import atexit
    atexit.register(self._flush)

  # ── 写入 ──

  def _ensure_dir(self):
    if not self._dir_ready:
      os.makedirs(os.path.dirname(_BUFFER_FILE), exist_ok=True)
      self._dir_ready = True

  def _open_buf(self):
    if self._buf_fh is None:
      self._ensure_dir()
      self._buf_fh = open(_BUFFER_FILE, "a", encoding="utf-8")
    return self._buf_fh

  def _close_buf(self):
    if self._buf_fh is not None:
      try:
        self._buf_fh.close()
      except Exception:
        pass
      self._buf_fh = None

  def log_event(self, event_type: str, module: str, data: str = "",
          level: str = "info"):
    line = json.dumps({
      "event_type": event_type, "module": module,
      "data": data, "level": level,
      "created_at": datetime.now().isoformat(),
    }, ensure_ascii=False)
    with self._lock:
      self._open_buf().write(line + "\n")
      self._buffer_count += 1
      now = time.time()
      if self._buffer_count >= _FLUSH_BATCH or now - self._last_flush >= _FLUSH_INTERVAL:
        self._flush()

  def _flush(self):
    """批量写入 SQLite。可在多线程下安全调用。"""
    # 先确保文件句柄关闭，避免并发读写
    self._close_buf()
    if not os.path.isfile(_BUFFER_FILE):
      self._buffer_count = 0
      self._last_flush = time.time()
      return
    try:
      with open(_BUFFER_FILE, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]
      if not lines:
        self._buffer_count = 0
        self._last_flush = time.time()
        return
      if self._db is None:
        self._db = _ensure_db()
      rows = []
      for line in lines:
        try:
          obj = json.loads(line)
          rows.append((
            obj["event_type"], obj["module"],
            obj.get("data", ""), obj.get("level", "info"),
            obj.get("created_at", datetime.now().isoformat()),
          ))
        except (json.JSONDecodeError, KeyError):
          continue
      if rows:
        self._db.executemany(
          "INSERT INTO logs (event_type, module, data, level, created_at) VALUES (?,?,?,?,?)",
          rows,
        )
        self._db.commit()
      # 清空 buffer
      open(_BUFFER_FILE, "w").close()
    except Exception as e:
      _log.warning("日志 flush 失败: %s", e)
    finally:
      self._buffer_count = 0
      self._last_flush = time.time()

  # ── 清理 ──

  def _cleanup(self):
    """双线清理：保留最近 N 天的记录 ∪ 保留本次启动以来的记录。

    删除既不满足"3 天内"也不满足"本次启动后"的记录。
    """
    if self._db is None:
      return
    try:
      from datetime import timedelta
      cutoff = (datetime.now() - timedelta(days=self._retention_days)).isoformat()
      deleted = self._db.execute(
        "DELETE FROM logs WHERE created_at < ? AND created_at < ?",
        (cutoff, self._launch_time),
      ).rowcount
      if deleted:
        self._db.commit()
        _log.debug("审计日志清理: 删除 %d 条过期记录", deleted)
    except Exception as e:
      _log.warning("审计日志清理失败: %s", e)

  # ── 查询 ──

  def query(self, event_type: str = "", module: str = "",
           since: str = "", limit: int = 20) -> list[dict]:
    """查询日志。参数均为可选，空字符串表示不筛选。"""
    if self._db is None:
      self._db = _ensure_db()
    where = []
    params = []
    if event_type:
      where.append("event_type=?")
      params.append(event_type)
    if module:
      where.append("module=?")
      params.append(module)
    if since:
      where.append("created_at>=?")
      params.append(since)
    sql = "SELECT event_type, module, data, level, created_at FROM logs"
    if where:
      sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(min(limit, _MAX_RESULTS))
    try:
      rows = self._db.execute(sql, params).fetchall()
      return [
        {"event_type": r[0], "module": r[1], "data": r[2],
         "level": r[3], "created_at": r[4]}
        for r in rows
      ]
    except Exception as e:
      _log.warning("日志查询失败: %s", e)
      return []

  def summary(self) -> str:
    """今日统计摘要"""
    if self._db is None:
      self._db = _ensure_db()
    today = datetime.now().strftime("%Y-%m-%d")
    try:
      rows = self._db.execute(
        "SELECT event_type, COUNT(*) FROM logs WHERE created_at LIKE ? GROUP BY event_type ORDER BY COUNT(*) DESC",
        (today + "%",),
      ).fetchall()
      if not rows:
        return f"今日 ({today}) 无日志记录"
      parts = [f"{r[0]}: {r[1]} 次" for r in rows]
      return f"今日 ({today}) 日志: {' · '.join(parts)}"
    except Exception as e:
      return f"查询失败: {e}"

  def tool_stats(self) -> str:
    """今日各工具调用次数"""
    if self._db is None:
      self._db = _ensure_db()
    today = datetime.now().strftime("%Y-%m-%d")
    try:
      rows = self._db.execute(
        "SELECT module, COUNT(*) FROM logs WHERE created_at LIKE ? AND event_type='tool_call' GROUP BY module ORDER BY COUNT(*) DESC",
        (today + "%",),
      ).fetchall()
      if not rows:
        return "今日无工具调用"
      parts = []
      for mod, cnt in rows:
        name = mod.replace("tools.", "", 1) if mod.startswith("tools.") else mod
        parts.append(f"{name}: {cnt} 次")
      return f"今日工具调用:\n" + "\n".join(f"  {p}" for p in parts)
    except Exception as e:
      return f"查询失败: {e}"


# ── 全局单例 ──

_ENGINE: Optional[AuditEngine] = None
_ENGINE_LOCK = threading.Lock()


def get_engine() -> AuditEngine:
  global _ENGINE
  with _ENGINE_LOCK:
    if _ENGINE is None:
      _ENGINE = AuditEngine()
      # 崩溃恢复 + 启动清理
      if os.path.isfile(_BUFFER_FILE):
        with open(_BUFFER_FILE, "r") as f:
          has_content = any(line.strip() for line in f)
        if has_content:
          _ENGINE._flush()
      _ENGINE._cleanup()
    return _ENGINE
