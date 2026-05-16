# utils/parser.py - 多语言符号解析（可选 tree-sitter 集成）
"""tree-sitter 不可用时，回退到纯文本正则或 AST。"""
import os


def find_symbols(path: str, lang: str, symbol_type: str = "", symbol_name: str = "") -> list[dict]:
  """统一符号查找接口。tree-sitter 可用时走精确解析，否则回退 AST/正则。"""
  try:
    return _find_with_treesitter(path, lang, symbol_type, symbol_name)
  except ImportError:
    pass
  except Exception as e:
    import logging
    logging.getLogger("tiao").debug("tree-sitter 解析失败 (%s)，回退正则: %s", lang, e)
  if lang == "python":
    return _find_python_ast(path, symbol_type, symbol_name)
  return _find_regex(path, lang, symbol_type, symbol_name)


_TREESITTER_LIB = os.environ.get(
  "TREESITTER_LIB_PATH",
  "/data/data/com.termux/files/usr/lib/tree-sitter/languages.so"
)


def _find_with_treesitter(path: str, lang: str, symbol_type: str, symbol_name: str) -> list[dict]:
  try:
    from tree_sitter import Language, Parser
    parser = Parser()
    parser.set_language(Language(_TREESITTER_LIB, lang))
    with open(path, "r", encoding="utf-8") as f:
      source = f.read()
    tree = parser.parse(bytes(source, "utf-8"))
    return _traverse_tree(tree.root_node, source, symbol_type, symbol_name)
  except ImportError:
    raise


def _traverse_tree(node, source: str, symbol_type: str, symbol_name: str, depth: int = 0) -> list[dict]:
  results = []
  if depth > 20:
    return results
  mapping = {
    "function": ("function_definition", "method_definition"),
    "class": ("class_definition",),
    "var": ("assignment",),
  }
  targets = mapping.get(symbol_type, ())
  if node.type in targets or not targets:
    name_node = node.child_by_field_name("name")
    if name_node:
      name = source[name_node.start_byte:name_node.end_byte]
      if not symbol_name or symbol_name.lower() in name.lower():
        results.append({"name": name, "type": node.type, "line": node.start_point[0] + 1})
  for child in node.children:
    results.extend(_traverse_tree(child, source, symbol_type, symbol_name, depth + 1))
  return results


def _find_python_ast(path: str, symbol_type: str, symbol_name: str) -> list[dict]:
  import ast
  with open(path, "r", encoding="utf-8") as f:
    source = f.read()
  tree = ast.parse(source)
  results = []
  for node in ast.walk(tree):
    name = lineno = ntype = None
    if isinstance(node, ast.FunctionDef):
      name, ntype, lineno = node.name, "function", node.lineno
    elif isinstance(node, ast.ClassDef):
      name, ntype, lineno = node.name, "class", node.lineno
    elif isinstance(node, ast.Assign):
      for t in node.targets:
        if isinstance(t, ast.Name):
          name, ntype, lineno = t.id, "var", node.lineno
          break
    if name and (not symbol_type or symbol_type in ntype):
      if not symbol_name or symbol_name.lower() in name.lower():
        results.append({"name": name, "type": ntype, "line": lineno})
  return results


def _find_regex(path: str, lang: str, symbol_type: str, symbol_name: str) -> list[dict]:
  patterns = {
    "python": {"function": r"^\s*def\s+(\w+)", "class": r"^\s*class\s+(\w+)"},
    "rust": {"function": r"^\s*(?:pub\s+)?fn\s+(\w+)", "struct": r"^\s*(?:pub\s+)?struct\s+(\w+)"},
    "go": {"function": r"^\s*func\s+(?:\(.*\)\s+)?(\w+)", "struct": r"^\s*type\s+(\w+)\s+struct"},
    "javascript": {"function": r"(?:function\s+(\w+)|(\w+)\s*=\s*(?:async\s*)?\(|(\w+)\s*:\s*function)"},
  }
  import re
  lang_patterns = patterns.get(lang, patterns.get("python", {}))
  results = []
  with open(path, "r", encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
      for stype, pattern in lang_patterns.items():
        m = re.match(pattern, line)
        if m:
          name = next((g for g in m.groups() if g), "")
          if not symbol_name or symbol_name.lower() in name.lower():
            if not symbol_type or symbol_type == stype:
              results.append({"name": name, "type": stype, "line": i})
  return results
