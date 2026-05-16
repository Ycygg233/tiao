import os
import json
import random
import re
import subprocess
import sys
import logging
from datetime import datetime
from typing import Optional

from prompt_toolkit import PromptSession

from config import CONFIG, valert
from security.checkpoint import undo_last
from styles import SUCCESS
from session import (
  SESSION_DIR, save_session, load_session, get_session_entries,
  generate_session_title,
)
from utils import fmt_size

_log = logging.getLogger("tiao")
from skills.prompts import load_skills, build_system_prompt


def _cmd_new(ctx) -> str:
  messages, system_prompt = ctx["messages"], ctx["system_prompt"]
  session_name = ctx.get("session_name", "")
  if len(messages) > 1:
    if not session_name:
      session_name = generate_session_title(messages) or ""
    if session_name:
      name = save_session(messages, CONFIG, session_name)
      if name:
        ctx["log"].debug("会话已保存: %s", name)
  ctx["session_name"] = ""
  ctx["_auto_titled"] = False
  _log.info("[SESSION] session= (新对话)")
  messages.clear()
  messages.append(system_prompt)
  ctx["console"].print("[dim]────新对话 ─────[/dim]")
  ctx["log"].debug("已开启新对话")
  return "handled"


def _cmd_undo(ctx) -> str:
  result = undo_last()
  c = ctx["console"]
  from tools.errors import is_error_result
  if is_error_result(result):
    c.print(f"[red]{result}[/red]")
  elif result.startswith("✓"):
    c.print(f"[{SUCCESS}]{result}[/]")
  else:
    c.print(f"[yellow]{result}[/yellow]")
  return "handled"


def _cmd_reload(ctx) -> str:
  """仅重载 Python 模块（开发调试用）。

  配置已即时生效，无需 reload。
  System prompt 重载请用 /reload prompt 系列命令。
  """
  c = ctx["console"]
  import importlib
  import pkgutil
  _reloaded = []
  _modules = []
  try:
    # 1. 无依赖层：config（跳过——配置已即时生效）
    _reloaded.append('config(跳过, 即时生效)')

    # 2. prompts
    import skills.prompts as _prompts_mod
    _modules.append(('prompts', _prompts_mod))
    importlib.reload(_prompts_mod)
    _reloaded.append('prompts')

    # 3. 基础工具层：utils (含子模块)
    import utils as _utils_mod
    _modules.append(('utils', _utils_mod))
    for _finder, _name, _ispkg in pkgutil.walk_packages(_utils_mod.__path__, prefix='utils.'):
      if _name in sys.modules:
        _modules.append((_name, sys.modules[_name]))
        importlib.reload(sys.modules[_name])
    importlib.reload(_utils_mod)
    _reloaded.append('utils')

    # 4. session（跳过——数据层，无状态变更需求）
    _reloaded.append('session(跳过)')

    # 5. 工具注册表（跳过——动态注册的工具不应被清空）
    _reloaded.append('tools.registry(跳过)')

    # 6. 工具层：tools (含子模块)
    import tools as _tools_mod
    _modules.append(('tools', _tools_mod))
    for _finder, _name, _ispkg in pkgutil.walk_packages(_tools_mod.__path__, prefix='tools.'):
      if _name in sys.modules:
        _modules.append((_name, sys.modules[_name]))
        importlib.reload(sys.modules[_name])
    importlib.reload(_tools_mod)
    _reloaded.append('tools')

    # 7. 命令层：commands —— 跳过 reload，避免 DispatchResult 枚举类被重新创建
    _reloaded.append('commands(跳过, 需重启生效)')

    # 8. 核心对话层：chat_core
    import chat.chat_core as _chat_mod
    _modules.append(('chat_core', _chat_mod))
    importlib.reload(_chat_mod)
    ctx["chat_stream"] = _chat_mod.chat_stream
    CONFIG["current_profile"] = ctx.get("current_profile", "default")
    _reloaded.append('chat_core')

    # 9. 调度层：tool_dispatch
    import tools.tool_dispatch as _disp_mod
    _modules.append(('tool_dispatch', _disp_mod))
    importlib.reload(_disp_mod)
    ctx["handle_tool_call"] = _disp_mod.handle_tool_call
    _reloaded.append('tool_dispatch')

    # 不再重建 client（配置已即时生效，client 仅作为 api_key 容器，已不依赖）
    # 不再重载 system prompt（请用 /reload prompt）

    c.print(
      f"[{SUCCESS}]✓ Python 模块已重载 ({CONFIG['model']} · {ctx['current_profile']})[/]"
    )
    c.print(f"[dim]重载: {', '.join(_reloaded)}[/dim]")
    c.print("[dim] 重载 system prompt 请用 /reload prompt core|skill|all[/dim]")
    ctx["log"].debug("模块重载: %s", _reloaded)
  except Exception as e:
    c.print(f"[red]✗ 重载失败: {e}[/red]")
    ctx["log"].warning("重载失败: %s", e)
  return "handled"


