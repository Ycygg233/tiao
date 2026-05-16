"""工具和命令帮助（/tools）
/tool 管理命令已于 v2.0.0beta 移除
"""

from ._data import _CMD_DESC, _CMD_USAGE


def _cmd_tools(ctx) -> str:
  c = ctx["console"]
  from tools import list_tools
  c.print("[dim]━━ 工具 ━━[/dim]")
  for name, info in sorted(list_tools().items()):
    c.print(f" [bold]@{name}[/bold] — {info.get('desc', '')}")
  c.print("[dim]简写: @/路径 读取文件/列目录 | @/路径 提问 附带提问[/dim]")
  c.print("[dim]━━ 命令 ━━[/dim]")
  for cmd, desc in _CMD_DESC.items():
    style = "bold color(245)" if cmd in ("/su", "/su+") else "bold"
    c.print(f" [{style}]{cmd}[/] — {desc}")
    usage = _CMD_USAGE.get(cmd)
    if usage:
      for line in usage:
        c.print(f"   [dim]{line}[/dim]")
  return "handled"
