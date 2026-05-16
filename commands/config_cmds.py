import os

from config import CONFIG, valert, CONFIG_META, validate_and_coerce, persist_config
from skills.prompts import load_skills, build_system_prompt
from rich.markup import escape
from security import _confirm_or_skip
from styles import SUCCESS, WARN, ERROR, MUTED, LABEL


def _cmd_limit(text: str, ctx) -> str:
  c = ctx["console"]
  parts = text.split(maxsplit=1)
  arg = parts[1].strip().lower() if len(parts) > 1 else ""
  if arg == "on":
    CONFIG["context_limiter_enabled"] = True
    c.print(f"[color(78)]✓ 上下文裁剪已开启[/]")
    persist_config()
  elif arg == "off":
    CONFIG["context_limiter_enabled"] = False
    c.print("[color(78)]✓ 上下文裁剪已关闭，将发送全部历史[/]")
    persist_config()
  else:
    status = "开启" if CONFIG.get("context_limiter_enabled", True) else "关闭"
    budget_tokens = CONFIG.get("max_history_tokens", 1000000)
    c.print(f"[dim]上下文裁剪: {status}[/dim]")
    c.print(f"[dim]预算: {budget_tokens:,} tokens[/dim]")
    c.print(f"[dim]用法: /limit on | /limit off[/dim]")
  return "handled"


def _cmd_ctx(text: str, ctx) -> str:
  c = ctx["console"]
  parts = text.split(maxsplit=1)
  arg = parts[1].strip() if len(parts) > 1 else ""
  if not arg:
    rounds = CONFIG.get("min_history_rounds", 6)
    c.print(f"[dim]当前保底轮数: {rounds} 轮[/dim]")
    c.print("[dim]用法: /ctx <数字> — 设置上下文裁剪保底轮数[/dim]")
    return "handled"
  try:
    n = int(arg)
    if n < 1:
      c.print("[color(172)]⚠ 轮数至少为 1[/]")
      return "handled"
    if n > 100:
      c.print("[color(172)]⚠ 轮数最大为 100[/]")
      return "handled"
  except ValueError:
    c.print(f"[color(172)]⚠ 无效数字: {arg}[/]")
    return "handled"
  CONFIG["min_history_rounds"] = n
  persist_config()
  c.print(f"[color(78)]✓ 保底轮数设为: {n} 轮[/]")
  ctx["log"].debug("min_history_rounds 设为: %d", n)
  return "handled"


def _cmd_profile(text: str, ctx) -> str:
  c = ctx["console"]
  parts = text.split(maxsplit=1)
  name = parts[1].strip() if len(parts) > 1 else ""
  profiles = CONFIG.get("profiles", {})
  if not name:
    c.print("[dim]当前场景预设:[/dim]")
    for pname, pcfg in profiles.items():
      mark = "→" if pname == ctx["current_profile"] else " "
      c.print(f" {mark} [bold]{pname}[/bold] — {pcfg.get('description', '')}")
    c.print("[dim]用法: /profile [name][/dim]")
    return "handled"
  if name not in profiles:
    c.print(f"[color(172)]⚠ 未知场景: {name}[/]")
    c.print(f"[dim]可用: {', '.join(profiles.keys())}[/dim]")
    return "handled"
  ctx["current_profile"] = name
  CONFIG["current_profile"] = name
  pcfg = profiles[name]
  for k, v in pcfg.items():
    if k == "description":
      continue
    if v is not None:
      if k == "thinking":
        v = "on" if v else "off"
      CONFIG[k] = v
  persist_config()
  skills_text = load_skills(ctx["log"], config=CONFIG)
  rules_text = ctx.get("rules_text", "")
  sp_content = build_system_prompt(CONFIG, name, skills_text, rules_text)
  ctx["system_prompt"] = {"role": "system", "content": sp_content}
  if ctx["messages"] and ctx["messages"][0].get("role") == "system":
    ctx["messages"][0] = ctx["system_prompt"]
  else:
    sys_idx = next((i for i, m in enumerate(ctx["messages"]) if m.get("role") == "system"), -1)
    if sys_idx >= 0:
      ctx["messages"][sys_idx] = ctx["system_prompt"]
    else:
      ctx["messages"].insert(0, ctx["system_prompt"])
  thinking = pcfg.get("thinking", False)
  effort = pcfg.get("reasoning_effort", "high") if thinking else "off"
  c.print(f"[color(78)]✓ 场景切换为: {name}[/] (temp={CONFIG['temperature']}, thinking=[color(245)]{effort}[/])")
  ctx["log"].debug("场景切换: %s, temp=%s, thinking=%s", name, CONFIG["temperature"], effort)
  return "handled"


