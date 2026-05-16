# config.py - 配置字典
# 默认配置在下方的 CONFIG 中。
# 如需覆盖配置，在 ~/.tiao_config.json 中放置 JSON 对象（键名与 CONFIG 一致）。

import os
import json
import copy as _copy

# ── 数据根目录（环境变量 TIAO_DATA_DIR 可覆盖）─────────
_DATA_DIR_DEFAULT = os.path.join(os.path.expanduser("~"), ".tiao_data")
DATA_DIR = os.environ.get("TIAO_DATA_DIR", _DATA_DIR_DEFAULT)


# ── 报错打印辅助（受 verbose 控制）────────────────────
def valert(console, style: str, symbol: str, message: str):
    """按 verbose 模式打印报错：off 仅符号，on 符号+消息"""
    text = symbol if not CONFIG.get("verbose") else f"{symbol} {message}"
    console.print(f"[{style}]{text}[/]")

CONFIG = {
  # ---- 显示 ----
  "display_name": None,     # None = 自动从模型名推断（如 deepseek→DeepSeek）
  "display_color": "bold color(67)",
  "verbose": False,          # 详细模式：on 显示完整报错，off 仅打符号
"show_reasoning": False,   # 显示推理过程：on 以银灰显示 reasoning_content，off 隐藏
"align_guide": True,       # 对齐指导：开启时注入对齐工具使用指南到 system prompt


  # ---- API ----
  "model": "deepseek-v4-flash",     # 默认快模型，需重推理时 /model 切换
  "api_base": "https://api.deepseek.com/v1",
  "temperature": 0.7,
  "top_p": 0.9,             # 核采样，与 temperature 协同
  "api_timeout": 60,           # 请求超时秒数（普通模式）
  "api_timeout_thinking": 180,      # 思考模式超时（v4-pro 等推理模型需更长时间）
  "api_max_retries": 1,         # 失败重试次数

  # ---- 上下文管理 ----
  "show_token_usage": True,        # 每句回复后显示 token 统计（入/出/合）
  "context_limiter_enabled": True,    # 独立总开关，/limit on|off 控制
  "max_history_tokens": 1000000,     # 1M tokens
  "min_history_rounds": 6,        # 保底保留轮数，/ctx <N> 修改
  "char_to_token_ratio": 3.0,

  # ---- 注入控制 ----
  "inject_secondary": True,

  # ---- 备份 ----
  "backup_version_on_update": False, # /update 前自动保留旧版本快照
  "backup_auto_cleanup": False,    # 自动清理开关
  "backup_auto_cleanup_days": 7,   # 自动清理保留天数

  # ---- 运行时状态（持久化到 config.json） ----
  "thinking": "profile",    # profile=走profile, off=硬关, on/high/max=强制开
"current_profile": "default",

  # ---- 系统提示词 ----
  "system_prompt": (
    "你是 DeepSeek。回答简洁，代码块用 markdown 格式。保持有帮助的语气，并清楚地传达限制。"
  ),

  # ---- 场景预设（供 /profile 命令切换） ----
  "profiles": {
    "default": {
      "temperature": 0.7,
      "thinking": False,
      "reasoning_effort": "high",
      "system_prompt": None,
      "description": "通用对话"
    },
    "code": {
      "temperature": 0.3,
      "thinking": False,
      "reasoning_effort": "high",
      "system_prompt": "你是专业的代码助手。回答简洁精确，直接给代码和解释。\n\n【重要规则】\n1. 当用户通过 @ 工具提供文件/目录内容时，请严格基于实际内容回答。\n2. 不要编造不存在的函数、类、变量或文件结构。",
      "description": "代码编写：低温，精确输出"
    },
    "debug": {
      "temperature": 0.5,
      "thinking": True,
      "reasoning_effort": "max",
      "system_prompt": "你是调试专家。请逐步分析问题原因，给出排查步骤和修复方案。\n\n【重要规则】\n1. 当用户通过 @ 工具提供文件/目录内容时，请严格基于实际内容回答。\n2. 不要编造不存在的函数、类、变量或文件结构。",
      "description": "调试模式：思考(max) + 逐步分析"
    },
    "review": {
      "temperature": 0.4,
      "thinking": True,
      "reasoning_effort": "max",
      "system_prompt": "你是代码审查专家。请从可读性、性能、安全性、健壮性四个维度分析代码，给出改进建议。\n\n【重要规则】\n1. 当用户通过 @ 工具提供文件/目录内容时，请严格基于实际内容回答。\n2. 不要编造不存在的函数、类、变量或文件结构。",
      "description": "代码审查：思考(max) + 四维分析"
    },
  },
}

