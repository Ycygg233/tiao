"""tools/search_web.py — 搜索工具（支持多平台扩展）

内置平台：
 metaso — 秘塔搜索（搜索+积分制）
 tavily — Tavily AI 搜索（搜索+抓取，depth: basic/advanced）

扩展方式：实现搜索函数 → register_search_provider() 注册
"""

import os
import json
import logging
from dataclasses import dataclass, field

import requests

log = logging.getLogger("tiao.tools.search")

_SEARCH_ENDPOINT = "https://metaso.cn/api/v1/search"
_TAVILY_SEARCH_ENDPOINT = "https://api.tavily.com/search"
_TAVILY_EXTRACT_ENDPOINT = "https://api.tavily.com/extract"


# ── 统一数据模型 ──

@dataclass
class SearchResult:
  title: str
  url: str = ""
  snippet: str = ""
  source: str = ""
  date: str = ""
  score: str = ""
  authors: list = field(default_factory=list)


# ── 搜索平台注册表（预留多平台扩展） ──

_SEARCH_PROVIDERS: dict[str, callable] = {}

def register_search_provider(name: str, fn):
  """注册搜索平台。
  fn 签名: (q, scope, size, **kwargs) → (list[SearchResult], meta_dict)
  """
  _SEARCH_PROVIDERS[name] = fn

def get_search_provider(name: str):
  return _SEARCH_PROVIDERS.get(name)


# ── 秘塔搜索实现 ──

def _search_metaso(q, scope="webpage", size=5, include_summary=False,
          include_raw=False, concise=True):
  """调用秘塔搜索 API"""
  api_key = os.environ.get("metaso_api_key", "")
  if not api_key:
    raise ValueError("未设置 metaso_api_key")

  body = {
    "q": q.strip(), "scope": scope,
    "includeSummary": include_summary, "size": str(size),
    "includeRawContent": include_raw, "conciseSnippet": concise,
  }

  resp = requests.post(_SEARCH_ENDPOINT,
    headers={"Authorization": f"Bearer {api_key}",
         "Accept": "application/json",
         "Content-Type": "application/json"},
    json=body, timeout=30)
  resp.raise_for_status()
  data = resp.json()

  raw_list = data.get("webpages", data.get("data", data.get("results", [])))
  results = []
  for item in raw_list:
    results.append(SearchResult(
      title=item.get("title", "(无标题)"),
      url=item.get("link", item.get("url", "")),
      snippet=item.get("snippet", item.get("summary", item.get("content", ""))),
      source=item.get("source", item.get("site", "")),
      date=item.get("date", ""),
      score=item.get("score", ""),
      authors=item.get("authors", []),
    ))
  return results, {"credits": data.get("credits", 0)}


# ── Tavily 搜索实现 ──

def _search_tavily(q, scope="webpage", size=5, depth="basic", **kwargs):
  """调用 Tavily Search API"""
  api_key = os.environ.get("tavily_api_key", "")
  if not api_key:
    raise ValueError("未设置 tavily_api_key")

  body = {
    "api_key": api_key,
    "query": q.strip(),
    "search_depth": depth,
    "max_results": size,
    "include_answer": True,
  }

  resp = requests.post(_TAVILY_SEARCH_ENDPOINT, json=body, timeout=30)
  resp.raise_for_status()
  data = resp.json()

  raw_list = data.get("results", [])
  results = []
  for item in raw_list:
    results.append(SearchResult(
      title=item.get("title", "(无标题)"),
      url=item.get("url", ""),
      snippet=item.get("content", ""),
      source="tavily",
      date=item.get("published_date", ""),
      score=str(item.get("score", "")),
    ))

  meta = {}
  answer = data.get("answer", "")
  if answer:
    meta["answer"] = answer
  return results, meta


def _extract_tavily(urls, depth="basic"):
  """调用 Tavily Extract API 抓取指定 URL"""
  api_key = os.environ.get("tavily_api_key", "")
  if not api_key:
    raise ValueError("未设置 tavily_api_key")

  if isinstance(urls, str):
    urls = [urls]

  body = {
    "api_key": api_key,
    "urls": urls,
    "extract_depth": depth,
  }

  resp = requests.post(_TAVILY_EXTRACT_ENDPOINT, json=body, timeout=60)
  resp.raise_for_status()
  data = resp.json()

  raw_list = data.get("results", [])
  results = []
  for item in raw_list:
    results.append(SearchResult(
      title=item.get("url", "(无标题)"),
      url=item.get("url", ""),
      snippet=item.get("content", item.get("raw_content", "")),
      source="tavily_extract",
    ))
  return results, {"failed": data.get("failed_urls", [])}