def _cmd_reload_prompt(text: str, ctx) -> str:
  """重载 system prompt，三级粒度。

  /reload prompt      → 提示用法
  /reload prompt core   → 仅重载 core 层（00_core_base）
  /reload prompt skill   → core + secondary（tool）
  /reload prompt all    → core + secondary + rules（全量）
  """
  c = ctx["console"]
  parts = text.split(maxsplit=2)
  level = parts[2].strip().lower() if len(parts) > 2 else ""

  if level not in ("core", "skill", "all"):
    c.print("[yellow]用法:[/yellow]")
    c.print(" /reload prompt core  重载核心层（00_core_base）")
    c.print(" /reload prompt skill 重载核心 + 次级（tool）")
    c.print(" /reload prompt all  全量重载（含项目规则）")
    return "handled"

  try:
    # 根据层级决定注入哪些作用域
    from skills.prompts import get_always_scopes, load_skills, build_system_prompt

    # 临时构造一个 config 来决定作用域
    if level == "core":
      # 只注入 core
      temp_config = {**CONFIG, "inject_secondary": False}
    elif level == "skill":
      # 注入 core + secondary
      temp_config = {**CONFIG, "inject_secondary": True}
    else: # all
      temp_config = {**CONFIG, "inject_secondary": True}

    skills_text = load_skills(ctx["log"], config=temp_config)
    rules_text = ctx.get("rules_text", "") if level == "all" else ""
    sp_content = build_system_prompt(CONFIG, ctx["current_profile"], skills_text, rules_text)
    ctx["system_prompt"] = {"role": "system", "content": sp_content}
    ctx["messages"][0] = ctx["system_prompt"]

    level_names = {"core": "核心层", "skill": "核心+次级", "all": "全量"}
    c.print(f"[{SUCCESS}]✓ system prompt 已重载（{level_names.get(level, level)}）[/]")
    ctx["log"].debug("system prompt 重载: level=%s", level)
  except Exception as e:
    c.print(f"[red]✗ 重载失败: {e}[/red]")
    ctx["log"].warning("system prompt 重载失败: %s", e)
  return "handled"


def _cmd_sessions(text: str = "", ctx = None) -> str:
  c = ctx["console"] if ctx else None
  parts = text.strip().split(maxsplit=2)
  # 跳过命令前缀 /sessions
  if parts and parts[0].startswith("/"):
    parts = parts[1:]
  sub = parts[0] if parts else ""

  # ── export 子命令 ──
  if sub == "export":
    target = parts[1] if len(parts) > 1 else ""
    if not target:
      if c: c.print("[yellow]⚠ 用法: /sessions export <会话名|编号|--all>[/yellow]")
      return "handled"
    if target == "--all":
      return _export_all_sessions(c)
    return _export_session(target, c)

  # ── rm 子命令 ──
  if sub in ("rm", "delete", "del"):
    target = parts[1] if len(parts) > 1 else ""
    if not target:
      if c: c.print("[yellow]⚠ 用法: /sessions rm <名称|编号|--all>[/yellow]")
      return "handled"
    if target == "--all":
      return _delete_all_sessions(c)
    return _delete_session(target, c)

  # ── 列表（默认） ──
  entries = get_session_entries()
  if not entries:
    if c: c.print("[dim]没有已保存的会话[/dim]")
    return "handled"
  if c: c.print("[dim]已保存的会话:[/dim]")
  for i, entry in enumerate(entries, 1):
    name = entry["name"]
    mt = entry.get("mtime", "")
    try:
      mt = datetime.fromisoformat(str(mt)).strftime("%m-%d %H:%M")
    except (ValueError, TypeError):
      try:
        mt = datetime.fromtimestamp(float(mt)).strftime("%m-%d %H:%M")
      except (ValueError, TypeError):
        mt = ""
    model_hint = f" [{entry['model']}]" if entry.get("model") else ""
    msg_hint = f" {entry.get('msg_count', 0)}条" if entry.get("msg_count") else ""
    if c: c.print(f" {i}. [bold]{name}[/bold]{model_hint}{msg_hint} {mt}")
  return "handled"


