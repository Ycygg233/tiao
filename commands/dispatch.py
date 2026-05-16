from prompt_toolkit.completion import Completer, Completion
from enum import Enum

from session import get_available_models
from ._data import _COMMANDS, _CMD_DESC, _TOOLS, _TOOLS_DESC, _CMD_SUBCOMMANDS
from .session_cmds import (
  _cmd_new, _cmd_undo, _cmd_reload, _cmd_sessions, _cmd_copy,
  _cmd_switch, _cmd_save, _cmd_title, _cmd_workspace, _cmd_status,
  _cmd_reload_prompt,
)
from .config_cmds import (
  _cmd_limit, _cmd_ctx, _cmd_profile, _cmd_model,
  _cmd_rules, _cmd_verbose, _cmd_think, _cmd_reasoning, _cmd_su, _cmd_update, _cmd_quota,
  _cmd_config, _cmd_audit, _cmd_backup,
)
from .tool_cmds import _cmd_tools
from tools.tool_dispatch import handle_tool_call


class TiaoCompleter(Completer):
  """自定义补全：按 / 或 @ 前缀精确匹配（含子命令），带中文说明"""
  def get_completions(self, document, complete_event):
    raw = document.text_before_cursor.split('\n')[-1]
    text = raw.lstrip()
    if not text:
      return
    # start_position 基于最后一行长度
    start_pos = -len(raw)

    # ── /sessions 子命令（展开子项）─────────────────────────
    if text.startswith("/sessions"):
      cmd_text = text[:10]
      prefix = text[10:].strip()
      if "/sessions".startswith(cmd_text) or cmd_text == "/sessions":
        yield Completion("/sessions", start_position=start_pos, display_meta="列出所有会话")
      _subs = {
        "export <名称|编号>": "导出指定会话为 JSON",
        "export --all": "导出所有会话为 JSON",
        "rm <名称|编号>": "删除指定会话",
        "rm --all": "删除所有会话",
      }
      for sub, desc in _subs.items():
        if sub.startswith(prefix):
          yield Completion(
            f"/sessions {sub}",
            start_position=start_pos,
            display_meta=desc,
          )
      return

    # ── /audit 子命令（展开子项）───────────────────────────
    if text.startswith("/audit"):
      cmd_text = text[:6]
      prefix = text[6:].strip()
      if "/audit".startswith(cmd_text) or cmd_text == "/audit":
        yield Completion("/audit", start_position=start_pos, display_meta="今日统计摘要（含各工具明细）")
      _subs = {
        "summary": "今日统计摘要",
        "since 1h": "过去 1 小时",
        "since 1d": "过去 1 天",
        "tool_call": "查询工具调用记录",
      }
      for sub, desc in _subs.items():
        if sub.startswith(prefix):
          yield Completion(
            f"/audit {sub}",
            start_position=start_pos,
            display_meta=desc,
          )
      return

    # ── /backup 子命令 ────────────────────────────────────
    if text.startswith("/backup"):
      cmd_text = text[:8]
      prefix = text[8:].strip()
      if "/backup".startswith(cmd_text) or cmd_text == "/backup":
        yield Completion("/backup", start_position=start_pos, display_meta="备份引擎")
      # 二级：/backup version on|off
      if prefix.startswith("version "):
        for opt in ("on", "off"):
          if opt.startswith(prefix[8:]):
            yield Completion(
              f"/backup version {opt}",
              start_position=start_pos,
              display_meta="大版本变更时自动备份",
            )
        return
      _subs = {
        "now":   "立即备份项目",
        "version": "版本控制 on/off（大版本自动备份）",
        "list":  "列出所有备份文件",
        "cleanup": "清理旧备份 [保留份数]",
      }
      for sub, desc in _subs.items():
        if sub.startswith(prefix):
          yield Completion(
            f"/backup {sub}",
            start_position=start_pos,
            display_meta=desc,
          )
      return

    # ── /config 子命令 ────────────────────────────────────
    if text.startswith("/config"):
      cmd_text = text[:8]
      prefix = text[8:].strip()
      if "/config".startswith(cmd_text) or cmd_text == "/config":
        yield Completion("/config", start_position=start_pos, display_meta="配置管理")
      _subs = {
        "set": "设置配置 key=val [key2=val2 ...]",
        "get": "查看配置 /config get key",
        "list": "列出所有配置项",
      }
      for sub, desc in _subs.items():
        if sub.startswith(prefix):
          yield Completion(
            f"/config {sub}",
            start_position=start_pos,
            display_meta=desc,
          )
      return


    # ── /verbose 子命令 ───────────────────────────────────
    if text.startswith("/verbose"):
      cmd_text = text[:9]
      prefix = text[9:].strip()
      if "/verbose".startswith(cmd_text) or cmd_text == "/verbose":
        yield Completion("/verbose", start_position=start_pos, display_meta="切换日志级别")
      _subs = {
        "on":  "开启详细日志（DEBUG）",
        "off":  "关闭详细日志（INFO）",
        "debug": "DEBUG 级别",
        "info": "INFO 级别",
      }
      for sub, desc in _subs.items():
        if sub.startswith(prefix):
          yield Completion(
            f"/verbose {sub}",
            start_position=start_pos,
            display_meta=desc,
          )
      return

    # ── /think 子命令 ─────────────────────────────────────
    if text.startswith("/think"):
      cmd_text = text[:7]
      prefix = text[7:].strip()
      if "/think".startswith(cmd_text) or cmd_text == "/think":
        yield Completion("/think", start_position=start_pos, display_meta="切换思考模式")
      _subs = {
        "on":  "开启思考（effort=high）",
        "off":  "关闭思考",
        "high": "思考 effort=high",
        "max":  "思考 effort=max",
        "reset": "重置为 profile 默认",
      }
      for sub, desc in _subs.items():
        if sub.startswith(prefix):
          yield Completion(
            f"/think {sub}",
            start_position=start_pos,
            display_meta=desc,
          )
      return

    # ── /limit 子命令 ─────────────────────────────────────
    if text.startswith("/limit"):
      cmd_text = text[:7]
      prefix = text[7:].strip()
      if "/limit".startswith(cmd_text) or cmd_text == "/limit":
        yield Completion("/limit", start_position=start_pos, display_meta="上下文裁剪开关")
      _subs = {
        "on": "开启上下文裁剪",
        "off": "关闭上下文裁剪（发送全部历史）",
      }
      for sub, desc in _subs.items():
        if sub.startswith(prefix):
          yield Completion(
            f"/limit {sub}",
            start_position=start_pos,
            display_meta=desc,
          )
      return

    # ── /profile 子命令（动态从 CONFIG 读取）───────────────
    if text.startswith("/profile"):
      cmd_text = text[:9]
      prefix = text[9:].strip()
      if "/profile".startswith(cmd_text) or cmd_text == "/profile":
        yield Completion("/profile", start_position=start_pos, display_meta="切换对话场景")
      try:
        from config import CONFIG, valert
        profiles = CONFIG.get("profiles", {})
      except Exception:
        profiles = {}
      for name in profiles:
        if name.startswith(prefix):
          desc = profiles[name].get("description", "")
          yield Completion(
            f"/profile {name}",
            start_position=start_pos,
            display_meta=desc,
          )
      return

    # ── /workspace 子命令（提示路径）───────────────────────
    if text.startswith("/workspace"):
      cmd_text = text[:11]
      prefix = text[11:].strip()
      if "/workspace".startswith(cmd_text) or cmd_text == "/workspace":
        yield Completion("/workspace", start_position=start_pos, display_meta="查看/设置工作区")
      if not prefix:
        yield Completion(
          "/workspace /path/to/project",
          start_position=start_pos,
          display_meta="设置工作区目录",
        )
      return

    # ── /model 子命令（模型名）─────────────────────────────
    if text.startswith("/model"):
      cmd_text = text[:7]
      rest = text[7:].lstrip()
      if not rest:
        yield Completion("/model", start_position=start_pos, display_meta="查看/切换模型")
      for m in get_available_models():
        mid = m["id"]
        if mid.startswith(rest):
          yield Completion(
            f"/model {mid}",
            start_position=start_pos,
            display_meta=m.get("desc", ""),
          )
      return

    # ── /reasoning 子命令 ─────────────────────────────────
    if text.startswith("/reasoning"):
      cmd_text = text[:11]
      prefix = text[11:].strip()
      if "/reasoning".startswith(cmd_text) or cmd_text == "/reasoning":
        yield Completion("/reasoning", start_position=start_pos, display_meta="显示推理过程开关")
      _subs = {
        "on": "开启显示推理过程",
        "off": "关闭显示推理过程",
      }
      for sub, desc in _subs.items():
        if sub.startswith(prefix):
          yield Completion(
            f"/reasoning {sub}",
            start_position=start_pos,
            display_meta=desc,
          )
      return

    # ── /su 子命令 ────────────────────────────────────────
    if text.startswith("/su") and not text.startswith("/su+"):
      cmd_text = text[:4]
      prefix = text[4:].strip()
      if "/su".startswith(cmd_text) or cmd_text == "/su":
        yield Completion("/su", start_position=start_pos, display_meta="中级提权")
      _subs = {
        "yes": "持久化提权（永久生效）",
        "no": "撤销提权",
      }
      for sub, desc in _subs.items():
        if sub.startswith(prefix):
          yield Completion(
            f"/su {sub}",
            start_position=start_pos,
            display_meta=desc,
          )
      return

    # ── /su+ 子命令 ───────────────────────────────────────
    if text.startswith("/su+"):
      cmd_text = text[:5]
      prefix = text[5:].strip()
      if "/su+".startswith(cmd_text) or cmd_text == "/su+":
        yield Completion("/su+", start_position=start_pos, display_meta="完全放行")
      _subs = {
        "yes": "持久化提权（永久生效）",
        "no": "撤销提权",
      }
      for sub, desc in _subs.items():
        if sub.startswith(prefix):
          yield Completion(
            f"/su+ {sub}",
            start_position=start_pos,
            display_meta=desc,
          )
      return

    # ── /ctx 子命令 ───────────────────────────────────────
    if text.startswith("/ctx"):
      cmd_text = text[:5]
      prefix = text[5:].strip()
      if "/ctx".startswith(cmd_text) or cmd_text == "/ctx":
        yield Completion("/ctx", start_position=start_pos, display_meta="设置保底轮数")
      if not prefix:
        yield Completion(
          "/ctx <数字>",
          start_position=start_pos,
          display_meta="设置上下文裁剪保底轮数（当前: N 轮）",
        )
      return

    # ── /switch 子命令（模糊匹配会话）────────────────────
    if text.startswith("/switch") or (len(text) > 1 and "/switch".startswith(text.split()[0])):
      cmd_text = text[:8]
      prefix = text[8:].strip()
      need_cmd = "/switch".startswith(cmd_text) or cmd_text == "/switch"
      try:
        from session import get_session_entries
        all_entries = get_session_entries()
        if not prefix:
          show = all_entries[:5]
        else:
          show = []
          for e in all_entries:
            if prefix in e["name"] or prefix in (e.get("title", "") or ""):
              show.append(e)
              if len(show) >= 5:
                break
        for entry in show:
          if need_cmd or prefix:
            name = entry["name"]
            title = entry.get("title", "") or name
            meta = f"{title} ({entry.get('msg_count', 0)} 条)"
            yield Completion(
              f"/switch {name}",
              start_position=start_pos,
              display_meta=meta,
            )
      except Exception:
        pass
      if need_cmd:
        yield Completion("/switch", start_position=start_pos, display_meta="切换到指定会话")
      return

    # ── 通用 / 命令前缀匹配（唯一匹配时展开子命令）───────
    if text.startswith("/"):
      cmd_part = text.split()[0].strip()
      if cmd_part == "/":
        return
      matched = [cmd for cmd in _COMMANDS if cmd.startswith(cmd_part)]
      for cmd in matched:
        yield Completion(
          cmd,
          start_position=start_pos,
          display_meta=_CMD_DESC.get(cmd, ""),
        )
      # 唯一匹配时展开子命令
      if len(matched) == 1:
        cmd = matched[0]
        rest = text[len(cmd):].lstrip()
        subs = _CMD_SUBCOMMANDS.get(cmd)
        if subs is None:
          pass  # 无子命令，不展开
        elif subs:
          # 有预定义的子命令 → 直接展开
          for sub, desc in subs.items():
            if sub.startswith(rest):
              yield Completion(
                f"{cmd} {sub}",
                start_position=start_pos,
                display_meta=desc,
              )
        elif not rest:
          # 空 dict = 动态展开（/model /switch /profile）
          yield Completion(
            f"{cmd} ",
            start_position=start_pos,
            display_meta="按空格展开子项...",
          )
      return

    # ── @ 工具匹配 ────────────────────────────────────────
    if text.startswith("@"):
      for tool in _TOOLS:
        if tool.startswith(text):
          yield Completion(
            tool,
            start_position=start_pos,
            display_meta=_TOOLS_DESC.get(tool, ""),
          )
      return