# ── Jina AI 搜索实现 ──

def _parse_jina_markdown(text: str, fallback_title: str) -> list:
  """解析 Jina 返回的 Markdown 格式结果为结构化 SearchResult"""
  results = []
  import re as _re
  for m in _re.finditer(r'^## \[(.+?)\]\((.+?)\)\s*$(.+?)(?=^## |\Z)', text, _re.M | _re.DOTALL):
    title = m.group(1).strip()
    url = m.group(2).strip()
    snippet = _re.sub(r'\s+', ' ', m.group(3).strip())[:300]
    results.append(SearchResult(title=title, url=url, snippet=snippet, source="jina"))
  if not results:
    results.append(SearchResult(title=fallback_title, snippet=text[:2000], source="jina"))
  return results


def _search_jina(q, scope="webpage", size=5, **kwargs):
  """调用 Jina Search API (s.jina.ai)"""
  import urllib.parse
  api_key = os.environ.get("jina_api_key", "")
  if not api_key:
    raise ValueError("未设置 jina_api_key")

  resp = requests.get(
    f"https://s.jina.ai/{urllib.parse.quote(q.strip(), safe='')}",
    headers={
      "Authorization": f"Bearer {api_key}",
      "Accept": "application/json",
      "User-Agent": "Mozilla/5.0 (Linux; Android 14)",
    },
    timeout=30,
  )
  resp.raise_for_status()

  content_type = resp.headers.get("Content-Type", "")
  if "application/json" in content_type or resp.text.strip().startswith("{"):
    try:
      data = resp.json()
    except (json.JSONDecodeError, ValueError):
      return _parse_jina_markdown(resp.text, q), {}
    if isinstance(data, str):
      return _parse_jina_markdown(data, q), {}
    raw_list = []
    if isinstance(data, dict):
      raw_list = data.get("data", data.get("results", []))
    results = []
    for item in raw_list:
      if isinstance(item, dict):
        results.append(SearchResult(
          title=item.get("title", item.get("url", "(无标题)")),
          url=item.get("url", ""),
          snippet=item.get("description", item.get("content", item.get("snippet", ""))),
          source="jina",
        ))
      elif isinstance(item, str):
        results.append(SearchResult(title=item, source="jina"))
    return results, {}
  else:
    results = _parse_jina_markdown(resp.text, q)
    return results, {}


def _fetch_jina(url, **kwargs):
  """调用 Jina Reader API (r.jina.ai) 抓取网页"""
  api_key = os.environ.get("jina_api_key", "")
  if not api_key:
    raise ValueError("未设置 jina_api_key")

  # SSRF 防护：仅允许 HTTP/HTTPS，DNS 解析防内网
  if not url.lower().startswith(("http://", "https://")):
    raise ValueError(f"仅支持 HTTP/HTTPS URL: {url}")
  from urllib.parse import urlparse
  import ipaddress
  hostname = urlparse(url).hostname
  if hostname:
    try:
      ip = ipaddress.ip_address(hostname)
      if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_multicast:
        raise ValueError(f"禁止访问内网地址: {url}")
    except ValueError:
      pass

  resp = requests.get(
    f"https://r.jina.ai/{url}",
    headers={
      "Authorization": f"Bearer {api_key}",
      "Accept": "application/json",
      "User-Agent": "Mozilla/5.0 (Linux; Android 14)",
    },
    timeout=60,
  )
  resp.raise_for_status()

  text = resp.text
  # 提取标题
  title = url
  for prefix in ["Title: ", "# ", "title: "]:
    for line in text.split("\n"):
      if line.strip().startswith(prefix):
        title = line.strip()[len(prefix):]
        break

  return [SearchResult(
    title=title,
    url=url,
    snippet=text[:3000],
    source="jina_reader",
  )], {}


# ── Bocha AI 搜索实现 ──

_BOCHA_WEB_SEARCH = "https://api.bochaai.com/v1/web-search"
_BOCHA_AI_SEARCH = "https://api.bochaai.com/v1/ai-search"


