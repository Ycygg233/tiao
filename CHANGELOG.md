# Changelog

## v2.1.0 (2026-05-16)

### 🎨 动画与体验
- 流星动画改为 Braille spinner（`⠋⠙⠹...`），帧率波动不卡顿，无文字标签
- 去线程化：动画由后台线程改为同步内联绘制，消除 stdout 竞态
- 光标隐藏：回复输出期间隐藏光标，返回 prompt 时恢复，不再闪烁
- 标题生成 Spinner：`/title` / `/save` 使用 Rich `status()` spinner 替代手动打印

### 🔧 标题与会话
- `/title` 和 `/save` 改为直调 API，不复用 `chat_stream()`，不污染消息历史
- 修复会话重命名分叉 bug：改名时调用 `rename_session_file()` 而非 INSERT 新记录
- 修复自动保存计数器（`_total_since_save` 永远到不了 5 的问题）

### 🔒 权限与安全
- `__exec__` 超时从硬编码 30s 改为动态：su 300s / su+ 无限制
- `run_python` su+ 超时确认无限制（`thread.join(timeout=None)`）

### 📚 文档与技能
- README 定位从"AI 编码助手"改为"打理终端 · 辅助编码"
- 快速开始新增首次引导表格，分全自动 / 手动安装两种方式
- skills/ 项目目录描述重写，匹配实际沙箱保护与备份路径
- skills/ 完整命令列表从 9 条补充到 28 条
- 权限文档 `__exec__` 超时数值修正

### 🧹 清理
- 移除 `skills/prompts.py` 中废弃的 `"memo"` 作用域
- 清理 config.py / commands/session_cmds.py 中的 memo 残留文本
- `chat/_thinking.py` 从 84 行精简至 29 行（去线程化 + 简化帧逻辑）
- 语言别名表从 25 条扩充至 45 条，补充 C/C++ 启发式检测

### ⚙️ 其他
- `/reasoning` 命令加入命令列表
- 新增 `tiao-web` 别名，Web 模式快捷启动
- 修正 main.py 中启动画面会话名过长溢出问题
