"""styles.py — 256 色语义色板

用亮度做层次，用色相做情绪。
所有 CLI 输出统一通过此表查色，新增输出时勿拍脑门选颜色。
"""
from typing import Final
from rich.theme import Theme

# ── Rich Theme（覆盖 Markdown 标题默认粉紫色）──────────
# 样式名格式: markdown.h1 / markdown.h2 / markdown.code 等
TIAO_THEME = Theme({
    "markdown.h1":           "bold color(255)",          # 纯白，章节锚点
    "markdown.h2":           "bold color(248)",          # 亮灰白，小节
    "markdown.h3":           "bold color(248)",          # 亮灰白，子项（同 h2）
    "markdown.h4":           "bold color(235)",          # 深灰，次级
    "markdown.code":         "color(250) on color(235)", # 代码块
    "markdown.block_quote":  "italic color(245)",        # 块引用——灰色斜体，替代默认紫
    "markdown.link":         "underline color(68)",      # 链接——钢蓝下划线，替代默认紫
    "markdown.link_url":     "dim color(240)",           # 链接 URL——灰色退后
    "markdown.kbd":          "color(250) on color(235)", # 键盘按键——代码同款背景
})

# ── 亮度梯度（结构/辅助）───────────────────────────────
# 数字越大越亮（0=黑, 255=白），暗底上 >240 为前景色
BORDER:   Final[str] = "dim color(240)"    # 边框/面板 —— 几乎隐形
SEPARATOR:  Final[str] = "color(238)"      # 分隔线 —— 结构支撑，不抢戏
MUTED:    Final[str] = "color(245) italic"  # 次要文本/时间戳 —— 彻底退后
WAIT:    Final[str] = "color(245)"      # 等待态 —— 灰白隐身，高频重复必须安静
BODY:    Final[str] = "color(250)"      # 正文 —— 阅读主体
CODE_BG:   Final[str] = "color(250) on color(235)" # 代码/路径 —— 微反差背景

# ── 蓝系（元信息/标识）─────────────────────────────────
SOURCE:   Final[str] = "color(67)"       # 来源标识（DeepSeek · 19:57）—— 钢蓝
TECH_TAG:  Final[str] = "color(73)"       # 技术关键词（usage, cancel）—— 柔和青蓝

# ── 青系（动作态）──────────────────────────────────────
ACTION:   Final[str] = "bold color(80)"    # 工具调用（read_file()）—— 降刺青
RUNNING:   Final[str] = "color(80)"       # 执行中（ 步骤 X）—— 同色相非粗体

# ── 情绪色（低频点缀）─────────────────────────────────
SUCCESS:   Final[str] = "color(78)"       # 成功确认（✓ 备份已清理）—— 柔和绿
WARN:    Final[str] = "color(172)"       # 警告（⚠ 路径不能为空）—— 暗金/暖橙
ERROR:    Final[str] = "color(167) bold"    # 错误（✗ 执行失败）—— 柔和红

# ── 结构锚点 ──────────────────────────────────────────
LABEL:    Final[str] = "white bold"       # P0/P1/P2 标签、节标题
HEADING:   Final[str] = "bold color(255)"     # Markdown H1 标题 —— 纯白，章节锚点
HEADING_H2: Final[str] = "bold color(246)"     # Markdown H2 标题 —— 亮灰白，小节
HEADING_H3: Final[str] = "bold color(246)"     # Markdown H3 标题（同 H2 亮灰白）


# ── 快速替换对照表（从旧 16 色迁移用）────────────────
MIGRATION = {
  "green":   SUCCESS,   # [green] → [color(78)]
  "bold green": f"bold {SUCCESS}",
  "yellow":   WARN,     # [yellow] → [color(172)]
  "red":    ERROR,    # [red] → [color(167) bold]
  "bold red":  f"bold color(167)",
  "blue":    SOURCE,    # [blue] → [color(67)]
  "cyan":    ACTION,    # [cyan](tool) → [bold color(80)]
  "dim cyan":  SEPARATOR,  # [dim cyan] → [color(238)]
  "bold cyan": SOURCE,   # [bold cyan](user prefix) → color(67) 钢蓝
  "dim":    MUTED,    # [dim](help) → [color(245) italic]
  "bold":    LABEL,    # [bold] → [white bold]
}
