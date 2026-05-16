from tools import list_tools

_COMMANDS = [
  "/exit", "/quit", "/new", "/clear", "/config",
  "/undo", "/reload", "/limit", "/ctx", "/profile", "/model",
  "/sessions", "/switch", "/tools", "/help", "/rules",
  "/save", "/title", "/copy", "/verbose", "/workspace",
  "/status", "/audit", "/backup", "/update", "/quota",
  "/su", "/su+", "/think", "/reasoning",
]

_CMD_DESC = {
  "/exit": "退出", "/quit": "退出",
  "/new": "保存当前对话，开启新对话",
  "/clear": "清屏",
    "/config": "统一配置管理 /config set key=val | get key | list",
  "/undo": "撤销上次写入/替换操作",
  "/reload": "重载配置/命令/核心对话模块（不退出）",
  "/limit": "上下文裁剪开关 /limit on|off",
  "/ctx": "设置上下文裁剪保底轮数 /ctx <数字>",
  "/profile": "切换对话场景 /profile default|code|debug|review",
  "/model": "查看/切换模型 /model <模型名>",
  "/sessions": "会话管理（导出/删除）",
  "/switch": "切换到指定会话 /switch <编号|名称>",
  "/tools": "显示工具和命令帮助",
  "/help": "显示工具和命令帮助（/tools 的别名）",
  "/rules": "注入项目规则到 system prompt /rules <路径>",
  "/save": "保存当前会话到文件（自动生成标题）",
  "/title": "设置或 AI 自动生成会话标题",
  "/copy": "复制最后一条 AI 回复到剪贴板",
  "/verbose": "切换详细日志 /verbose [on|off|debug|info]",
  "/workspace": "设置/查看会话工作区 /workspace [路径]",
  "/status": "查看当前状态（内存/工具数/线程数）",
  "/quota": "工具调用配额 /quota <N> | /quota off",
  "/audit": "日志查询",
  "/backup": "备份引擎 /backup now|version on|off|list|cleanup",
  "/update": "增量更新：备份并覆盖项目文件",
  "/think": "思考模式 /think [on|off|high|max] 查看或切换思考状态",
"/reasoning": "显示推理过程 /reasoning [on|off] 控制是否显示模型的思考过程",
"/su": "中级提权，解锁 __exec__ + import/json + open + 网络",
  "/su+": "完全放行，无 AST 拦截、无路径限制、任意命令",
}

_TOOLS = [f"@{n}" for n in list_tools().keys()] + ["@summarize"]
_TOOLS_DESC = {f"@{n}": info["desc"] for n, info in list_tools().items()}
_TOOLS_DESC["@summarize"] = "扫描目录并生成项目摘要"

# 命令详细用法（/tools 列表时换行显示）
_CMD_USAGE = {
  "/audit": [
    "  /audit              今日统计摘要（含各工具明细）",
    "  /audit since <时间>  按时间查询（如 1h / 1d）",
    "  /audit <事件类型>    按类型查询（如 tool_call）",
  ],
  "/sessions": [
    "  /sessions              列出所有会话",
    "  /sessions export <名称|编号|--all>  导出为 JSON",
    "  /sessions rm <名称|编号|--all>     删除会话",
  ],
}

# 子命令映射（通用补全展开用）
_CMD_SUBCOMMANDS = {
  "/sessions": {"export": "导出会话", "rm": "删除会话"},
  "/audit": {"summary": "今日统计", "since": "按时间查询"},
  "/backup": {"now": "立即备份", "version": "版本控制", "list": "列出备份", "cleanup": "清理旧备份", "auto": "自动清理"},
  "/config": {"set": "设置配置", "get": "查看配置", "list": "列出配置"},
  "/verbose": {"on": "开启详细日志", "off": "关闭详细日志", "debug": "DEBUG 级别", "info": "INFO 级别"},
  "/think": {"on": "开启思考", "off": "关闭思考", "high": "effort=high", "max": "effort=max", "reset": "重置为 profile 默认"},
  "/limit": {"on": "开启裁剪", "off": "关闭裁剪"},
  "/reasoning": {"on": "开启显示", "off": "关闭显示"},
  "/su": {"yes": "持久化提权", "no": "撤销提权"},
  "/su+": {"yes": "持久化提权", "no": "撤销提权"},
  "/ctx": {"<数字>": "设置保底轮数"},
  "/workspace": {"<路径>": "设置工作区目录"},
  # 动态展开（按空格后独立 block 接管）
  "/model": {},
  "/switch": {},
  "/profile": {},
}
