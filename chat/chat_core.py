"""chat_core.py — 核心对话逻辑（facade，从 chat/ 包重导出）

保持向后兼容，所有 import chat_core 的模块不受影响。
"""
from chat._shared import (
  _confirm_func, _output_sink,
  _messages_lock, _total_input_tokens, _total_output_tokens,
  set_confirm_func, set_output_sink, clear_output_sink,
  set_thinking, _get_thinking_status, reset_thinking,
  set_workspace, get_workspace,
  _get_config, _sanitize_effort, _build_api_kwargs, _token_valid,
  _execute_tool_core,
)
from chat._stream import (
  _get_http_session, warmup_connection, warmup_tokenizer,
  _direct_chat_stream,
  _on_api_failure, chat_stream,
)