def _cmd_model(text: str, ctx) -> str:
  c = ctx["console"]
  parts = text.split(maxsplit=1)
  name = parts[1].strip() if len(parts) > 1 else ""
  if not name:
    c.print(f"[dim]当前模型: {CONFIG['model']}[/dim]")
    from session import get_available_models
    models = get_available_models()
    for m in models:
      mark = "→" if m["id"] == CONFIG["model"] else " "
      desc = m.get("desc", "")
      c.print(f" {mark} [bold]{m['id']}[/bold]" + (f" — {desc}" if desc else ""))
    c.print("[dim]用法: /model <模型名>[/dim]")
    return "handled"
  try:
    name = validate_and_coerce("model", name)
  except ValueError as e:
    c.print(f"[color(167)]✗ {e}[/]")
    return "handled"
  old_model = CONFIG["model"]
  CONFIG["model"] = name
  persist_config()
  c.print(f"[color(78)]✓ 模型切换: {old_model} → {name}[/]")
  ctx["log"].debug("模型切换: %s → %s", old_model, name)
  return "handled"


def _cmd_rules(text: str, ctx) -> str:
  c = ctx["console"]
  parts = text.split(maxsplit=1)
  rpath = parts[1].strip() if len(parts) > 1 else ""
  if not rpath:
    c.print("[color(172)]⚠ 用法: /rules /path/to/project_rules.md[/]")
    return "handled"
  if not os.path.isfile(rpath):
    c.print(f"[color(167)]✗ 文件不存在: {escape(rpath)}[/]")
    return "handled"
  from security import sandbox_check
  ok, msg = sandbox_check("read", rpath)
  if not ok:
    c.print(f"[color(167)]✗ 路径被沙箱拒绝: {escape(msg)}[/]")
    return "handled"
  try:
    with open(rpath, "r", encoding="utf-8") as f:
      rules_content = f.read().strip()
    if not rules_content:
      c.print("[color(172)]⚠ 规则文件为空[/]")
      return "handled"
    ctx["rules_text"] = rules_content
    skills_text = load_skills(ctx["log"], config=CONFIG)
    sp_content = build_system_prompt(CONFIG, CONFIG.get("current_profile", "default"), skills_text, rules_content)
    ctx["system_prompt"] = {"role": "system", "content": sp_content}
    ctx["messages"][0] = ctx["system_prompt"]
    c.print(f"[color(78)]✓ 已注入项目规则 ({len(rules_content)} 字符): {rpath}[/]")
    ctx["log"].debug("注入规则: %s (%d chars)", rpath, len(rules_content))
  except Exception as e:
    c.print(f"[color(167)]✗ 加载规则失败: {e}[/]")
  return "handled"


def _cmd_verbose(text: str, ctx) -> str:
  c = ctx["console"]
  parts = text.split(maxsplit=1)
  arg = parts[1].strip().lower() if len(parts) > 1 else ""
  import logging
  root = logging.getLogger()
  levels = {"debug": logging.DEBUG, "info": logging.INFO, "on": logging.DEBUG, "off": logging.INFO}
  if arg in levels:
    root.setLevel(levels[arg])
    verbose = arg in ("on", "debug")
    CONFIG["verbose"] = verbose
    label = "DEBUG" if levels[arg] == logging.DEBUG else "INFO"
    c.print(f"[color(78)]✓ 日志级别: {label} | 报错详细: {'开启' if verbose else '关闭'}[/]")
  else:
    current = root.level
    label = logging.getLevelName(current)
    verbose = CONFIG.get("verbose", False)
    c.print(f"[dim]当前日志级别: {label} | 报错详细: {'开启' if verbose else '关闭'}[/dim]")
    c.print("[dim]用法: /verbose on|off|debug|info[/dim]")
  return "handled"




