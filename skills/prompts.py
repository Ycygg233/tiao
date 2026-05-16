# prompts.py - System Prompt 构建
import os

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SKILLS_DIR = os.path.join(_BASE_DIR, "skills")

# 基础作用域：始终注入
_CORE_SCOPES = {"core"}
# 次级作用域：由 inject_secondary 开关控制
_SECONDARY_SCOPES = {"tool"}


def get_always_scopes(config: dict = None) -> set:
  """根据配置返回实际生效的始终注入作用域

  参数:
    config: CONFIG 字典，用于读取 inject_secondary 开关
        为 None 时返回全量（兼容旧调用方）

  返回:
    始终注入的作用域集合
  """
  scopes = set(_CORE_SCOPES)
  if config is None or config.get("inject_secondary", True):
    scopes |= _SECONDARY_SCOPES
  if config is None or config.get("align_guide", True):
    scopes |= {"guide"}
  return scopes


def load_skills(log=None, config: dict = None) -> str:
  """加载 skills/ 目录下始终注入的 .md 文件，拼接成一段文本。

  文件名约定：{NN}_{scope}_{name}__{tags}.md
  scope 在 get_always_scopes(config) 中的始终加载，其余按需（AI 自行 read_file）。

  参数:
    log: 日志记录器
    config: CONFIG 字典，用于控制次级作用域是否注入
  """
  if not os.path.isdir(SKILLS_DIR):
    return ""
  active_scopes = get_always_scopes(config)
  _KNOWN_OPTIONAL_SCOPES = {"cap", "domain", "ref", "arch", "guide"}
  parts = []
  try:
    files = sorted(f for f in os.listdir(SKILLS_DIR) if f.endswith(".md"))
    for fname in files:
      stem = fname.replace(".md", "")
      stem = stem.split("__")[0]
      segments = stem.split("_", 1)
      if len(segments) < 2:
        if log:
          log.warning("skills/%s 不遵循命名约定 {NN}_{scope}_{name}__{tags}.md，已跳过", fname)
        continue
      scope = segments[1].split("_")[0]
      if scope not in active_scopes:
        if scope not in _KNOWN_OPTIONAL_SCOPES and log:
          log.debug("skills/%s 作用域 '%s' 不在活跃集合 %s", fname, scope, active_scopes)
        continue

      fpath = os.path.join(SKILLS_DIR, fname)
      try:
        with open(fpath, "r", encoding="utf-8") as f:
          content = f.read().strip()
        if content:
          parts.append(content)
      except Exception as e:
        if log:
          log.warning("加载 skills/%s 失败: %s", fname, e)
  except Exception as e:
    if log:
      log.warning("读取 skills 目录失败: %s", e)
  return "\n\n".join(parts)


def build_system_prompt(config: dict, profile_name: str, skills_text: str = "",
            rules_text: str = "") -> str:
  """根据 profile 构建完整 system prompt"""
  profile_cfg = config.get("profiles", {}).get(profile_name, {})
  sp_base = profile_cfg.get("system_prompt") or config.get("system_prompt", "")
  parts = [sp_base]
  if skills_text:
    parts.append(skills_text)
  if rules_text:
    parts.append(f"## 注入的项目规则\n{rules_text}")
  return "\n\n".join(parts)
