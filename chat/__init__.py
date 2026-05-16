"""chat/ — 对话核心包

包结构：
 _shared.py  共享状态 + 配置读写 + 工具执行核心（142行）
 _stream.py  对话流 + API 通信（426行）
 _agent.py   Agent 模式（223行）
 
外部统一通过 chat_core.py facade 导入，保持向后兼容。
"""
