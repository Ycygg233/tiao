# tools/file_ops.py - 文件/目录操作工具 + tiao 专属工具
import os
import shlex
import stat
from datetime import datetime

from config import CONFIG
from utils import fmt_size
from security import sandbox_check, _backup_file, _generate_diff, _get_workspace_context, get_sudo_level, _resolve_path

# ========== 文件操作配额辅助 ==========




# ========== 常量 ==========

_LARGE_FILE_WARN = 50 * 1024
_ABSOLUTE_SIZE_CAP = 100 * 1024 * 1024


def _count_dir(path: str, max_depth: int = 1) -> tuple:
  items = 0
  size = 0
  base_depth = path.rstrip(os.sep).count(os.sep)
  try:
    for root, dirs, files in os.walk(path):
      depth = root.rstrip(os.sep).count(os.sep) - base_depth
      if depth < 0:
        depth = 0
      for f in files:
        items += 1
        try:
          size += os.path.getsize(os.path.join(root, f))
        except OSError:
          pass
      if depth >= max_depth:
        dirs.clear()
  except (PermissionError, OSError):
    pass
  return items, size


def read_file(path: str, offset: int = 0, limit: int = 0,
       tail: bool = False, lines: str = "") -> str:
  ok, reason = sandbox_check("read", path)
  if not ok:
    return f"错误: {reason}"
  # P0-12 附加修复：拒绝目录路径
  if os.path.isdir(path):
    return f"⚠ 路径是目录而非文件，请使用 scan_dir: {path}"

  budget_tokens = CONFIG.get("max_history_tokens", 1000000)
  ratio = CONFIG.get("char_to_token_ratio", 3.0)
  budget_chars = budget_tokens * ratio

  try:
    file_size = os.path.getsize(path)
  except OSError:
    file_size = 0

  if file_size > _ABSOLUTE_SIZE_CAP:
    return (
      f"✗ 文件过大（{fmt_size(file_size)}），超出绝对大小限制 "
      f"（{fmt_size(_ABSOLUTE_SIZE_CAP)}）\n"
      f" 建议使用 run_python 做流式处理，避免全量读入内存"
    )

  if file_size > budget_chars:
    return (
      f"✗ 文件太大（{fmt_size(file_size)}），超出当前上下文预算 "
      f"（{budget_tokens:,} tokens ≈ {fmt_size(int(budget_chars))}）\n"
      f"建议使用 find 搜索目标内容，或 /limit off 关闭裁剪后重试"
    )

  # 大文件只记录日志，不弹确认
  if file_size > budget_chars * 0.95:
    pct = file_size / budget_chars * 100
    max_tk = CONFIG.get("max_history_tokens", 1000000)
    _log.debug("大文件 %.1f%% 预算: %s / %s", pct, fmt_size(file_size), fmt_size(int(max_tk * 3.0)))

  if not os.path.isfile(path):
    return f"⚠ 不是常规文件，无法读取: {path}"

  try:
    with open(path, "r", encoding="utf-8") as f:
      content = f.read()
  except UnicodeDecodeError:
    return (f"⚠ 文件不是文本格式（UTF-8 解码失败）: {path}\n"
        f" 可用 run_python 配合 open('{os.path.basename(path)}', 'rb').read(32) 查看文件头字节")
  except Exception as e:
    return f"错误: 读取失败 - {e}"

  total_lines = content.count("\n") + 1
  file_lines = content.split("\n")

  # lines 参数优先：指定非连续行号，忽略 offset/limit/tail
  if lines.strip():
    try:
      requested = [int(x.strip()) for x in lines.split(",") if x.strip()]
    except ValueError:
      return f"错误: lines 参数格式无效，应为逗号分隔的数字，如 '3,7,15'"
    invalid = [n for n in requested if n < 1 or n > total_lines]
    if invalid:
      return f"错误: 行号超出范围 (1-{total_lines}): {invalid}"
    sliced = [file_lines[n - 1] for n in requested]
    content = "\n".join(sliced)
    if not content and sliced:
      content = "(空行)"
  elif tail and limit > 0:
    start = max(0, total_lines - limit)
    sliced = file_lines[start:start + limit]
    content = "\n".join(sliced)
    if not content and sliced:
      content = "(空行)"
    offset = start + 1 # 供 range_hint 标注实际行号
  elif offset > 0 or limit > 0:
    start = max(0, offset - 1) if offset > 0 else 0
    end = start + limit if limit > 0 else len(file_lines)
    sliced = file_lines[start:end]
    content = "\n".join(sliced)
    if not content and sliced:
      content = "(空行)"

  line_count = content.count("\n") + 1
  char_count = len(content)
  pct = char_count / budget_chars * 100 if budget_chars > 0 else 0
  range_hint = ""
  if lines.strip():
    range_hint = f" | 指定行: {lines} (全文件 {total_lines} 行)"
  elif offset > 0 or limit > 0:
    range_hint = f" | 范围: L{max(1, offset)}-L{max(1, offset) + line_count - 1} (全文件 {total_lines} 行)"
  info = (f"\n\n---\n 文件统计: {line_count} 行 | {fmt_size(char_count)} 字符 "
      f"| 占上下文预算 {pct:.1f}%{range_hint}")
  ws_ctx = _get_workspace_context(path)
  if ws_ctx:
    info += f" | 工作区: {ws_ctx['relative']}"
  if pct > 10:
    info += " ⚠"
  return content + info