# ===== 默认值快照（供 Web 端重置用，与 CLI 配置隔离） =====
_DEFAULT_CONFIG = _copy.deepcopy(CONFIG)


# ============================================================
# CONFIG_META — 配置项元数据（类型、校验规则、label）
# ============================================================
# 供 validate_and_coerce() 和 /config list 使用。
# 运行时状态（thinking、agent_mode、current_profile 等）将在 Phase 6 加入。

CONFIG_META: dict[str, dict] = {
  # ── 显示 ──
  "display_name": {
    "type": "string",
    "nullable": True,
    "label": "显示名称",
  },
  "display_color": {
    "type": "string",
    "label": "主题色 (bold cyan | bold blue | rgb(100,160,255) ...)",
  },

  # ── API ──
  "model": {
    "type": "enum",
    "values": ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"],
    "aliases": {"flash": "deepseek-v4-flash", "pro": "deepseek-v4-pro"},
    "label": "模型",
  },
  "api_base": {
    "type": "string",
    "validate": "url",
    "label": "API 地址",
  },
  "temperature": {
    "type": "float", "min": 0.0, "max": 2.0,
    "label": "温度",
  },
  "top_p": {
    "type": "float", "min": 0.0, "max": 1.0,
    "label": "核采样 (top_p)",
  },
  "api_timeout": {
    "type": "int", "min": 10, "max": 300,
    "label": "请求超时(秒)",
  },
  "api_timeout_thinking": {
    "type": "int", "min": 30, "max": 600,
    "label": "思考超时(秒)",
  },
  "api_max_retries": {
    "type": "int", "min": 0, "max": 5,
    "label": "重试次数",
  },

  # ── 上下文管理 ──
  "show_token_usage": {
    "type": "bool",
    "label": "显示 Token 用量",
  },
  "context_limiter_enabled": {
    "type": "bool",
    "label": "上下文裁剪",
  },
  "max_history_tokens": {
    "type": "int", "min": 1000, "max": 10_000_000,
    "label": "上下文预算(tokens)",
  },
  "min_history_rounds": {
    "type": "int", "min": 1, "max": 100,
    "label": "保底保留轮数",
  },
  "char_to_token_ratio": {
    "type": "float", "min": 1.0, "max": 10.0,
    "label": "字符/Token 比率",
  },

  # ── 系统提示词 ──
  "system_prompt": {
    "type": "string",
    "label": "系统提示词",
  },

  # ── 注入控制 ──
  "inject_secondary": {
    "type": "bool",
    "label": "注入次级技能（tool）",
  },
  # ── 备份 ──
  "backup_version_on_update": {
    "type": "bool",
    "label": "大版本变更时自动备份旧版本",
  },
  "backup_auto_cleanup": {
    "type": "bool",
    "label": "自动清理旧备份",
  },
  "backup_auto_cleanup_days": {
    "type": "int", "min": 1, "max": 365,
    "label": "备份保留天数",
  },

  # ── 运行时状态 ──
  "thinking": {
    "type": "enum",
    "values": ["profile", "off", "on", "high", "max"],
    "label": "思考模式",
  },
  "current_profile": {
    "type": "enum",
    "values": ["default", "code", "debug", "review"],
    "label": "当前场景",
  },

  # ── 嵌套（只读，不能直接 set） ──
  "profiles": {
    "type": "nested",
    "readonly": True,
    "label": "场景预设",
  },
}

# bool 输入映射
_TRUE_SET = frozenset({"true", "1", "on", "yes"})
_FALSE_SET = frozenset({"false", "0", "off", "no"})