def _extract_bocha_results(data: dict) -> list:
  webpages = data.get("webPages") or data.get("webPages", {}).get("value", [])
  if isinstance(webpages, dict):
    return webpages.get("value", [])
  if isinstance(webpages, list):
    return webpages
  return (data.get("data", {}).get("webPages", {}).get("value", []))


def _search_bocha(q, scope="webpage", size=5, summary=True, freshness="", **kwargs):
  """调用 Bocha Search API（web-search + ai-search）"""
  api_key = os.environ.get("bocha_api_key", "")
  if not api_key:
    raise ValueError("未设置 bocha_api_key")

  # 先尝试 ai-search（功能更全面），回退 web-search
  endpoints = [
    (_BOCHA_AI_SEARCH, {"query": q.strip(), "count": size, "answer": True}),
    (_BOCHA_WEB_SEARCH, {"query": q.strip(), "count": size, "summary": summary}),
  ]

  if freshness:
    for i in range(len(endpoints)):
      endpoints[i][1]["freshness"] = freshness

  last_error = None
  data = None
  for url, payload in endpoints:
    try:
      resp = requests.post(
        url,
        headers={
          "Authorization": f"Bearer {api_key}",
          "Content-Type": "application/json",
        },
        json=payload,
        timeout=15,
      )
      if resp.status_code >= 400:
        last_error = f"HTTP {resp.status_code}"
        continue
      resp.raise_for_status()
      data = resp.json()
      if not data or not isinstance(data, dict):
        last_error = "空响应"
        continue
      break
    except (requests.RequestException, json.JSONDecodeError) as e:
      last_error = e
      continue

  if data is None:
    raise last_error or ValueError("Bocha API 调用失败")

  raw_list = _extract_bocha_results(data)
  if not raw_list:
    raise ValueError("无搜索结果")

  results = []
  for item in raw_list:
    if isinstance(item, dict):
      results.append(SearchResult(
        title=item.get("name", item.get("title", "(无标题)")),
        url=item.get("url", ""),
        snippet=item.get("snippet") or item.get("summary", ""),
        source="bocha",
        date=item.get("datePublished", item.get("date", "")),
      ))

  meta = {}
  if isinstance(data, dict):
    answer = data.get("answer", "") or data.get("data", {}).get("answer", "")
    if answer:
      meta["answer"] = answer

  return results, meta


# ── 统一格式化（控制上下文占用） ──

def _format_results(q, scope, results, concise=True, max_chars=2000, credits=0):
  """格式化搜索结果，到达 max_chars 后自动截断，防止撑爆上下文"""
  lines = []
  total = 0

  def add(line):
    nonlocal total
    lines.append(line)
    total += len(line)

  header = f"? 搜索「{q}」（{scope}）共 {len(results)} 条"
  if credits:
    header += f" · 消耗 {credits} 积分"
  header += "："
  add(header)

  for i, r in enumerate(results, 1):
    if total >= max_chars:
      add(f"\n... 已达输出上限（{max_chars} 字符），省略 {len(results)-i+1} 条")
      break

    if concise:
      # 精简模式：两行一条
      snippet = r.snippet[:100].replace("\n", " ").strip()
      line = f" {i}. **{r.title}**"
      if snippet:
        line += f" — {snippet}"
      add(line)
      add(f"   → {r.url[:100]}")
    else:
      # 完整模式：多行含元数据
      add(f" {i}. **{r.title}**")
      if r.url:
        add(f"   → {r.url}")
      if r.snippet:
        add(f"   file {r.snippet[:200]}")
      meta = []
      if r.source:  meta.append(f" {r.source}")
      if r.date:   meta.append(f" {r.date}")
      if r.score:  meta.append(f" {r.score}")
      if r.authors: meta.append(f" {', '.join(r.authors[:2])}")
      if meta:
        add(f"   {' · '.join(meta)}")
      add("")

  add(f"\n 共 {len(results)} 条 · 输出 {total} 字符")
  return "\n".join(lines)


# ── 统一入口 ──