def _cmd_update(ctx) -> str:
  c = ctx["console"]
  import zipfile
  import shutil
  from datetime import datetime as _dt

  update_zip = "/sdcard/Download/tiao_update.zip"
  if not os.path.isfile(update_zip):
    c.print("[color(172)]⚠ 未找到更新包[/]")
    c.print(f"[dim]请将 tiao_update.zip 放入 /sdcard/Download/[/dim]")
    return "handled"

  backup_dir = "/sdcard/Documents/tiao-archive"
  os.makedirs(backup_dir, exist_ok=True)

  if CONFIG.get("backup_version_on_update", False):
    try:
      from security.backup import backup_version
      ts = _dt.now().strftime("%Y%m%d_%H%M%S")
      backup_version(ts)
      c.print("[color(78)] 版本快照已保存到 _BACKUPS_/[/]")
    except Exception as e:
      c.print(f"[color(172)]⚠ 版本快照失败: {e}[/]")

  ts = _dt.now().strftime("%Y%m%d_%H%M%S")
  project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
  backup_path = os.path.join(backup_dir, f"tiao_backup_{ts}")
  try:
    shutil.make_archive(backup_path, 'zip', project_dir)
    c.print(f"[color(78)] 已备份: {backup_path}.zip[/]")
  except Exception as e:
    c.print(f"[color(167)]✗ 备份失败: {e}[/]")
    return "handled"

  if not _confirm_or_skip("覆盖更新项目文件"):
    c.print("[dim]已取消[/dim]")
    return "handled"

  _MAX_EXTRACT_BYTES = 100 * 1024 * 1024
  _MAX_COMPRESSION_RATIO = 100
  try:
    with zipfile.ZipFile(update_zip, 'r') as z:
      real_project_dir = os.path.realpath(project_dir)
      total_size = 0
      for member in z.namelist():
        member_path = os.path.join(real_project_dir, member)
        real_member_path = os.path.realpath(member_path)
        if not real_member_path.startswith(real_project_dir + os.sep):
          c.print(f"[color(167)]✗ 更新包包含非法路径: {member}[/]")
          return "handled"
        info = z.getinfo(member)
        if info.file_size > 0 and info.compress_size > 0:
          ratio = info.file_size / info.compress_size
          if ratio > _MAX_COMPRESSION_RATIO:
            c.print(f"[color(167)]✗ 压缩比异常 ({ratio:.0f}x): {member}[/]")
            return "handled"
        total_size += info.file_size
      if total_size > _MAX_EXTRACT_BYTES:
        c.print(f"[color(167)]✗ 更新包过大 ({total_size / 1024 / 1024:.0f}MB)，超过 {_MAX_EXTRACT_BYTES / 1024 / 1024:.0f}MB 限制[/]")
        return "handled"
      z.extractall(real_project_dir)
    c.print("[color(78)]✓ 更新完成[/]")
    c.print("[dim]请执行 /reload 或重启 CLI 生效[/dim]")
  except Exception as e:
    c.print(f"[color(167)]✗ 解压失败: {e}[/]")
    c.print(f"[dim]备份文件: {backup_path}.zip[/dim]")

  return "handled"


