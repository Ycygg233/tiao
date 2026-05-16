# 01_tool_rules.md - 工具决策锚点

## 工具链：scan_dir → find → read_file
- 项目路径先 scan_dir 侦察，大目录（>200项）不展开
- 文件 ≤5 全读，6~15 读小文件+汇总大文件，>15 只汇报结构
- 需要询问时一次性列清单

## 规则
- 不输出 @语法，严格基于工具返回内容回答
- write/delete 需确认，路径有白名单
- 需完整规范时 read_file skills/02_ref_tool_rules_full.txt

## 提权路径
- `/su` — 中级提权，解锁 `run_python` + `__exec__`（安全白名单命令）
- `/su+` — 完全放行，无 AST 拦截、完整 builtins、任意命令、任意路径读写
- 默认级别只读，写操作需确认
