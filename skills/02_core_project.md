# 项目目录结构

## 代码位置（用户自定）
项目代码存放在用户选择的目录，默认 `~/tiao/`（Termux 家目录）。
该目录受沙箱**硬保护**（`_PROTECTED_ROOT`），AI 不可直接写入，
文件修改应通过工具调用（@write_file / @replace）并受沙箱权限控制。

## 运行时数据（固定位置）
| 位置 | 内容 |
|:-----|:------|
| `~/.tiao_data/sessions/tiao.db` | 会话持久化（SQLite） |
| `~/.tiao_data/logs/` | 日志文件 + logs.db（结构化审计日志） |
| `~/.tiao_data/search_cache/` | 搜索缓存 |
| `~/.tiao_config.json` | 用户配置（递归合并覆盖默认值） |
| `~/.tiao_key` | API Key（XOR 混淆加密） |
| `~/.tiao_providers_env` | 搜索平台 Key（metaso/tavily/jina/bocha） |
| `~/.tiao_sudo.json` | 提权持久化状态 |

数据目录可由环境变量 `TIAO_DATA_DIR` 覆盖。

## 工作区（动态设定）
工作区通过 `/workspace <路径>` 命令动态设定，不固定。
设定后，AI 工具调用会自动感知工作区上下文，文件读取阈值放宽。

## 备份（快照机制）
备份统一保存在 `/storage/emulated/0/_BACKUPS_/`：
- `tiao_new.tar.gz` / `tiao_old.tar.gz` — 双槽滚动备份
- `alert_<时间戳>.tar.gz` — 紧急备份（审计 high 告警时自动触发）
- `version_before_<标签>.tar.gz` — 大版本更新前快照

## 文件操作原则
- 读写操作均经 `sandbox_check()` 检查路径白名单和权限级别
- 项目代码目录的写操作默认被沙箱拦截（硬保护）
- 默认级别只读；`/su` 解锁写操作 + run_python；`/su+` 完全放行