def _cmd_think(text: str, ctx) -> str:
  c = ctx["console"]
  from chat.chat_core import set_thinking, reset_thinking

  parts = text.split(maxsplit=1)
  if len(parts) == 1:
    c.print(f"[dim]{set_thinking()}[/dim]")
    return "handled"

  arg = parts[1].strip().lower()
  if arg == "reset":
    reset_thinking()
    persist_config()
    from chat.chat_core import _get_thinking_status
    c.print(f"[dim]{_get_thinking_status()}[/dim]")
    return "handled"

  result = set_thinking(arg)
  CONFIG["thinking"] = arg
  persist_config()
  c.print(f"[dim]{result}[/dim]")
  return "handled"


def _cmd_reasoning(text: str, ctx) -> str:
  c = ctx["console"]
  parts = text.split(maxsplit=1)
  arg = parts[1].strip().lower() if len(parts) > 1 else ""
  if arg in ("on", "off"):
    CONFIG["show_reasoning"] = (arg == "on")
    persist_config()
    c.print(f"[color(78)]✓ 显示推理: {'开启' if arg == 'on' else '关闭'}[/]")
  else:
    status = "开启" if CONFIG.get("show_reasoning", False) else "关闭"
    c.print(f"[dim]显示推理: {status}[/dim]")
    c.print("[dim]用法: /reasoning on|off[/dim]")
  return "handled"


_SU_DESC = {
  "su": ("中级提权", "解锁 __exec__（安全只读命令）+ 沙箱内 import/json/open + 网络 + 15s 超时"),
  "su+": ("完全放行", "无 AST 拦截、完整 builtins、subprocess 任意命令、任意路径读写、30s 超时"),
}


def _clear_tool_cache():
  """清除 AI 工具缓存，下次对话重新获取（提权后刷新工具列表）"""
  try:
    import chat.chat_core as _chat
    _chat.chat_stream._tool_cache = None
  except Exception:
    pass


def _cmd_su(text: str, ctx, level: str) -> str:
  c = ctx["console"]
  from security import set_sudo_level, get_sudo_level, save_sudo_persist, clear_sudo_persist
  parts = text.split(maxsplit=1)
  arg = parts[1].strip().lower() if len(parts) > 1 else ""

  title, desc = _SU_DESC[level]

  if arg in ("0", "default", "no", "off"):
    current = get_sudo_level()
    set_sudo_level("")
    clear_sudo_persist()
    _clear_tool_cache()
    c.print(f"[color(172)]- 已撤销所有提权[/]")
    c.print(f"[dim]当前提权: 无（沙箱模式）[/dim]")
    return "handled"

  if arg in ("yes", "永久"):
    set_sudo_level(level)
    save_sudo_persist(level)
    _clear_tool_cache()
    c.print(f"[color(78)]+ 已永久启用 {title}[/]")
    c.print(f"[dim]{desc}[/dim]")
    return "handled"

  set_sudo_level(level)
  _clear_tool_cache()
  c.print(f"[color(78)]+ 已启用 {title}（仅本次会话）[/]")
  c.print(f"[dim]{desc}[/dim]")
  c.print(f"[dim]使用 [color(245)]/{level}[/] yes 持久化 | [color(245)]/{level}[/] no 撤销[/dim]")
  return "handled"


# ═══════════════════════════════════════════════════════════════
# /config 统一配置命令
# ═══════════════════════════════════════════════════════════════

