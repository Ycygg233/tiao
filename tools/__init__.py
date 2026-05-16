# tools/__init__.py - 工具包入口：注册所有内置工具并导出公共 API
from .registry import (
  register, register_schema,
  get_tool, get_tool_entry, get_tool_schema,
  execute, list_tools, list_tool_schemas,
  tool_needs_confirm, get_openai_tools,
  _update_ai_safe_tools, _AI_SAFE_TOOLS,
  set_current_session, register_session_tool,
  remove_session_tool, clear_session_tools,
)
from security.sandbox import (
  sandbox_check,
  run_python as _run_python,
  ALLOWED_PATHS,
)
from security.dialog import (
  _confirm_or_skip, _set_confirm_callback, set_auto_confirm,
)
from security.checkpoint import (
  undo_last,
)
from .file_ops import (
  read_file, scan_dir, path_info, create_dir, write_file,
  find, replace, delete, rename, grep_symbol, paste,
  _write_file_parser, _replace_parser, _find_parser, _grep_symbol_parser,
)
from .schema import (
  ToolSchema, ToolPermissions, ParamDef,
)
from .executors import (
  BaseExecutor, NativeExecutor, SandboxExecutor,
  DryRunExecutor, ExecutionContext, create_executor,
)
from .errors import (
  ToolError, PermissionDeniedError, ValidationError,
  ExecutionError, TimeoutError, SandboxError, NotFoundError,
  toolerror_to_result, is_error_result,
)
from utils import fmt_size

# ========== 注册所有内置工具 (向后兼容) ==========

def _register_builtin(name, fn, desc, params, **kwargs):
  try:
    register(name, fn, desc, params, **kwargs)
  except Exception as e:
    import logging
    logging.getLogger("tiao").error(
      "内置工具 %s 注册失败: %s (请检查 registry.py)", name, e, exc_info=True
    )

_register_builtin("read_file", read_file, "读取文件内容", {"path": "文件路径", "offset": "起始行号(1开始,默认全读)", "limit": "最大返回行数(默认全读)", "tail": "与limit配合，从末尾向前读(默认false)", "lines": "指定非连续行号，逗号分隔(如'3,7,15')，优先于offset/limit/tail"}, safe_for_ai=True)
_register_builtin("scan_dir",  scan_dir,  "扫描目录结构（元数据，不展开内容）", {"path": "目录路径", "max_depth": "扫描深度(默认2)", "json_output": "是否输出JSON格式(默认false)"}, safe_for_ai=True)
_register_builtin("path_info", path_info, "获取路径详细信息",        {"path": "文件或目录路径"}, safe_for_ai=True)
_register_builtin("create_dir", create_dir, "创建目录（含父目录）",      {"path": "目录路径"})
_register_builtin("write_file", write_file, "创建/覆盖写入文件",       {"path": "文件路径", "content": "写入内容"}, safe_for_ai=True, needs_confirm=True, parser=_write_file_parser)
_register_builtin("find",    find,    "按文件名或内容搜索文件",     {"path": "搜索目录", "pattern": "匹配模式", "search_content": "是否搜索内容(默认False)", "max_depth": "搜索深度(默认3)", "max_results": "最大返回结果数(默认30)", "use_regex": "是否正则匹配(默认False)", "file_pattern": "按文件名过滤(如 *.py)", "ignore_case": "忽略大小写(默认False)", "context": "上下文行数(默认0)"}, safe_for_ai=True, parser=_find_parser)
_register_builtin("replace",  replace,  "局部替换文件内容（old→new）",   {"path": "文件路径", "old": "被替换的原文", "new": "替换后的新文本"}, safe_for_ai=True, needs_confirm=True, parser=_replace_parser)
_register_builtin("delete",   delete,   "删除文件或目录（含非空目录）",  {"path": "目标路径"}, needs_confirm=True)
_register_builtin("rename",   rename,   "移动/重命名文件或目录",       {"path": "源路径", "new_path": "目标路径"}, needs_confirm=True)
_register_builtin("run_python", _run_python, "在受限沙箱中执行 Python 代码（su 300s/su+ 无限制）", {"code": "Python 代码字符串"}, safe_for_ai=True)
_register_builtin("grep_symbol", grep_symbol, "用 AST 查找 Python 文件中的符号定义（class/function/var）", {"path": "文件路径", "symbol_type": "符号类型过滤(可选)", "symbol_name": "符号名片段(可选)"}, parser=_grep_symbol_parser)
_register_builtin("paste",   paste,   "读取剪贴板内容",      {})

# @search 网页搜索（秘塔/Tavily/自定义）
from .search_web import search_web as _search_web_fn
_register_builtin("search", _search_web_fn,
  "搜索网页（支持 metaso/tavily 等多平台）",
  {
    "q": "搜索关键词（必填，tavily fetch_urls 模式可选）",
    "scope": "metaso 专用: webpage | news | weixin，默认 webpage",
    "size": "返回结果数 1-20，默认 5",
    "include_summary": "metaso 专用: 是否包含完整句子摘要，默认 false",
    "include_raw": "metaso 专用: 是否包含原始内容，默认 false",
    "concise": "精简输出（默认 true，每个结果 2 行）",
    "max_chars": "输出字符上限，默认 2000",
    "provider": "metaso(默认) | tavily | jina | bocha",
    "depth": "tavily 专用: basic | advanced，默认 basic",
    "fetch_urls": "tavily/jina 专用: 抓取模式，传入逗号分隔的 URL",
    "freshness": "bocha 专用: 时间过滤 oneDay|oneWeek|oneMonth|oneYear",
  },
  safe_for_ai=True)

# @local_search 本地搜索（免费，多源聚合+缓存）
from .local_search import local_search as _local_search_fn
_register_builtin("local_search", _local_search_fn,
  "本地搜索（免费，多源聚合+缓存），支持 cache/web/fetch/auto 四种模式",
  {
    "q": "搜索关键词（必填，fetch 模式可选）",
    "scope": "auto(默认，仅缓存，未命中给提示) | all(缓存+联网) | cache(仅缓存) | web(仅联网) | fetch(抓URL)",
    "max_results": "最大结果数 1-10，默认 5",
    "fetch_url": "当 scope=fetch 时指定要抓取的 URL",
    "refresh": "是否强制刷新缓存（默认 false，24h 内读缓存）",
  },
  safe_for_ai=True)



_update_ai_safe_tools()