def validate_and_coerce(key: str, raw: str):
  """校验 + 类型转换：将字符串原始值转为配置项应有的 Python 类型。

  参数:
    key: 配置项名称
    raw: 用户输入的字符串值

  返回:
    类型化后的值（int / float / bool / str / None）

  抛出:
    ValueError: 校验不通过或未知配置项
  """
  meta = CONFIG_META.get(key)
  if not meta:
    raise ValueError(f"未知配置项: {key}")

  t = meta["type"]

  # ── enum ──
  if t == "enum":
    if raw in meta["values"]:
      return raw
    aliases = meta.get("aliases", {})
    if raw in aliases:
      return aliases[raw]
    raise ValueError(f"可选值: {'/'.join(meta['values'])}")

  # ── int ──
  if t == "int":
    try:
      v = int(raw)
    except (ValueError, TypeError):
      raise ValueError(f"需为整数")
    if v < meta["min"] or v > meta["max"]:
      raise ValueError(f"范围 {meta['min']}–{meta['max']}")
    return v

  # ── float ──
  if t == "float":
    try:
      v = float(raw)
    except (ValueError, TypeError):
      raise ValueError(f"需为数字")
    if v < meta["min"] or v > meta["max"]:
      raise ValueError(f"范围 {meta['min']}–{meta['max']}")
    return v

  # ── bool ──
  if t == "bool":
    if raw.lower() in _TRUE_SET:
      return True
    if raw.lower() in _FALSE_SET:
      return False
    raise ValueError(f"需为 true/false/on/off/1/0/yes/no")

  # ── string ──
  if t == "string":
    if meta.get("nullable") and raw.lower() in ("null", "none", ""):
      return None
    if meta.get("validate") == "url" and not raw.startswith("http"):
      raise ValueError(f"需以 http 开头")
    return raw

  # ── nested ──
  if t == "nested":
    raise ValueError(f"嵌套配置，不能直接设置")

  raise ValueError(f"不支持的配置类型: {t}")


# ============================================================
# 持久化
# ============================================================

_USER_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".tiao_config.json")


def persist_config():
  """将当前 CONFIG 原子写入 ~/.tiao_config.json。

  只持久化顶层标量键（排除 profiles 等嵌套结构，由用户按需保留）。
  """
  import logging
  logger = logging.getLogger("tiao")

  # 只保存非嵌套、非只读的顶层配置项
  export = {}
  for key in CONFIG:
    if key in ("api_key", "system_prompt"):
      continue # api_key 有专用加密文件；system_prompt 由 profiles 决定
    meta = CONFIG_META.get(key)
    if meta and meta.get("type") == "nested":
      continue # 跳过 profiles 等嵌套结构
    export[key] = CONFIG[key]

  tmp = _USER_CONFIG_PATH + ".tmp"
  try:
    with open(tmp, "w", encoding="utf-8") as f:
      json.dump(export, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _USER_CONFIG_PATH)
  except (OSError, IOError) as e:
    logger.warning("写入配置失败 (%s): %s", _USER_CONFIG_PATH, e)


def load_config():
  """从 ~/.tiao_config.json 加载用户配置，递归合并覆盖默认值。

  可被外部显式调用，也支持模块导入时自动加载。
  """
  if not os.path.isfile(_USER_CONFIG_PATH):
    return
  try:
    with open(_USER_CONFIG_PATH, "r", encoding="utf-8") as f:
      user_cfg = json.load(f)
  except (json.JSONDecodeError, IOError):
    return
  if not isinstance(user_cfg, dict):
    import logging
    logging.getLogger("tiao").warning("用户配置文件格式无效（非 JSON 对象），已忽略")
    return
  _deep_merge(CONFIG, user_cfg)


def _deep_merge(base: dict, override: dict):
  """递归合并 override 到 base（原地修改）"""
  for key, val in override.items():
    if key in base and isinstance(base[key], dict) and isinstance(val, dict):
      _deep_merge(base[key], val)
    else:
      base[key] = val


# ===== Web 端独立配置 =====

_WEB_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".tiao_web_config.json")


def load_web_config():
  """从 ~/.tiao_web_config.json 加载 Web 端专属配置，覆盖 CONFIG。

  先重置 CONFIG 为代码默认值（不受 ~/.tiao_config.json 影响），
  再加载 Web 端自定义配置。与 CLI 的 ~/.tiao_config.json 完全隔离。
  Web 端启动时调用。
  """
  # 重置为出厂默认值，清除共享配置的污染
  CONFIG.clear()
  CONFIG.update(_copy.deepcopy(_DEFAULT_CONFIG))

  # 加载 Web 专属配置
  if not os.path.isfile(_WEB_CONFIG_PATH):
    return
  try:
    with open(_WEB_CONFIG_PATH, "r", encoding="utf-8") as f:
      cfg = json.load(f)
  except (json.JSONDecodeError, IOError):
    return
  if not isinstance(cfg, dict):
    return
  _deep_merge(CONFIG, cfg)


# 模块导入时自动加载用户配置覆盖
load_config()
