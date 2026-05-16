# session.py - 会话持久化（SQLite） + 模型缓存
import os
import json
import time
import sqlite3
import threading
import atexit
import logging
from datetime import datetime
from typing import Optional, Dict

from utils import fmt_size
from config import CONFIG, valert, DATA_DIR

_log = logging.getLogger("tiao")

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_DIR = os.path.join(DATA_DIR, "sessions")
DB_PATH = os.path.join(SESSION_DIR, "tiao.db")
LAST_REPLY_FILE = os.path.join(SESSION_DIR, "last.md")
MODELS_CACHE_FILE = os.path.join(SESSION_DIR, "models_cache.json")

# ========== SQLite 连接管理 ==========

_db = None
_db_lock = threading.Lock()


def _get_db():
  global _db
  if _db is None:
    os.makedirs(SESSION_DIR, exist_ok=True)
    try:
      _db = sqlite3.connect(DB_PATH, check_same_thread=False)
      _db.execute("PRAGMA journal_mode=WAL")
      _db.execute("PRAGMA foreign_keys=ON")
    except sqlite3.DatabaseError:
      # 数据库损坏 → 备份后重建
      _log.warning("数据库损坏，正在重建: %s", DB_PATH)
      try:
        import shutil
        backup = DB_PATH + ".corrupted." + datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(DB_PATH, backup)
        _log.info("已备份损坏的数据库至: %s", backup)
      except Exception:
        pass
      try:
        os.remove(DB_PATH)
      except OSError:
        pass
      if os.path.isfile(DB_PATH + "-wal"):
        try: os.remove(DB_PATH + "-wal")
        except OSError: pass
      if os.path.isfile(DB_PATH + "-shm"):
        try: os.remove(DB_PATH + "-shm")
        except OSError: pass
      _db = sqlite3.connect(DB_PATH, check_same_thread=False)
      _db.execute("PRAGMA journal_mode=WAL")
      _db.execute("PRAGMA foreign_keys=ON")
  return _db


def _execute(sql, params=None):
  """线程安全的数据库执行，自动获取/释放锁"""
  with _db_lock:
    return _get_db().execute(sql, params or ())


def _transaction():
  """事务上下文管理器，自动 commit / rollback"""
  class _Tx:
    def __init__(self):
      self.db = None
    def __enter__(self):
      _db_lock.acquire()
      self.db = _get_db()
      return self.db
    def __exit__(self, exc_type, exc_val, exc_tb):
      try:
        if exc_type:
          self.db.rollback()
        else:
          self.db.commit()
      finally:
        _db_lock.release()
  return _Tx()


def _init_schema():
  with _transaction() as db:
    db.executescript("""
    CREATE TABLE IF NOT EXISTS sessions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL UNIQUE,
      title TEXT DEFAULT '',
      model TEXT DEFAULT '',
      msg_count INTEGER DEFAULT 0,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id INTEGER NOT NULL,
      seq INTEGER NOT NULL,
      role TEXT NOT NULL,
      content TEXT DEFAULT '',
      reasoning TEXT DEFAULT '',
      tool_calls TEXT DEFAULT '',
      tool_call_id TEXT DEFAULT '',
      FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
      UNIQUE(session_id, seq)
    );
    CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_id);
  """)


_init_schema()


def _close_db():
  """程序退出时关闭 SQLite 连接，确保 WAL checkpoint"""
  global _db
  if _db is not None:
    try:
      _db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
      _db.close()
    except Exception:
      pass
    _db = None


atexit.register(_close_db)


# ========== 旧 JSON → SQLite 迁移 ==========