def _resolve_session(target: str) -> Optional[str]:
  """按编号或名称查找会话，返回会话名"""
  entries = get_session_entries()
  if not entries:
    return None
  if target.isdigit():
    idx = int(target) - 1
    if 0 <= idx < len(entries):
      return entries[idx]["name"]
  for entry in entries:
    if entry["name"] == target:
      return target
  for entry in entries:
    if target.lower() in entry["name"].lower():
      return entry["name"]
  return None


_EXPORT_DIR = "/storage/emulated/0/Documents/tiao-archives/sessions"


def _export_session(target: str, c = None) -> str:
  """导出单个会话为 JSON"""
  name = _resolve_session(target)
  if not name:
    if c: c.print(f"[yellow]⚠ 未找到会话: {target}[/yellow]")
    return "handled"

  data = load_session(name)
  if not data:
    if c: c.print(f"[red]✗ 加载失败: {name}[/red]")
    return "handled"

  os.makedirs(_EXPORT_DIR, exist_ok=True)
  safe_name = name.translate(str.maketrans({c: "_" for c in r'/\:*?"<>|'}))[:60]
  fpath = os.path.join(_EXPORT_DIR, f"{safe_name}.json")

  try:
    with open(fpath, "w", encoding="utf-8") as f:
      json.dump(data, f, ensure_ascii=False, indent=2)
    size = os.path.getsize(fpath)
    if c: c.print(f"[{SUCCESS}]✓ 已导出: {fpath} ({fmt_size(size)})[/]")
    _log.info("会话已导出: %s → %s", name, fpath)
  except Exception as e:
    if c: c.print(f"[red]✗ 导出失败: {e}[/red]")
  return "handled"