class DispatchResult(Enum):
  HANDLED = "handled"
  BREAK = "break"
  FALLTHROUGH = "fallthrough"


def dispatch(text: str, ctx: dict) -> DispatchResult:
  """
  匹配 / 命令并执行。返回 DispatchResult。
  """
  if not text.startswith("/"):
    return DispatchResult.FALLTHROUGH

  if text in ("/exit", "/quit"):
    return DispatchResult.BREAK

  if text == "/clear":
    ctx["console"].clear()
    return DispatchResult.HANDLED

  _EXACT_CMDS = {
    "/new": _cmd_new,
    "/undo": _cmd_undo,
    "/reload": _cmd_reload,
    "/tools": _cmd_tools,
    "/help": _cmd_tools,
    "/copy": _cmd_copy,
    "/status": _cmd_status,
    "/update": _cmd_update,
    "/model": lambda ctx: _cmd_model("/model", ctx),
    "/config": lambda ctx: _cmd_config("/config", ctx),
    "/audit": lambda ctx: _cmd_audit("", ctx),
  "/quota": lambda ctx: _cmd_quota("", ctx),
    "/backup": lambda ctx: _cmd_backup("", ctx),
  }
  fn = _EXACT_CMDS.get(text)
  if fn:
    fn(ctx)
    return DispatchResult.HANDLED

  _PREFIX_CMDS = [
    ("/workspace ", _cmd_workspace),
    ("/workspace", _cmd_workspace),
  ("/verbose ", _cmd_verbose),
    ("/su+", lambda t, c: _cmd_su(t, c, "su+")),
    ("/su ", lambda t, c: _cmd_su(t, c, "su")),
    ("/su", lambda t, c: _cmd_su(t, c, "su")),
    ("/reload prompt", _cmd_reload_prompt),
    ("/think ", _cmd_think),
  ("/think", _cmd_think),
  ("/reasoning ", _cmd_reasoning),
  ("/reasoning", _cmd_reasoning),
    ("/limit ", _cmd_limit),
    ("/limit", _cmd_limit),
    ("/ctx ", _cmd_ctx),
    ("/ctx", _cmd_ctx),
    ("/profile ", _cmd_profile),
    ("/profile", _cmd_profile),
    ("/model ", _cmd_model),
    ("/switch ", _cmd_switch),
    ("/switch", _cmd_switch),
    ("/rules ", _cmd_rules),
    ("/rules", _cmd_rules),
    ("/save ", _cmd_save),
    ("/save", _cmd_save),
    ("/title ", _cmd_title),
    ("/title", _cmd_title),
    ("/sessions ", _cmd_sessions),
    ("/sessions", _cmd_sessions),
    ("/backup ", _cmd_backup),
    ("/backup", _cmd_backup),
    ("/audit ", _cmd_audit),
  ("/audit", _cmd_audit),
  ("/quota ", _cmd_quota),
  ("/quota", _cmd_quota),
  ]
  for prefix, handler in _PREFIX_CMDS:
    if text.startswith(prefix):
      handler(text, ctx)
      return DispatchResult.HANDLED

  return DispatchResult.FALLTHROUGH