def _cmd_config(text: str, ctx) -> str:
  """/config set key=val [key2=val2 ...] | get key | list"""
  c = ctx["console"]
  parts = text.split(maxsplit=2)
  sub = parts[1].strip().lower() if len(parts) > 1 else ""

  if sub == "set":
    if len(parts) < 3:
      c.print("[color(172)]用法: /config set key=val [key2=val2 ...][/]")
      return "handled"
    args = parts[2].split()
    for pair in args:
      if "=" not in pair:
        c.print(f"[color(172)]⚠ 格式错误: {pair}，需 key=value[/]")
        continue
      key, raw = pair.split("=", 1)
      try:
        val = validate_and_coerce(key, raw)
      except ValueError as e:
        c.print(f"[color(167)]✗ {key}: {e}[/]")
        continue
      CONFIG[key] = val
      label = CONFIG_META.get(key, {}).get("label", key)
      c.print(f"[color(78)]✓ {label} = {val}[/]")
    persist_config()
    c.print("[dim]已自动保存到配置文件，所有变更即时生效[/dim]")

  elif sub == "get":
    if len(parts) < 3:
      c.print("[color(172)]用法: /config get key[/]")
      return "handled"
    key = parts[2].strip()
    val = CONFIG.get(key, "")
    label = CONFIG_META.get(key, {}).get("label", key)
    c.print(f" {label} ({key}) = {val}")

  elif sub == "list":
    c.print("[bold]配置项一览:[/bold]")
    for key, meta in CONFIG_META.items():
      if meta.get("readonly"):
        continue
      val = CONFIG.get(key, "")
      display_val = str(val) if val is not None else "null"
      label = meta.get("label", key)
      c.print(f" {key:30s} = {display_val:20s} # {label}")

  else:
    c.print("[color(172)]用法:[/]")
    c.print(" /config set key=val [key2=val2 ...] 设置配置")
    c.print(" /config get key            查看配置")
    c.print(" /config list             列出所有配置")


def _cmd_backup(text: str = "", ctx = None) -> str:
  """备份命令: /backup now|version on|off|list|cleanup"""
  from security.backup import get_backup_engine, backup_now, backup_alert

  parts = text.strip().split()
  # 跳过命令前缀 /backup
  if parts and parts[0].startswith("/"):
    parts = parts[1:]
  sub = parts[0] if parts else "now"

  if ctx:
    c = ctx.get("console")

  if sub == "now":
    backup_now()
    if ctx:
      c.print("[color(78)]✓ 项目已备份到 _BACKUPS_/tiao_new.tar.gz[/]")

  elif sub == "version":
    arg = parts[1] if len(parts) > 1 else ""
    if arg == "on":
      CONFIG["backup_version_on_update"] = True
      persist_config()
      if ctx:
        c.print("[color(78)]✓ 大版本变更时自动备份: 开启[/]")
    elif arg == "off":
      CONFIG["backup_version_on_update"] = False
      persist_config()
      if ctx:
        c.print("[dim]大版本变更时自动备份: 关闭[/dim]")
    else:
      status = CONFIG.get("backup_version_on_update", False)
      if ctx:
        c.print(f"大版本自动备份: {' 开启' if status else ' 关闭'}")

  elif sub == "list":
    engine = get_backup_engine()
    snaps = engine.list_snapshots()
    if ctx:
      if not snaps:
        c.print("[dim]没有备份文件[/dim]")
      else:
        c.print(f"[bold]备份列表 ({len(snaps)}):[/bold]")
        for s in snaps[:10]:
          c.print(f" {s['name']:45s} {s['size']:>8s} {s['time']}")

  elif sub == "cleanup":
    keep = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    if ctx and keep == 0:
      if not _confirm_or_skip("确认删除所有备份?"):
        return "handled"
    get_backup_engine().cleanup(keep=keep)
    if ctx:
      c.print(f"[color(78)]✓ 备份已清理 (保留最近 {keep} 个)[/]")

  elif sub == "auto":
    arg = parts[1] if len(parts) > 1 else ""
    if arg == "on":
      CONFIG["backup_auto_cleanup"] = True
      persist_config()
      if ctx: c.print(f"[color(78)]✓ 自动清理已开启 (保留 {CONFIG['backup_auto_cleanup_days']} 天)[/]")
    elif arg == "off":
      CONFIG["backup_auto_cleanup"] = False
      persist_config()
      if ctx: c.print("[color(78)] 自动清理已关闭[/]")
    elif arg.isdigit():
      days = max(1, min(365, int(arg)))
      CONFIG["backup_auto_cleanup"] = True
      CONFIG["backup_auto_cleanup_days"] = days
      persist_config()
      if ctx: c.print(f"[color(78)]✓ 自动清理已开启，保留 {days} 天内的备份[/]")
    else:
      status = CONFIG.get("backup_auto_cleanup", False)
      days = CONFIG.get("backup_auto_cleanup_days", 7)
      if ctx:
        c.print(f"自动清理: {' 开启' if status else ' 关闭'} | 保留天数: {days}")
        c.print("[dim]/backup auto on|off|天数[/dim]")

  else:
    if ctx:
      c.print("[dim]用法: /backup now|version on|off|list|cleanup [N]|auto [on|off|天数][/dim]")

  return "handled"