def _export_all_sessions(c = None) -> str:
  """导出所有会话"""
  entries = get_session_entries()
  if not entries:
    if c: c.print("[dim]没有已保存的会话[/dim]")
    return "handled"

  os.makedirs(_EXPORT_DIR, exist_ok=True)
  ok = fail = 0
  for entry in entries:
    name = entry["name"]
    data = load_session(name)
    if not data:
      fail += 1
      continue
    safe_name = name.translate(str.maketrans({c: "_" for c in r'/\:*?"<>|'}))[:60]
    fpath = os.path.join(_EXPORT_DIR, f"{safe_name}.json")
    try:
      with open(fpath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
      ok += 1
    except Exception:
      fail += 1

  if c: c.print(f"[{SUCCESS}]✓ 已导出 {ok} 个会话到 {_EXPORT_DIR}[/]")
  if fail: c.print(f"[yellow]⚠ {fail} 个导出失败[/yellow]")
  return "handled"


def _delete_session(target: str, c = None) -> str:
  """删除指定会话"""
  name = _resolve_session(target)
  if not name:
    if c: c.print(f"[yellow]⚠ 未找到会话: {target}[/yellow]")
    return "handled"
  from session import delete_session_file
  if delete_session_file(name):
    if c: c.print(f"[{SUCCESS}]✓ 已删除: {name}[/]")
    _log.info("会话已删除: %s", name)
  else:
    if c: c.print(f"[red]✗ 删除失败: {name}[/red]")
  return "handled"


def _delete_all_sessions(c = None) -> str:
  """删除所有会话"""
  from session import delete_session_file
  entries = get_session_entries()
  if not entries:
    if c: c.print("[dim]没有已保存的会话[/dim]")
    return "handled"
  ok = 0
  for entry in entries:
    if delete_session_file(entry["name"]):
      ok += 1
  if c: c.print(f"[{SUCCESS}]✓ 已删除 {ok}/{len(entries)} 个会话[/]")
  return "handled"


def _cmd_copy(ctx) -> str:
  c = ctx["console"]
  last_reply = ctx.get("last_reply_ref", [""])[0]
  if not last_reply:
    c.print("[yellow]⚠ 没有可复制的回复（还没有 AI 回复过）[/yellow]")
    return "handled"
  MAX_CLIPBOARD_CHARS = 500_000
  if len(last_reply) > MAX_CLIPBOARD_CHARS:
    c.print(f"[yellow]⚠ 内容过长 ({len(last_reply):,} 字符)，已截断至 {MAX_CLIPBOARD_CHARS:,} 字符[/yellow]")
    last_reply = last_reply[:MAX_CLIPBOARD_CHARS]
  try:
    subprocess.run(
      ["termux-clipboard-set"],
      input=last_reply, text=True, timeout=5, check=True,
    )
    c.print(f"[{SUCCESS}]✓ 已复制 ({len(last_reply)} 字符) 到剪贴板[/]")
  except FileNotFoundError:
    c.print("[red]✗ 未找到 termux-clipboard-set，请安装 termux-api[/red]")
  except Exception as e:
    c.print(f"[red]✗ 复制失败: {e}[/red]")
  return "handled"


def _cmd_switch(text: str, ctx) -> str:
  c = ctx["console"]
  parts = text.split(maxsplit=1)
  target = parts[1].strip() if len(parts) > 1 else ""
  if not target:
    c.print("[yellow]⚠ 用法: /switch <编号或会话名>[/yellow]")
    return "handled"
  entries = get_session_entries()
  if not entries:
    c.print("[yellow]⚠ 没有已保存的会话[/yellow]")
    return "handled"

  name = None
  if target.isdigit():
    idx = int(target) - 1
    if 0 <= idx < len(entries):
      name = entries[idx]["name"]
  else:
    for entry in entries:
      if entry["name"] == target:
        name = entry["name"]
        break
    if not name:
      for entry in entries:
        if target.lower() in entry["name"].lower():
          name = entry["name"]
          break
  if not name:
    c.print(f"[yellow]⚠ 未找到会话: {target}[/yellow]")
    return "handled"

  if len(ctx["messages"]) > 1:
    save_session(ctx["messages"], CONFIG, ctx.get("session_name", ""))
  data = load_session(name)
  if not data:
    c.print(f"[red]✗ 加载失败: {name}[/red]")
    return "handled"
  loaded = data["messages"]
  meta = data.get("meta", {})
  saved_model = meta.get("last_model")
  ctx["messages"].clear()
  ctx["messages"].extend(loaded)
  ctx["session_name"] = name
  _log.info("[SESSION] session=%s", name)
  count_info = f"({len(ctx['messages'])} 条消息)"
  if saved_model and saved_model != CONFIG["model"]:
    count_info += f" [dim]上次模型: {saved_model}，当前: {CONFIG['model']}[/dim]"
  c.print(f"[{SUCCESS}]✓ 已切换到: {ctx['session_name']}[/] {count_info}")
  return "handled"


# ========== 标题推荐辅助 ==========

_TITLE_META_PROMPT = """请根据整场对话拟订3个标题推荐。
要求：
- 每个标题不超过35字
- 直接列出 A/B/C 三个选项
- 不要多余的解释文字
- 格式示例：
A. 标题一
B. 标题二
C. 标题三"""

_TITLE_COLORS = ["bold color(80)", "bold color(78)", "bold color(172)"]

_COLD_START_TIPS = [
  "目前还没有聊天记录，有什么需要帮忙的吗？",
  "还没开始对话呢，先聊点什么吧～",
  "空空如也，等你来开场！",
  "没有对话内容，要不要先打个招呼？",
]

# 标题行正则：A. xxx / A、xxx / A：xxx / A: xxx
_TITLE_LINE_RE = re.compile(r'^([ABC])[.、：:]\s*(.+)$')


def _parse_titles(text: str) -> list[str]:
  """从助手回复中提取 A/B/C 标题。"""
  titles = []
  for line in text.split("\n"):
    line = line.strip()
    m = _TITLE_LINE_RE.match(line)
    if m:
      titles.append(m.group(2))
  return titles[:3]





def _show_title_selection(c, titles: list[str]) -> str | None:
  """显示标题选择界面，返回选中的标题或 None"""
  if not titles:
    return None

  from rich.panel import Panel

  lines = []
  for i, title in enumerate(titles):
    color = _TITLE_COLORS[i] if i < len(_TITLE_COLORS) else "white"
    letter = chr(65 + i)
    lines.append(f" [{color}]{letter}. {title}[/{color}]")
  lines.append("")
  lines.append(" [dim]输入 A/B/C 选择，R 重取[/dim]")

  panel = Panel(
    "\n".join(lines),
    title=" 标题推荐",
    border_style="blue",
    padding=(1, 2),
  )
  c.print(panel)

  try:
    session = PromptSession()
    while True:
      choice = session.prompt("> ").strip().upper()
      if choice in ("A", "B", "C"):
        return titles[ord(choice) - 65]
      if choice == "R":
        return "__RETRY__"
  except (KeyboardInterrupt, EOFError):
    return None


# ========== 命令实现 ==========


def _cmd_save(text: str, ctx) -> str:
  """保存当前会话。
  已有文字标题 → 直接保存
  兜底数字标题 → 弹出标题推荐
  """
  c = ctx["console"]

  messages = ctx["messages"]
  if len(messages) <= 1:
    c.print("[yellow]⚠ 对话太短，无法保存[/yellow]")
    return "handled"

  # 判断当前标题类型
  current_name = ctx.get("session_name", "")
  is_fallback = (not current_name
          or (len(current_name) > 8 and current_name[0].isdigit()))

  if not is_fallback:
    # 已有文字标题，直接保存
    name = save_session(messages, CONFIG, current_name)
    if name:
      c.print(f"[{SUCCESS}]✓ 会话已保存: {current_name}[/]")
    else:
      c.print("[red]✗ 保存失败[/red]")
    return "handled"

  # 兜底标题 → 直调 API 生成标题推荐 → 选标题 → 保存
  selected = None
  while True:
    try:
      with c.status("[dim]生成标题中…[/dim]", spinner="dots"):
        import requests as _req
        resp = _req.post(
        f"{CONFIG['api_base']}/chat/completions",
        headers={
          "Authorization": f"Bearer {CONFIG.get('api_key', '')}",
          "Content-Type": "application/json",
        },
        json={
          "model": CONFIG["model"],
          "messages": messages + [{"role": "user", "content": _TITLE_META_PROMPT}],
          "temperature": 0.3,
          "max_tokens": 150,
          "stream": False,
        },
        timeout=30,
      )
      resp.raise_for_status()
      reply = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
      ctx["log"].error("标题生成异常: %s", e)
      c.print(f"[yellow]⚠ 标题生成失败: {e}[/yellow]")
      c.print("[dim]将使用默认标题保存[/dim]")
      break

    titles = _parse_titles(reply)
    if not titles:
      c.print("[yellow]⚠ 无法解析标题，将使用默认名称保存[/yellow]")
      break

    selected = _show_title_selection(c, titles)
    if selected == "__RETRY__":
      continue
    if selected:
      old_name = ctx.get("session_name", "")
      if old_name and old_name != selected:
        from session import rename_session_file
        rename_session_file(old_name, selected)
      ctx["session_name"] = selected
    break

  name = save_session(messages, CONFIG, selected or "")
  if name:
    msg = selected or name
    c.print(f"[{SUCCESS}]✓ 会话已保存: {msg}[/]")
  else:
    c.print("[red]✗ 保存失败[/red]")
  return "handled"


def _cmd_title(text: str, ctx) -> str:
  """设置或生成会话标题。
  /title 名称  → 手动设置标题
  /title    → 无对话：冷启动提示
           有对话：AI 推荐 3 个标题供选择（直调 API，复用上下文前缀）
  """
  c = ctx["console"]
  parts = text.split(maxsplit=1)
  arg = parts[1].strip() if len(parts) > 1 else ""

  # ── 带参数：直接设置 ──
  if arg:
    old_name = ctx.get("session_name", "")
    if old_name and old_name != arg:
      from session import rename_session_file
      rename_session_file(old_name, arg)
    ctx["session_name"] = arg
    ctx["_auto_titled"] = True
    c.print(f"[{SUCCESS}]✓ 会话标题已设为: {arg}[/]")
    return "handled"

  messages = ctx["messages"]
  non_system = [m for m in messages if m.get("role") != "system"]

  # ── 冷启动 ──
  if len(non_system) < 2:
    c.print(f"[dim]{random.choice(_COLD_START_TIPS)}[/dim]")
    return "handled"

  # ── 有对话：直调 API 生成标题推荐（复用上下文前缀，不污染消息历史） ──
  while True:
    try:
      with c.status("[dim]生成标题中…[/dim]", spinner="dots"):
        import requests as _req
        resp = _req.post(
        f"{CONFIG['api_base']}/chat/completions",
        headers={
          "Authorization": f"Bearer {CONFIG.get('api_key', '')}",
          "Content-Type": "application/json",
        },
        json={
          "model": CONFIG["model"],
          "messages": messages + [{"role": "user", "content": _TITLE_META_PROMPT}],
          "temperature": 0.3,
          "max_tokens": 150,
          "stream": False,
        },
        timeout=30,
      )
      resp.raise_for_status()
      reply = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
      ctx["log"].error("标题生成异常: %s", e)
      c.print(f"[red]✗ 标题生成失败: {e}[/red]")
      return "handled"

    titles = _parse_titles(reply)
    if not titles:
      c.print(f"[yellow]⚠ 无法从回复中解析标题格式，可手动用 /title <名称> 设置[/yellow]")
      return "handled"

    selected = _show_title_selection(c, titles)
    if selected == "__RETRY__":
      continue
    if selected:
      old_name = ctx.get("session_name", "")
      if old_name and old_name != selected:
        from session import rename_session_file
        rename_session_file(old_name, selected)
      ctx["session_name"] = selected
      ctx["_auto_titled"] = True
      c.print(f"[{SUCCESS}]✓ 会话标题已设为: {selected}[/]")
    else:
      c.print("[yellow]⚠ 已取消[/yellow]")
    return "handled"


def _cmd_workspace(text: str, ctx) -> str:
  c = ctx["console"]
  parts = text.split(maxsplit=1)
  path = parts[1].strip() if len(parts) > 1 else ""

  import chat.chat_core as chat_core
  from security.permissions import get_workspace as _sandbox_ws

  if not path:
    ws = _sandbox_ws()
    if ws:
      c.print(f"[dim]当前工作区: {ws}[/dim]")
      c.print("[dim]工作区内文件读取大小警告阈值从 50%/68% 放宽至 80%/95%[/dim]")
    else:
      c.print("[dim]未设置工作区[/dim]")
      c.print("[dim]用法: /workspace /path/to/project[/dim]")
    return "handled"

  if not os.path.isdir(path):
    c.print(f"[yellow]⚠ 不是有效目录: {path}[/yellow]")
    return "handled"

  chat_core.set_workspace(path)
  ctx["workspace"] = path

  c.print(f"[{SUCCESS}]✓ 工作区已设为: {path}[/]")
  c.print("[dim]工作区内文件读取大小警告阈值从 50%/68% 放宽至 80%/95%[/dim]")
  c.print("[dim]AI 工具调用会自动感知工作区上下文[/dim]")
  ctx["log"].debug("工作区设置: %s", path)
  return "handled"


def _cmd_status(ctx) -> str:
  c = ctx["console"]
  from utils.metrics import get_process_stats, get_tool_stats
  import threading
  proc = get_process_stats()
  tools_stats = get_tool_stats()
  c.print(f"[dim]━━ 运行状态 ━━[/dim]")
  c.print(f" 内存: {proc['rss_mb']}MB | 线程: {proc['threads']} | 活跃: {threading.active_count()}")
  c.print(f" 工具: {tools_stats['total_tools']} (内置: {tools_stats['global_tools']}, 会话: {tools_stats['session_tools']})")
  ws = ctx.get("workspace", "")
  if ws:
    c.print(f" 工作区: {ws}")
  max_tok = CONFIG.get('max_history_tokens', 1000000)
  min_rnd = CONFIG.get('min_history_rounds', 6)
  c.print(f" 模型: {CONFIG['model']} | 场景: {ctx.get('current_profile', 'default')} | 预算: {max_tok:,} tokens · 保底 {min_rnd} 轮")
  from security.permissions import get_sudo_level
  sudo_lvl = get_sudo_level()
  if sudo_lvl:
    persist = "永久" if os.path.isfile(os.path.join(os.path.expanduser("~"), ".tiao_sudo.json")) else "临时"
    c.print(f" 提权: {sudo_lvl} [{persist}] | 日志审计: 开启")
  else:
    c.print(f" 提权: 沙箱模式 | 日志审计: 开启")
  from chat.chat_display import _fmt_tokens
  import chat._shared as _sh
  c.print(f" 累计: ↑{_fmt_tokens(_sh._total_input_tokens)} / ↓{_fmt_tokens(_sh._total_output_tokens)}")
  return "handled"
