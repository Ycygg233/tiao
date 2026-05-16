# chat/_stream.py - 对话流 + API 通信（HTTP 会话、直调 API、chat_stream）
import os
import sys
import json
import time as _time
import threading
import logging
import signal
import queue as _queue
from typing import Optional

import requests as _requests
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.text import Text
from rich.syntax import Syntax
import re as _re

from config import CONFIG, valert

from chat._shared import _messages_lock, _total_input_tokens, _total_output_tokens, _output_sink
from chat._shared import _get_config, _build_api_kwargs, _token_valid, _execute_tool_core, set_workspace
from chat.chat_messages import _trim_messages, _sanitize_messages
from chat.chat_display import _fmt_tokens, _format_tool_call, _print_token_usage
from tools import get_tool, get_openai_tools, _AI_SAFE_TOOLS
from security.dialog import set_auto_confirm
from tools.quota import get_quota
from utils import count_tokens, count_tokens_messages
from chat._thinking import draw_frame, clear_line

# ── 打断标志 ──
_cancel_requested = False

def _handle_stop(sig, frame):
    global _cancel_requested
    _cancel_requested = True

signal.signal(signal.SIGTSTP, _handle_stop)

# ========== HTTP 会话池（冷启动预热 + 连接复用降首 Token 延迟） ==========

_http_session = None
_http_session_lock = threading.Lock()