def path_info(path: str) -> str:
  ok, reason = sandbox_check("read", path)
  if not ok:
    return f"错误: {reason}"
  try:
    if not os.path.exists(path):
      return f"路径不存在: {path}"
    st = os.stat(path)
    lines = []
    lines.append(f"路径: {path}")
    lines.append(f"类型: {' 目录' if os.path.isdir(path) else 'file 文件'}")
    lines.append(f"大小: {st.st_size:,} bytes")
    lines.append(f"权限: {stat.filemode(st.st_mode)}")
    lines.append(f"修改: {datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"创建: {datetime.fromtimestamp(st.st_ctime).strftime('%Y-%m-%d %H:%M:%S')}")
    return "\n".join(lines)
  except Exception as e:
    return f"错误: {e}"


def create_dir(path: str) -> str:
  ok, reason = sandbox_check("create", path)
  if not ok:
    return f"错误: {reason}"
  try:
    os.makedirs(path, exist_ok=True)
    return f"✓ 已创建目录: {path}"
  except Exception as e:
    return f"错误: {e}"


_MAX_WRITE_BYTES = 5 * 1024 * 1024

def write_file(path: str, content: str = "") -> str:
  ok, reason = sandbox_check("write", path)
  if not ok:
    return f"错误: {reason}"

  if len(content) > _MAX_WRITE_BYTES:
    return f"✗ 写入内容过大 ({len(content):,} 字符)，超过 {_MAX_WRITE_BYTES:,} 字符限制"

  try:
    original = ""
    existed = os.path.isfile(path)
    if existed:
      try:
        with open(path, "r", encoding="utf-8") as f:
          original = f.read()
      except Exception:
        pass
      # P0-12 修复：备份失败时中断写入，防止数据丢失
      backup = _backup_file(path)
      if backup is None:
        return "⚠ 原文件存在但备份失败，写入已取消以保护数据"

    action = "创建" if not existed else "覆盖写入"
    with open(path, "w", encoding="utf-8") as f:
      f.write(content)

    result = f"✓ 已{action} {len(content):,} 字符到: {path}"
    if existed and original != content:
      diff_text = _generate_diff(path, original, content)
      if diff_text:
        result += f"\n```diff\n{diff_text}\n```"
    return result
  except Exception as e:
    return f"错误: {e}"


def delete(path: str) -> str:
  ok, reason = sandbox_check("delete", path)
  if not ok:
    return f"错误: {reason}"

  try:
    if not os.path.exists(path):
      return f"路径不存在: {path}"
    import shutil
    if os.path.isdir(path):
      shutil.rmtree(path)
      result = f"✓ 已删除目录（含子文件）: {path}"
    else:
      os.remove(path)
      result = f"✓ 已删除文件: {path}"
    return result
  except Exception as e:
    return f"错误: {e}"


def rename(path: str, new_path: str) -> str:
  """移动/重命名文件或目录"""
  ok, reason = sandbox_check("write", path)
  if not ok:
    return f"错误: {reason}"
  ok2, reason2 = sandbox_check("create", new_path)
  if not ok2:
    return f"错误: {reason2}"

  try:
    if not os.path.exists(path):
      return f"路径不存在: {path}"
    if os.path.exists(new_path):
      return f"⚠ 目标已存在: {new_path}"
    resolved_new = _resolve_path(new_path)
    parent = os.path.dirname(resolved_new) or "."
    os.makedirs(parent, exist_ok=True)
    os.rename(path, new_path)
    src_type = "目录" if os.path.isdir(new_path) else "文件"
    result = f"✓ 已移动{src_type}: {path} → {new_path}"
    return result
  except OSError as e:
    # 跨设备移动回退到 shutil.move
    import shutil
    try:
      shutil.move(path, new_path)
      src_type = "目录" if os.path.isdir(new_path) else "文件"
      result = f"✓ 已移动{src_type}(跨设备): {path} → {new_path}"
      return result
    except Exception as e2:
      return f"错误: {e2}"
  except Exception as e:
    return f"错误: {e}"


def scan_dir(path: str, max_depth: int = 2, json_output: bool = False) -> str:
  ok, reason = sandbox_check("read", path)
  if not ok:
    return f"错误: {reason}"
  try:
    if not os.path.isdir(path):
      return f"⚠ 不是目录: {path}"

    items = sorted(os.listdir(path))
    total_items = 0
    total_size = 0
    children = []

    for item in items:
      full = os.path.join(path, item)
      if os.path.isdir(full):
        d_items, d_size = _count_dir(full, max_depth)
        total_items += d_items
        total_size += d_size
        children.append({
          "name": item, "type": "dir",
          "items": d_items, "size": d_size,
          "flag": "large" if d_items > 200 else None,
        })
      else:
        size = os.path.getsize(full)
        total_size += size
        children.append({
          "name": item, "type": "file",
          "size": size,
        })

    if json_output:
      import json
      return json.dumps({
        "path": path,
        "max_depth": max_depth,
        "direct_count": len(items),
        "total_items": total_items,
        "total_size": total_size,
        "children": children,
      }, ensure_ascii=False, indent=2)

    lines = [f" 扫描: {path}"]
    lines.append(f"深度: ≤{max_depth} 层 | 直接子项: {len(items)}\n")
    for c in children:
      if c["type"] == "dir":
        flag = " ⚠大目录" if c.get("flag") == "large" else ""
        lines.append(f" {c['name']}/ {c['items']} 项 ({fmt_size(c['size'])}){flag}")
      else:
        sz = c["size"]
        flag = " ⚠大文件" if sz > _LARGE_FILE_WARN else ""
        lines.append(f"file {c['name']} ({fmt_size(sz)}){flag}")
    lines.append(f"\n 合计: {total_items} 项，总大小 {fmt_size(total_size)}")
    return "\n".join(lines)

  except Exception as e:
    return f"错误: {e}"


def replace(path: str, old: str, new: str) -> str:
  ok, reason = sandbox_check("write", path)
  if not ok:
    return f"错误: {reason}"

  if not os.path.isfile(path):
    return f"⚠ 不是常规文件，无法读取: {path}"

  try:
    with open(path, "r", encoding="utf-8") as f:
      original = f.read()

    if not old:
      return "✗ 错误: 旧文本不能为空"
    if old not in original:
      return f"⚠ 未找到匹配文本，未作修改: {path}"

    if not _backup_file(path):
      return f"✗ 备份失败，拒绝写入: {path}"
    # P1-29 修复：改为全部替换，避免语义不一致
    new_content = original.replace(old, new)
    replace_count = (len(original) - len(new_content)) // max(len(old) - len(new), 1) if len(old) != len(new) else original.count(old)
    with open(path, "w", encoding="utf-8") as f:
      f.write(new_content)

    result = f"✓ 已替换 {replace_count} 处（全部替换），共 {len(old)} → {len(new)} 字符: {path}"
    diff_text = _generate_diff(path, original, new_content)
    if diff_text:
      result += f"\n```diff\n{diff_text}\n```"
    return result
  except Exception as e:
    return f"错误: {e}"


def _write_file_parser(raw: str) -> dict:
  import shlex
  parts = shlex.split(raw)
  if not parts:
    raise ValueError("格式: @write_file /路径 内容")
  return {"path": parts[0], "content": " ".join(parts[1:])}


def _replace_parser(raw: str) -> dict:
  import shlex
  parts = shlex.split(raw)
  if len(parts) < 3:
    raise ValueError("格式: @replace /路径 旧文本 新文本")
  return {"path": parts[0], "old": parts[1], "new": parts[2]}


def _find_parser(raw: str) -> dict:
  import shlex
  parts = shlex.split(raw)
  if not parts:
    raise ValueError("格式: @find /路径 [-c 内容] [-r] [-f '*.py'] [-C 2] [-i]")
  path = parts[0]
  rest = parts[1:]
  kwargs = {"path": path}
  i = 0
  while i < len(rest):
    if rest[i] == "-c" and i + 1 < len(rest):
      kwargs["pattern"] = rest[i + 1]
      kwargs["search_content"] = True
      i += 2
    elif rest[i] == "-r":
      kwargs["use_regex"] = True
      i += 1
    elif rest[i] == "-i":
      kwargs["ignore_case"] = True
      i += 1
    elif rest[i] == "-f" and i + 1 < len(rest):
      kwargs["file_pattern"] = rest[i + 1]
      i += 2
    elif rest[i] == "-C" and i + 1 < len(rest):
      try:
        kwargs["context"] = int(rest[i + 1])
      except ValueError:
        kwargs["context"] = 0
      i += 2
    else:
      if "pattern" not in kwargs:
        kwargs["pattern"] = rest[i]
      i += 1
  return kwargs


def _is_binary(path: str) -> bool:
  """检测文件是否为二进制（O_NONBLOCK 防卡死）"""
  _BINARY_EXTS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp",
    ".mp3", ".mp4", ".avi", ".mov", ".wav", ".flac", ".ogg", ".m4a",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".rar", ".7z",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".exe", ".dll", ".so", ".dylib", ".o", ".a", ".lib",
    ".pyc", ".pyo", ".whl",
    ".woff", ".woff2", ".ttf", ".eot",
    ".DS_Store",
  })
  _, ext = os.path.splitext(path)
  if ext.lower() in _BINARY_EXTS:
    return True
  try:
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
      chunk = os.read(fd, 1024)
    finally:
      os.close(fd)
    return b"\0" in chunk
  except Exception:
    return True