def _migrate_json_to_db(db, json_path: str, name: str):
  """将单个 JSON 会话文件迁移到 SQLite。返回是否成功。"""
  try:
    with open(json_path, "r", encoding="utf-8") as f:
      data = json.load(f)
  except Exception:
    return False

  if isinstance(data, list):
    messages = data
    meta = {}
  else:
    messages = data.get("messages", [])
    meta = data.get("meta", {})

  if not messages:
    return False

  title = meta.get("title", "")
  model = meta.get("last_model", "")
  created = meta.get("created", datetime.now().isoformat())

  try:
    db.execute(
      "INSERT INTO sessions (name, title, model, msg_count, created_at, updated_at) VALUES (?,?,?,?,?,?)",
      (name, title, model, len(messages), created, datetime.now().isoformat()),
    )
    sid = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    for i, m in enumerate(messages):
      db.execute(
        "INSERT INTO messages (session_id, seq, role, content, reasoning, tool_calls, tool_call_id) VALUES (?,?,?,?,?,?,?)",
        (
          sid, i,
          m.get("role", ""),
          m.get("content", ""),
          m.get("reasoning_content", ""),
          json.dumps(m.get("tool_calls", []), ensure_ascii=False) if m.get("tool_calls") else "",
          m.get("tool_call_id", ""),
        ),
      )
    _log.info("迁移旧会话: %s (%d 条)", name, len(messages))
    return True
  except Exception as e:
    _log.warning("迁移旧会话失败 %s: %s", name, e)
    return False


def _auto_migrate():
  """启动时扫描 sessions/ 目录，自动迁移旧的 JSON 文件。"""
  if not os.path.isdir(SESSION_DIR):
    return
  with _transaction() as db:
    _skip = {"session_meta_cache.json", "models_cache.json", "tiao.db", "tiao.db-wal", "tiao.db-shm"}
    for fname in sorted(os.listdir(SESSION_DIR)):
      if fname in _skip:
        continue
      if not fname.endswith(".json") or fname.endswith(".meta.json"):
        continue
      json_path = os.path.join(SESSION_DIR, fname)
      if not os.path.isfile(json_path):
        continue
      name = fname.replace(".json", "")
      success = _migrate_json_to_db(db, json_path, name)
      if success:
        try:
          os.rename(json_path, json_path + ".migrated")
        except OSError:
          pass


_auto_migrate()


# ========== 保存 / 加载 ==========

_MIN_FREE_BYTES = 50 * 1024 * 1024


def _has_disk_space(path: str) -> bool:
  try:
    import shutil
    usage = shutil.disk_usage(path)
    return usage.free >= _MIN_FREE_BYTES
  except Exception:
    return True