def _cmd_quota(text: str = "", ctx = None) -> str:
  """配额命令: /quota [N] | off"""
  from tools.quota import set_quota, get_quota
  c = ctx.get("console") if ctx else None
  parts = text.strip().split()
  if parts and parts[0].startswith("/"):
    parts = parts[1:]

  if not parts:
    limit, used = get_quota()
    if c:
      status = "无限制" if limit == 0 else f"{used}/{limit}"
      c.print(f"[dim]工具调用配额: {status}[/dim]")
      c.print("[dim]用法: /quota <N> 设置额度 | /quota off 关闭限制[/dim]")

  elif parts[0] in ("off", "0"):
    set_quota(0)
    if c:
      c.print("[color(78)]✓ 配额已关闭，工具调用无限制[/]")

  else:
    try:
      n = int(parts[0])
      if n < 0:
        raise ValueError
      set_quota(n)
      if c:
        c.print(f"[color(78)]✓ 配额已设为 {n} 次[/]")
    except (ValueError, IndexError):
      if c:
        c.print("[color(172)]⚠ 用法: /quota <N> | /quota off[/]")

  return "handled"


def _cmd_audit(text: str = "", ctx = None) -> str:
  """审计命令: /audit [type] | since <时间> | summary"""
  from datetime import datetime
  from security.audit import get_engine

  engine = get_engine()
  parts = text.strip().split()
  if parts and parts[0].startswith("/"):
    parts = parts[1:]
  c = ctx.get("console") if ctx else None

  if not parts or parts[0] == "summary":
    summary = engine.summary()
    tools = engine.tool_stats()
    if c:
      c.print(f"[dim]{summary}[/dim]")
      if "无工具调用" not in tools:
        c.print(f"[dim]{tools}[/dim]")
    else:
      return summary + "\n" + tools

  elif parts[0] == "since":
    since = parts[1] if len(parts) > 1 else "1h"
    # 简单的相对时间解析
    import re as _re
    m = _re.match(r"(\d+)([hmd])", since)
    if m:
      n, unit = int(m.group(1)), m.group(2)
      from datetime import timedelta
      delta = {"h": timedelta(hours=n), "m": timedelta(minutes=n),
            "d": timedelta(days=n)}.get(unit, timedelta(hours=1))
      since_iso = (datetime.now() - delta).isoformat()
    else:
      since_iso = since
    rows = engine.query(since=since_iso, limit=30)
    if c:
      if not rows:
        c.print(f"[dim]过去 {since} 无日志[/dim]")
      else:
        c.print(f"[bold]过去 {since} 的日志 ({len(rows)} 条)[/bold]")
        for r in rows[:15]:
          c.print(f" [{r['level'][0].upper()}] {r['created_at'][:19]} "
              f"{r['event_type']} {r['module']}")
          if len(rows) > 15:
            c.print(f"[dim]... 还有 {len(rows) - 15} 条[/dim]")
    else:
      return f"日志: {len(rows)} 条"

  else:
    # 按 event_type 查询
    rows = engine.query(event_type=parts[0], limit=20)
    if c:
      if not rows:
        c.print(f"[dim]无 {parts[0]} 事件[/dim]")
      else:
        c.print(f"[bold]{parts[0]} 事件 ({len(rows)} 条)[/bold]")
        for r in rows[:10]:
          c.print(f" {r['created_at'][:19]} {r['module']} [{r['level']}]")
    else:
      return f"{parts[0]}: {len(rows)} 条"

  return "handled"