def _get_http_session():
  """全局 HTTP 会话（懒初始化，urllib3 连接池复用）"""
  global _http_session
  if _http_session is not None:
    return _http_session
  with _http_session_lock:
    if _http_session is not None:
      return _http_session
    session = _requests.Session()
    adapter = _requests.adapters.HTTPAdapter(
      pool_connections=10,
      pool_maxsize=20,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    _http_session = session
    return session



def warmup_connection():
  """ 预热 HTTP 连接（后台执行，降首 Token 延迟）"""
  session = _get_http_session()
  api_base = CONFIG.get("api_base", "")
  api_key = CONFIG.get("api_key", "")
  if not api_base or not api_key:
    return
  try:
    session.get(
      f"{api_base}/models",
      headers={"Authorization": f"Bearer {api_key}"},
      timeout=15,
    )
  except Exception:
    pass


def warmup_tokenizer():
  """ 预热 tiktoken（后台加载，避免首次计数卡 10s 超时）"""
  try:
    import tiktoken
    tiktoken.get_encoding("cl100k_base")
  except Exception:
    pass


log = logging.getLogger("tiao")
console = Console(color_system="truecolor", force_terminal=True)


_LANG_ALIAS = {
  "py": "python", "js": "javascript", "ts": "typescript",
  "sh": "bash", "shell": "bash", "yml": "yaml",
  "c++": "cpp", "c#": "csharp", "cs": "csharp",
  "jsx": "javascript", "tsx": "typescript",
  "html5": "html", "htm": "html", "xhtml": "html",
  "rb": "ruby", "rs": "rust", "go": "go",
  "kt": "kotlin", "swift": "swift", "m": "objectivec",
  "pl": "perl", "pm": "perl", "lua": "lua",
  "ps1": "powershell", "bat": "batch", "cmd": "batch",
  "dockerfile": "docker", "makefile": "make",
  # 高频补充
  "c": "c", "cpp": "cpp",
  "css": "css", "scss": "scss", "less": "less",
  "sql": "sql", "mysql": "sql", "pgsql": "sql",
  "xml": "xml",
  "json": "json", "toml": "toml", "ini": "ini", "cfg": "ini",
  "md": "markdown", "markdown": "markdown",
  "text": "text", "plain": "text", "txt": "text",
  "php": "php", "r": "r", "dart": "dart",
  "haskell": "haskell", "hs": "haskell",
  "scala": "scala",
  "cmake": "cmake",
  "diff": "diff", "patch": "diff",
  "vue": "vue", "svelte": "svelte",
  "makefile": "make", "docker": "docker",
  "bash": "bash", "zsh": "bash",
  "console": "bash", "terminal": "bash",
  "yaml": "yaml", "yml": "yaml",
  "js": "javascript", "ts": "typescript",
}


def _resolve_lang(lang: str) -> str:
  """解析语言标签：别名映射 → 有效性校验"""
  if not lang:
    return ""
  lang = lang.strip().lower()
  lang = _LANG_ALIAS.get(lang, lang)
  if _re.match(r"^[a-zA-Z][a-zA-Z0-9+#-]*$", lang):
    return lang
  return ""


def _guess_lang(code: str) -> str:
  """从代码内容启发式推测语言（在标签为空时兜底）

  优先级：特异性强的语言（Go/Rust/Java）先检测，通用语言（Python/JS）放后。
  """
  if not code:
    return ""
  head = code[:300]
  # C/C++ — #include / int main / printf / std:: 等特征
  if _re.search(r'#include\s*[<"]|int\s+main\s*\(|printf\s*\(|std::', head):
    return "c" if _re.search(r'\.h\s*$|printf|malloc|struct\s+\w+\s*{', head) else "cpp"
  # Go — package/import 组合极具特异性
  if _re.search(r"\bpackage\s+\w+|import\s+\"|fmt\.|go\s+func|:=\s", head):
    return "go"
  # Rust — fn/let mut/impl/pub fn 组合
  if _re.search(r"\bfn\s+\w+|let\s+mut\b|impl\s+\w+|pub\s+fn\b|unwrap\(\)", head):
    return "rust"
  # Java — public class/void main/System.out 极具特异性
  if _re.search(r"\bpublic\s+(class|static|void)\b|void\s+main\b|System\.out|@Override", head):
    return "java"
  # Bash — shebang / 常见命令行工具
  if _re.search(r"^#!|^(apt|yum|npm|pip|git|docker|kubectl)\s", head):
    return "bash"
  # HTML — DOCTYPE / 标签根
  if _re.search(r"^<!DOCTYPE html|<html[\s>]|<svg[\s>]", head):
    return "html"
  # SQL — 关键字组合
  if _re.search(r"SELECT\s+.*\s+FROM|CREATE\s+TABLE|INSERT\s+INTO|ALTER\s+TABLE", head, _re.IGNORECASE):
    return "sql"
  # JSON — 对象/数组根
  if _re.search(r"^\{\s*\"|^\[\s*\"", head):
    return "json"
  # JavaScript — => / console. / document. / window. / import { / function
  if _re.search(r"\b(function|const|let|var)\s+\w+|=>|console\.|document\.|window\.|import\s*\{", head):
    return "javascript"
  # Python — 兜底，关键字较通用
  if _re.search(r"\b(def|class)\s+\w+|\b(import|from)\s+\w+|raise\s+|except\b|elif\b|yield\b|print\(|if\s+__name__|try:", head):
    return "python"
  return ""


class _StreamSegmenter:
  """流式内容分段器：按 ``` 切分文本/代码段，闭合段冻结为 Rich renderable（永不重解析）"""
  def __init__(self):
    self.frozen = []        # 已冻结的 renderable 列表
    self.state = "text"     # "text" | "code"
    self.text_buf = ""      # 当前文本段缓存
    self.code_buf = ""      # 当前代码段缓存
    self.code_lang = ""     # 当前代码段语言

  def feed(self, chunk: str):
    """喂入一段 chunk，闭合时自动冻结"""
    i = 0
    while i < len(chunk):
      if self.state == "text":
        idx = chunk.find("```", i)
        if idx == -1:
          self.text_buf += chunk[i:]
          break
        # 文本段闭合：``` 之前的内容
        self.text_buf += chunk[i:idx]
        if self.text_buf:
          self.frozen.append(Markdown(self.text_buf))
          self.text_buf = ""
        i = idx + 3
        self.state = "code"
        self.code_buf = ""
        # 读取语言名
        line_end = chunk.find("\n", i)
        if line_end != -1:
          lang = chunk[i:line_end].strip()
          i = line_end + 1
        else:
          lang = chunk[i:].strip()
          i = len(chunk)
        self.code_lang = _resolve_lang(lang)
        if not self.code_lang and lang:
          # 不是合法语言标签，内容退回 code_buf
          self.code_buf = lang + "\n"
      else:  # code
        close_idx = chunk.find("```", i)
        if close_idx == -1:
          self.code_buf += chunk[i:]
          break
        self.code_buf += chunk[i:close_idx]
        if self.code_buf:
          lexer = self.code_lang or _guess_lang(self.code_buf) or "text"
          self.frozen.append(Syntax(self.code_buf, lexer, theme="monokai", line_numbers=True))
          self.code_buf = ""
        i = close_idx + 3
        self.state = "text"

  def finalize(self):
    """流结束时冻结剩余内容"""
    if self.text_buf:
      self.frozen.append(Markdown(self.text_buf))
      self.text_buf = ""
    elif self.code_buf:
      lexer = self.code_lang or _guess_lang(self.code_buf) or "text"
      self.frozen.append(Syntax(self.code_buf, lexer, theme="monokai", line_numbers=True))
      self.code_buf = ""

  def build_group(self) -> Group:
    """构建当前用于 Live 显示的 Group"""
    parts = list(self.frozen)
    if self.state == "text" and self.text_buf:
      parts.append(Markdown(self.text_buf))
    elif self.state == "code" and self.code_buf:
      parts.append(Text(self.code_buf, style="bold color(250)"))
    return Group(*parts) if parts else Text("")


def _direct_chat_stream(model, messages, *, token="", thinking=False,
                        tools=None, api_kwargs=None, stream_output=True, display_max=0):
  global _cancel_requested
  import time as _t
  t0 = _t.time()
  full_content = ""
  reasoning_content = ""
  tool_calls_acc = {}
  _reasoning_done = False

  body = {
    "model": model or CONFIG["model"],
    "messages": messages,
    "stream": True,
  }
  if tools:
    body["tools"] = tools
  if api_kwargs:
    for k in ("temperature", "top_p", "reasoning_effort"):
      if k in api_kwargs:
        body[k] = api_kwargs[k]
    extra = api_kwargs.get("extra_body", {})
    if extra:
      body["extra_body"] = extra

  req_timeout = CONFIG.get("api_timeout_thinking", 180) if thinking else CONFIG.get("api_timeout", 60)
  api_base = CONFIG["api_base"]
  api_key = CONFIG.get("api_key", "")

  try:
    resp = _get_http_session().post(
      f"{api_base}/chat/completions",
      headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
      },
      json=body,
      stream=True,
      timeout=req_timeout,
    )
    resp.raise_for_status()

    _segmenter = _StreamSegmenter()
    _printed_seg = 0  # 已打印的分段数
    _reasoning_printed = False

    # ── 独立线程读取 SSE，主线程通过 Queue 获取并同步画动画 ──
    _anim_frame = 0
    _line_queue = _queue.Queue()

    def _reader():
      try:
        for line in resp.iter_lines(decode_unicode=True):
          if line is not None:
            _line_queue.put(line)
      finally:
        _line_queue.put(None)  # EOF 哨兵

    _reader_thread = threading.Thread(target=_reader, daemon=True)
    _reader_thread.start()

    try:
      while True:
        try:
          line = _line_queue.get(timeout=0.05)
        except _queue.Empty:
          draw_frame(_anim_frame)
          _anim_frame += 1
          continue
        if line is None:
          break  # EOF

        if _cancel_requested:
          raise KeyboardInterrupt
        if not line.startswith("data: "):
          continue
        data_str = line[6:]
        if data_str.strip() == "[DONE]":
          break
        try:
          chunk = json.loads(data_str)
        except json.JSONDecodeError:
          continue
        if not chunk.get("choices"):
          continue
        delta = chunk["choices"][0].get("delta", {})

        if delta.get("content"):
          if reasoning_content and not _reasoning_done and _output_sink:
            _output_sink({"type": "think_done", "content": ""})
            _reasoning_done = True
          full_content += delta["content"]
          if _output_sink and stream_output:
            _output_sink({"type": "chunk", "content": delta["content"]})
          else:
            # content 到达 → 清除动画行，打印内容
            clear_line()
            # 首次出现 content 时打印推理内容（如有）
            if not _reasoning_printed and reasoning_content and CONFIG.get("show_reasoning"):
              console.print(Text(reasoning_content, style="color(244)"))
              console.print("")
              _reasoning_printed = True
            # 喂给分段器，打印新闭合的段
            _segmenter.feed(delta["content"])
            while _printed_seg < len(_segmenter.frozen):
              console.print(_segmenter.frozen[_printed_seg])
              _printed_seg += 1

        if delta.get("reasoning_content"):
          reasoning_content += delta["reasoning_content"]
          if _output_sink:
            _output_sink({"type": "think", "content": delta["reasoning_content"]})

        if tools and delta.get("tool_calls"):
          for tc_delta in delta["tool_calls"]:
            idx = tc_delta["index"]
            if idx not in tool_calls_acc:
              tool_calls_acc[idx] = {
                "id": "",
                "function": {"name": "", "arguments": ""},
              }
            if tc_delta.get("id"):
              tool_calls_acc[idx]["id"] = tc_delta["id"]
            if tc_delta.get("function"):
              if tc_delta["function"].get("name"):
                tool_calls_acc[idx]["function"]["name"] += tc_delta["function"]["name"]
              if tc_delta["function"].get("arguments"):
                tool_calls_acc[idx]["function"]["arguments"] += tc_delta["function"]["arguments"]
    except KeyboardInterrupt:
      _cancel_requested = True
      clear_line()
      log.info("已取消")
      return None
    finally:
      clear_line()
      if full_content:
        _segmenter.finalize()
        if not _reasoning_printed and reasoning_content and CONFIG.get("show_reasoning"):
          console.print(Text(reasoning_content, style="color(244)"))
          console.print("")
        while _printed_seg < len(_segmenter.frozen):
          console.print(_segmenter.frozen[_printed_seg])
          _printed_seg += 1

    elapsed = _t.time() - t0

    # ── 降级：deepseek thinking 模式下，首条回复可能只有 reasoning_content，content 为空 ──
    if not full_content.strip() and reasoning_content.strip():
      if _output_sink and not _reasoning_done:
        _output_sink({"type": "think_done", "content": ""})
        _reasoning_done = True
      if _output_sink and stream_output:
        _output_sink({"type": "chunk", "content": reasoning_content})
      full_content = reasoning_content

    return {
      "content": full_content,
      "reasoning": reasoning_content,
      "tool_calls": tool_calls_acc,
      "elapsed": elapsed,
    }

  except _requests.exceptions.RequestException as e:
    err_detail = ""
    if hasattr(e, 'response') and e.response is not None:
      try:
        err_body = e.response.text[:500]
        err_detail = f"\n响应: {err_body}"
      except Exception:
        pass
    log.warning("直调 API 请求失败: %s%s", e, err_detail)
    if _output_sink:
      _output_sink({"type": "error", "content": f"✗ 直调失败: {e}{err_detail}"})
    else:
      valert(console, "red", "✗", f"直调失败: {e}{err_detail}")
    return None
  except Exception as e:
    log.error("直调异常: %s", e)
    return None