def search_web(q: str = "",
        scope: str = "webpage",
        size: int = 5,
        include_summary: bool = False,
        include_raw: bool = False,
        concise: bool = True,
        max_chars: int = 2000,
        provider: str = "metaso",
        depth: str = "basic",
        fetch_urls: str = "",
        freshness: str = "") -> str:
  """搜索网页，返回结构化结果。

  参数:
    q: 搜索关键词（必填，fetch_urls 模式可选）
    scope: metaso 专用: webpage | news | weixin
    size: 返回结果数 1-20，默认 5
    include_summary: metaso 专用: 是否包含完整句子摘要
    include_raw: metaso 专用: 是否包含原始内容
    concise: 精简输出，每个结果 2 行（默认 true）
    max_chars: 输出字符上限（默认 2000）
    provider: metaso(默认) | tavily | jina | bocha
    depth: tavily 专用: basic | advanced（默认 basic）
    fetch_urls: tavily/jina 专用: 抓取模式，传入 URL（逗号分隔）
    freshness: bocha 专用: 时间过滤，oneDay | oneWeek | oneMonth | oneYear
  """
  max_chars = max(500, min(10000, int(max_chars)))
  size = max(1, min(20, int(size)))

  try:
    if provider == "tavily":
      if fetch_urls:
        urls = [u.strip() for u in fetch_urls.split(",") if u.strip()]
        if not urls:
          return "错误: fetch_urls 为空"
        results, meta = _extract_tavily(urls, depth)
        label = f"tavily 抓取 {len(urls)} 个 URL"
      else:
        if not q or not q.strip():
          return "错误: 搜索关键词不能为空"
        results, meta = _search_tavily(q, scope, size, depth)
        label = f"tavily({depth})「{q.strip()}」"
      credits = 0
      scope_display = label

    elif provider == "jina":
      if fetch_urls:
        urls = [u.strip() for u in fetch_urls.split(",") if u.strip()]
        if not urls:
          return "错误: fetch_urls 为空"
        results, meta = _fetch_jina(urls[0])
        label = f"jina 抓取 {urls[0]}"
      else:
        if not q or not q.strip():
          return "错误: 搜索关键词不能为空"
        results, meta = _search_jina(q, scope, size)
        label = f"jina「{q.strip()}」"
      credits = 0
      scope_display = label

    elif provider == "bocha":
      if not q or not q.strip():
        return "错误: 搜索关键词不能为空"
      results, meta = _search_bocha(q, scope, size, freshness=freshness)
      label = f"bocha「{q.strip()}」"
      credits = 0
      scope_display = label

    elif provider == "metaso" or not provider:
      if not q or not q.strip():
        return "错误: 搜索关键词不能为空"
      if scope not in ("webpage", "news", "weixin"):
        scope = "webpage"
      results, meta = _search_metaso(
        q, scope, size, include_summary, include_raw, concise)
      credits = meta.get("credits", 0)
      scope_display = scope

    else:
      if not q or not q.strip():
        return "错误: 搜索关键词不能为空"
      fn = get_search_provider(provider)
      if not fn:
        return f"✗ 未知搜索平台: {provider}，可用: metaso, tavily, jina, bocha"
      results, meta = fn(q=q, scope=scope, size=size, depth=depth)
      credits = 0
      scope_display = scope

  except ValueError as e:
    hint = {
      "metaso": "./provider-key.sh set metaso <key>",
      "tavily": "./provider-key.sh set tavily <key>",
      "jina":  "./provider-key.sh set jina <key>",
      "bocha": "./provider-key.sh set bocha <key>",
    }.get(provider, f"请配置 {provider}_api_key 环境变量")
    return f"错误: {e}\n {hint}"
  except requests.exceptions.RequestException as e:
    detail = ""
    if hasattr(e, "response") and e.response is not None:
      detail = f" ({e.response.status_code}) {e.response.text[:200]}"
    return f"✗ 搜索失败: {e}{detail}"
  except json.JSONDecodeError:
    return "✗ 搜索 API 返回了非 JSON 响应"
  except Exception as e:
    return f"✗ {provider} 搜索失败: {e}"

  if not results:
    return "? 未找到相关结果"

  result = _format_results(q if q else fetch_urls, scope_display,
               results, concise, max_chars, credits)

  # AI answer 附加在开头（tavily / bocha 支持）
  if provider in ("tavily", "bocha") and not fetch_urls:
    answer = meta.get("answer", "") if isinstance(meta, dict) else ""
    if answer:
      result = f"AI AI 摘要：{answer[:500]}\n\n{result}"

  return result