def find(path: str, pattern: str = "", search_content: bool = False,
     max_depth: int = 3, max_results: int = 30,
     use_regex: bool = False, file_pattern: str = "",
     ignore_case: bool = False, context: int = 0) -> str:
  ok, reason = sandbox_check("read", path)
  if not ok:
    return f"错误: {reason}"
  if not os.path.isdir(path):
    return f"⚠ 不是目录: {path}"

  import fnmatch
  import re as _re
  results = []
  skipped_dirs = []

  _re_flags = _re.IGNORECASE if ignore_case else 0
  _re_obj = _re.compile(pattern, _re_flags) if use_regex and pattern else None

  def _match_line(line: str) -> bool:
    if _re_obj:
      return bool(_re_obj.search(line))
    if ignore_case:
      return pattern.lower() in line.lower()
    return pattern in line

  for root, dirs, files in os.walk(path):
    rel = os.path.relpath(root, path)
    depth = 0 if rel == "." else rel.count(os.sep) + 1
    if depth >= max_depth:
      dirs.clear()
      continue

    if len(files) + len(dirs) > 1000 and depth > 0:
      skipped_dirs.append(root)
      dirs.clear()
      continue

    if not search_content and pattern:
      for f in files:
        if file_pattern and not fnmatch.fnmatch(f, file_pattern):
          continue
        if fnmatch.fnmatch(f, pattern):
          full = os.path.join(root, f)
          size = os.path.getsize(full)
          results.append(f"file {full} ({fmt_size(size)})")
          if len(results) >= max_results:
            break
      for d in dirs:
        if file_pattern and not fnmatch.fnmatch(d, file_pattern):
          continue
        if fnmatch.fnmatch(d, pattern):
          results.append(f" {os.path.join(root, d)}/")
          if len(results) >= max_results:
            break

    elif search_content and pattern:
      for f in files:
        full = os.path.join(root, f)
        if file_pattern and not fnmatch.fnmatch(f, file_pattern):
          continue
        if _is_binary(full):
          continue
        try:
          with open(full, "r", encoding="utf-8", errors="replace") as fh:
            all_lines = fh.readlines()
        except Exception:
          continue

        match_indices = []
        for i, ln in enumerate(all_lines):
          if _match_line(ln):
            match_indices.append(i)
        if not match_indices:
          continue

        matched_lines = []
        for idx in match_indices[:5]:
          start = max(0, idx - context)
          end = min(len(all_lines), idx + context + 1)
          for j in range(start, end):
            prefix = ">" if j == idx else " "
            matched_lines.append(f"{prefix} L{j+1}: {all_lines[j].rstrip()[:120]}")

        _MAX_DISPLAY = 30
        truncated = len(matched_lines) > _MAX_DISPLAY
        if truncated:
          matched_lines = matched_lines[:_MAX_DISPLAY]

        label = f"file {full} ({len(match_indices)} 处匹配"
        if truncated:
          label += "，已截断"
        label += ")"
        results.append(label)
        results.extend(matched_lines)

        if len(results) >= max_results:
          break

    elif not pattern:
      for f in files:
        if file_pattern and not fnmatch.fnmatch(f, file_pattern):
          continue
        full = os.path.join(root, f)
        size = os.path.getsize(full)
        results.append(f"file {full} ({fmt_size(size)})")
        if len(results) >= max_results:
          break
      for d in dirs:
        if file_pattern and not fnmatch.fnmatch(d, file_pattern):
          continue
        results.append(f" {os.path.join(root, d)}/")
        if len(results) >= max_results:
          break

    if len(results) >= max_results:
      break

  lines_out = [f"? 查找: {path}"]
  if pattern:
    mode = "内容" if search_content else "名称"
    extra = ""
    if use_regex:
      extra += " 正则"
    if ignore_case:
      extra += " 忽略大小写"
    lines_out.append(f"模式: {mode}匹配 \"{pattern}\"{extra} | 深度: ≤{max_depth}")
  lines_out.append(f"结果: {len(results)} 项（上限 {max_results}）\n")
  lines_out.extend(results[:max_results])

  if skipped_dirs:
    lines_out.append(f"\n⚠ 跳过大目录: {len(skipped_dirs)} 个（>1000 文件）")
    for sd in skipped_dirs[:5]:
      lines_out.append(f"  {sd}")
    if len(skipped_dirs) > 5:
      lines_out.append(f"  ...等 {len(skipped_dirs)} 个")

  return "\n".join(lines_out)