def save_session(messages: list, config: dict, session_name: str = ""):
  """保存消息历史到 SQLite。增量写入新消息，已存在的消息自动跳过。"""
  if len(messages) <= 1:
    return None
  try:
    if not _has_disk_space(SESSION_DIR):
      _log.warning("磁盘空间不足（<%dMB），跳过保存", _MIN_FREE_BYTES // (1024 * 1024))
      return None

    _INVALID_FILENAME_CHARS = str.maketrans({c: "_" for c in r'/\:*?"<>|'})
    if session_name:
      name = session_name.strip().translate(_INVALID_FILENAME_CHARS)[:60]
    else:
      name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")

    model = config.get("model", "")
    now = datetime.now().isoformat()

    with _transaction() as db:
      # 查找或创建会话
      row = db.execute("SELECT id, msg_count FROM sessions WHERE name=?", (name,)).fetchone()
      if row:
        sid, existing_count = row
        db.execute("UPDATE sessions SET model=?, updated_at=? WHERE id=?", (model, now, sid))
      else:
        db.execute(
          "INSERT INTO sessions (name, title, model, msg_count, created_at, updated_at) VALUES (?,?,?,?,?,?)",
          (name, "", model, 0, now, now),
        )
        sid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        existing_count = 0

      # 增量写入：只写新消息（seq >= existing_count）
      new_count = 0
      for i, m in enumerate(messages):
        seq = i
        if seq < existing_count:
          continue
        db.execute(
          "INSERT OR IGNORE INTO messages (session_id, seq, role, content, reasoning, tool_calls, tool_call_id) VALUES (?,?,?,?,?,?,?)",
          (
            sid, seq,
            m.get("role", ""),
            m.get("content", ""),
            m.get("reasoning_content", ""),
            json.dumps(m.get("tool_calls", []), ensure_ascii=False) if m.get("tool_calls") else "",
            m.get("tool_call_id", ""),
          ),
        )
        new_count += 1

      db.execute("UPDATE sessions SET msg_count=?, updated_at=? WHERE id=?",
            (len(messages), now, sid))

    # _transaction() 已自动 commit
    _log.debug("会话已保存: %s (%d 新增, %d 总计)", name, new_count, len(messages))
    return name
  except Exception:
    _log.warning("保存会话失败", exc_info=True)
    return None


def load_session(name: str) -> Optional[Dict]:
  """从 SQLite 加载会话，返回 {messages: [...], meta: {...}}"""
  with _db_lock:
    db = _get_db()
    row = db.execute(
      "SELECT id, title, model, msg_count, created_at FROM sessions WHERE name=?",
      (name,),
    ).fetchone()
    if not row:
      return None

    sid, title, model, msg_count, created_at = row
    rows = db.execute(
      "SELECT role, content, reasoning, tool_calls, tool_call_id FROM messages WHERE session_id=? ORDER BY seq",
      (sid,),
    ).fetchall()

  messages = []
  for role, content, reasoning, tool_calls, tool_call_id in rows:
    msg = {"role": role, "content": content}
    if reasoning:
      msg["reasoning_content"] = reasoning
    if tool_calls:
      try:
        msg["tool_calls"] = json.loads(tool_calls)
      except json.JSONDecodeError:
        msg["tool_calls"] = []
    if tool_call_id:
      msg["tool_call_id"] = tool_call_id
    messages.append(msg)

  return {
    "messages": messages,
    "meta": {
      "title": title,
      "last_model": model,
      "created": created_at,
    },
  }


# ========== 标题生成（DeepSeek 直达） ==========

_TITLE_PROMPT = "用简短的一句话概括这段对话的主题，不超过15个字。只输出标题，不要多余内容。"


def _extract_title_text(content) -> str:
  if isinstance(content, list):
    parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
    return " ".join(parts)
  return str(content) if content else ""


def generate_session_title(messages: list, client=None, timeout=None) -> str:
  """用 DeepSeek 生成会话标题，不污染主对话上下文。client 参数保留兼容旧调用。"""
  non_system = [m for m in messages if m.get("role") != "system"]
  if len(non_system) < 2:
    return ""

  user_msgs = [_extract_title_text(m.get("content", "")) for m in non_system if m.get("role") == "user"]
  user_msgs = [u for u in user_msgs if u.strip()]
  if not user_msgs:
    roles = [m.get("role") for m in non_system]
    _log.warning("标题生成失败: 无有效user消息. roles=%s, len(non_system)=%d, len(messages)=%d",
           roles, len(non_system), len(messages))
    return ""

  first = user_msgs[0][:200]
  recent = [u[:200] for u in user_msgs[-2:] if u != user_msgs[0]]
  sample = [{"role": "user", "content": first}]
  for r in recent:
    sample.append({"role": "user", "content": r})
  if len(sample) < 1:
    return ""

  try:
    import requests
    resp = requests.post(
      f"{CONFIG['api_base']}/chat/completions",
      headers={
        "Authorization": f"Bearer {CONFIG.get('api_key', '')}",
        "Content-Type": "application/json",
      },
      json={
        "model": CONFIG["model"],
        "messages": [
          {"role": "system", "content": _TITLE_PROMPT},
          *sample,
        ],
        "temperature": 0.3,
        "max_tokens": 30,
      },
      timeout=timeout or 30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()
  except Exception as e:
    _log.warning("标题生成失败: %s", e)
    return ""


# ========== 查询 / 管理 ==========


def get_session_entries(offset: int = 0, limit: int = 15) -> list[dict]:
  """获取会话条目（按更新时间倒序，支持分页）"""
  rows = _execute(
    "SELECT id, name, title, model, msg_count, updated_at FROM sessions ORDER BY updated_at DESC LIMIT ? OFFSET ?",
    (limit, offset),
  ).fetchall()
  entries = []
  for sid, name, title, model, count, updated in rows:
    entries.append({
      "id": sid,
      "name": name,
      "title": title,
      "model": model,
      "msg_count": count,
      "mtime": updated,
      "size": 0,
    })
  return entries


def delete_session_file(name: str) -> bool:
  """删除会话及其所有消息"""
  try:
    with _transaction() as db:
      db.execute("DELETE FROM sessions WHERE name=?", (name,))
    from tools.registry import clear_session_tools
    clear_session_tools(name)
    return True
  except Exception:
    _log.warning("删除会话失败: %s", name, exc_info=True)
    return False


def delete_session_by_id(sid: int) -> bool:
  """按 id 删除会话"""
  name = get_session_name_by_id(sid)
  if not name:
    return False
  return delete_session_file(name)


def get_session_name_by_id(sid: int) -> str | None:
  """根据 id 获取会话名"""
  row = _execute("SELECT name FROM sessions WHERE id=?", (sid,)).fetchone()
  return row[0] if row else None


def rename_session_file(old_name: str, new_name: str) -> bool:
  """重命名会话"""
  try:
    with _transaction() as db:
      db.execute("UPDATE sessions SET name=? WHERE name=?", (new_name, old_name))
      changes = db.total_changes
    return changes > 0
  except Exception:
    _log.warning("重命名会话失败: %s → %s", old_name, new_name, exc_info=True)
    return False


def set_session_title(name: str, title: str):
  """设置会话标题"""
  with _transaction() as db:
    db.execute("UPDATE sessions SET title=? WHERE name=?", (title, name))


# ========== 启动提示 ==========


def show_recent_sessions(console):
  """启动时显示最近 3 次会话"""
  entries = get_session_entries()[:3]
  if entries:
    lines = []
    for e in entries:
      if e.get("model"):
        lines.append(f"{e['name']} [{e['model']}]")
      else:
        lines.append(e['name'])
    console.print(f"[dim]近期会话: {' | '.join(lines)} — 可用 /switch 恢复[/dim]")


# ========== 模型缓存（保持 JSON）==========

_MODEL_FALLBACK = [
  {"id": "deepseek-v4-flash", "desc": "快速模型，默认"},
  {"id": "deepseek-v4-pro", "desc": "强推理模型"},
  {"id": "deepseek-chat", "desc": "DeepSeek-V3"},
  {"id": "deepseek-reasoner", "desc": "DeepSeek-R1 推理模型"},
]


def try_fetch_models(client=None, log=None):
  """启动时检查/更新模型缓存（每 24h 拉一次）。client 参数保留兼容旧调用。"""
  os.makedirs(SESSION_DIR, exist_ok=True)
  if os.path.isfile(MODELS_CACHE_FILE):
    try:
      with open(MODELS_CACHE_FILE, "r") as f:
        cached = json.load(f)
      age = time.time() - cached.get("updated", 0)
      if age < 86400:
        return
    except Exception:
      pass
  try:
    import requests
    resp = requests.get(
      f"{CONFIG['api_base']}/models",
      headers={"Authorization": f"Bearer {CONFIG.get('api_key', '')}"},
      timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    models = []
    for m in data.get("data", []):
      models.append({"id": m["id"], "desc": m.get("owned_by", "")})
    with open(MODELS_CACHE_FILE, "w") as f:
      json.dump({"updated": time.time(), "models": models}, f)
    if log:
      log.debug("模型列表已缓存: %d 个", len(models))
  except Exception as e:
    if log:
      log.debug("拉取模型列表失败: %s", e)


def get_available_models() -> list:
  """获取可用模型列表（缓存优先，无缓存用硬编码兜底）"""
  if os.path.isfile(MODELS_CACHE_FILE):
    try:
      with open(MODELS_CACHE_FILE, "r") as f:
        cached = json.load(f)
      return cached.get("models", _MODEL_FALLBACK)
    except Exception:
      pass
  return _MODEL_FALLBACK