def _on_api_failure(messages: list, iteration: int):
  with _messages_lock:
    if messages and messages[-1].get("role") == "user":
      popped = messages.pop()
      log.debug("API 失败，回滚用户消息: %s", popped.get("content", "")[:50])
  msg = (f"[bold color(167)]✗ API 请求失败（第 {iteration} 轮）[/bold color(167)]\n"
      f"[dim]已移除本轮输入，可重试。如持续失败请检查网络或缩短上下文 (/clear 后继续)。[/dim]")
  if _output_sink:
    _output_sink({"type": "error", "content": msg})
  else:
    console.print(msg)



def chat_stream(user_input: str, messages: list, last_reply_ref: list,
                token: str = "", thinking: bool = False, model: str = "",
                stream_output: bool = True, workspace: str = "",
                temperature: float = None, top_p: float = None,
                reasoning_effort: str = None) -> None:
  global _cancel_requested
  if not user_input or not user_input.strip():
    log.warning("chat_stream 收到空输入，跳过")
    return

  # 整个回复输出期间隐藏光标，返回 prompt 前恢复
  sys.stdout.write("\033[?25l")
  sys.stdout.flush()
  try:

    if workspace:
      set_workspace(workspace)

    with _messages_lock:
      messages.append({"role": "user", "content": user_input})
    _trim_messages(messages, _messages_lock)
    actual_model = model or CONFIG["model"]

    if CONFIG.get("context_limiter_enabled", True):
      incoming_tokens = count_tokens(user_input)
      history_tokens = count_tokens_messages(messages)
      budget_tokens = _get_config("max_history_tokens", 1000000)
      if history_tokens + incoming_tokens > budget_tokens:
        budget_chars = budget_tokens * _get_config("char_to_token_ratio", 3.0)
        history_est = f"≈{history_tokens} tokens" if history_tokens else f"{sum(len(m.get('content','')) for m in messages):,} chars"
        msg = (f"[yellow]⚠ 此消息较长，发送后将触发历史裁剪。[/yellow]\n"
            f"[dim]当前 {history_est} + 新增 ≈{incoming_tokens} tokens "
            f"> 预算 {budget_tokens:,} tokens ({budget_chars:,.0f} chars)。[/dim]\n"
            f"[dim]如需保留全部上下文，可先执行 /limit off[/dim]")
        if _output_sink:
          _output_sink({"type": "warn", "content": msg})
        else:
          console.print(msg)

    with _messages_lock:
      _known_ids = {id(m) for m in messages}
      working = list(messages)
    _cached_tools = getattr(chat_stream, "_tool_cache", None)
    if _cached_tools is None:
      chat_stream._tool_cache = get_openai_tools()
    tools = chat_stream._tool_cache
    iteration = 0

    while True:
      iteration += 1
      if iteration == 20:
        if _output_sink:
          _output_sink({"type": "warn", "content": "⚠ 已调用 20 轮工具，继续运行中"})
        else:
          valert(console, "yellow", "⚠", "已调用 20 轮工具，继续运行中")
      if iteration % 3 == 0 and len(working) > len(messages) + 5:
        _trim_messages(working)
      if not _token_valid(token):
        log.debug("令牌已过期，终止对话流")
        _on_api_failure(messages, iteration)
        return

      if _output_sink:
        _output_sink({"type": "status", "content": "思考中…"})

      api_kwargs = {}
      if temperature is not None:
        api_kwargs["temperature"] = temperature
      else:
        api_kwargs["temperature"] = CONFIG["temperature"]
      topp_val = top_p if top_p is not None else CONFIG.get("top_p")
      if topp_val is not None:
        api_kwargs["top_p"] = topp_val
      api_kwargs.update(_build_api_kwargs(thinking=thinking, reasoning_effort=reasoning_effort))

      result = _direct_chat_stream(
        actual_model, _sanitize_messages(working, strip_reasoning=False, model=actual_model),
        token=token, thinking=thinking, tools=tools,
        api_kwargs=api_kwargs, stream_output=stream_output,
      )

      if result is None:
        if _cancel_requested:
          _cancel_requested = False  # 复位
          return
        _on_api_failure(messages, iteration)
        return

      full_content = result["content"]
      reasoning_content = result["reasoning"]
      tool_calls_acc = result["tool_calls"]
      elapsed = result["elapsed"]

      if not tool_calls_acc and not full_content.strip():
        if _output_sink:
          _output_sink({"type": "warn", "content": "⚠ 模型返回为空，可能是内容被过滤或上下文过长。建议 /clear 后重试。"})
        else:
          valert(console, "yellow", "⚠", "模型返回为空，可能是内容被过滤或上下文过长。建议 /clear 后重试。")
        _on_api_failure(messages, iteration)
        return

      if not _token_valid(token):
        log.debug("令牌已过期，丢弃结果")
        _on_api_failure(messages, iteration)
        return

      if tool_calls_acc:
        sorted_indices = sorted(tool_calls_acc.keys())
        tool_calls_list = [tool_calls_acc[i] for i in sorted_indices]

        assistant_msg = {
          "role": "assistant",
          "content": full_content,
          "reasoning_content": reasoning_content or "",
          "tool_calls": [
            {
              "id": tc["id"],
              "type": "function",
              "function": {
                "name": tc["function"]["name"],
                "arguments": tc["function"]["arguments"],
              },
            }
            for tc in tool_calls_list
          ],
        }
        working.append(assistant_msg)

        set_auto_confirm(True)
        try:
          for tc_data in tool_calls_list:
            if _cancel_requested:
              _cancel_requested = False
              console.print("[dim] 已取消剩余工具调用[/dim]")
              break
            tool_name = tc_data["function"]["name"]
            try:
              args = json.loads(tc_data["function"]["arguments"])
            except json.JSONDecodeError:
              args = {}

            if tool_name not in _AI_SAFE_TOOLS:
              result = f"✗ 不允许 AI 自动调用 {tool_name}，需要用户手动执行"
              log.warning("AI 尝试调用非安全工具: %s", tool_name)
              working.append({
                "role": "tool", "tool_call_id": tc_data["id"], "content": result,
              })
              continue

            fn = get_tool(tool_name)
            if not fn:
              result = f"✗ 未知工具: {tool_name}"
              working.append({
                "role": "tool", "tool_call_id": tc_data["id"], "content": result,
              })
              continue

            display = _format_tool_call(tool_name, args)
            if _output_sink:
              _output_sink({"type": "tool", "content": f"{display} [{elapsed:.1f}s]"})
            else:
              if "(" in display and display.endswith(")"):
                name_part, inside = display.split("(", 1)
                inside = inside.rstrip(")")
                colored = f"[bold color(80)]{name_part}([/bold color(80)][bold color(80)]{inside}[/bold color(80)][bold color(80)])[/bold color(80)]"
              else:
                colored = f"[bold color(80)]{display}[/bold color(80)]"
              console.print(f"  {colored} [dim]{elapsed:.1f}s[/dim]")
            result, ok = _execute_tool_core(tool_name, args, elapsed)
            working.append({
              "role": "tool", "tool_call_id": tc_data["id"], "content": result,
            })
        finally:
          set_auto_confirm(False)
        continue
      else:
        with _messages_lock:
          last_reply_ref[0] = full_content
          _print_token_usage(messages, full_content, reasoning_content)
      with _messages_lock:
        for m in working:
          if id(m) not in _known_ids:
            messages.append(m)
        final_msg = {"role": "assistant", "content": full_content, "reasoning_content": reasoning_content or ""}
        messages.append(final_msg)

      if _output_sink and not stream_output:
        _output_sink({"type": "message", "content": full_content})
      return
  finally:
    sys.stdout.write("\033[?25h")
    sys.stdout.flush()