def grep_symbol(path: str, symbol_type: str = "", symbol_name: str = "") -> str:
  ok, reason = sandbox_check("read", path)
  if not ok:
    return f"错误: {reason}"
  if not os.path.isfile(path):
    return f"⚠ 不是文件: {path}"
  if not path.endswith(".py"):
    return f"⚠ 仅支持 Python 文件 (.py): {path}"

  import ast
  if not os.path.isfile(path):
    return f"⚠ 不是常规文件，无法读取: {path}"

  try:
    with open(path, "r", encoding="utf-8") as f:
      source = f.read()
    tree = ast.parse(source)
  except Exception as e:
    return f"错误: 解析失败 - {e}"

  results = []
  sym_type_filter = symbol_type.lower() if symbol_type else ""
  sym_name_filter = symbol_name.lower() if symbol_name else ""

  for node in ast.walk(tree):
    name = None
    node_type = None
    line = 0

    if isinstance(node, ast.ClassDef):
      node_type = "class"
      name = node.name
      line = node.lineno
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
      node_type = "function"
      name = node.name
      line = node.lineno
    elif isinstance(node, ast.AnnAssign):
      if isinstance(node.target, ast.Name):
        node_type = "var"
        name = node.target.id
        line = node.lineno
    elif isinstance(node, ast.Assign):
      node_type = "var"
      for target in node.targets:
        if isinstance(target, ast.Name):
          name = target.id
          line = node.lineno
          break

    if name is None:
      continue

    if sym_type_filter and node_type != sym_type_filter:
      continue
    if sym_name_filter and sym_name_filter not in name.lower():
      continue

    results.append(f"  [{node_type}] {name} (L{line})")

  if not results:
    parts = [f"? 未找到符号: {path}"]
    if symbol_type:
      parts.append(f"类型={symbol_type}")
    if symbol_name:
      parts.append(f"名称~={symbol_name}")
    return " | ".join(parts)

  return f"? 符号列表: {path} ({len(results)} 个)\n" + "\n".join(results)


def paste() -> str:
  import subprocess
  try:
    result = subprocess.run(
      ["termux-clipboard-get"],
      capture_output=True, text=True, timeout=10
    )
    if result.returncode != 0:
      return f"错误: 读取剪贴板失败: {result.stderr.strip()}"
    text = result.stdout
    if not text:
      return "剪贴板为空"
    preview = text[:500]
    if len(text) > 500:
      preview += f"\n... (共 {len(text)} 字符，已截断)"
    return f"剪贴板内容 ({len(text)} 字符):\n{preview}"
  except Exception as e:
    return f"错误: 读取剪贴板时异常: {e}"


def _grep_symbol_parser(raw: str) -> dict:
  import shlex
  parts = shlex.split(raw)
  if not parts:
    raise ValueError("格式: @grep_symbol /路径 [类型] [名称]")
  result = {"path": parts[0]}
  if len(parts) >= 2:
    result["symbol_type"] = parts[1]
  if len(parts) >= 3:
    result["symbol_name"] = parts[2]
  return result
