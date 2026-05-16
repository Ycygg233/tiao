"""tools/local_search.py — 本地搜索工具（免费，多源聚合+缓存）

搜索源分层（按成本）：
 L1 cache — 本地缓存 Documents/search_cache/*.md，零成本
 L2 web  — DuckDuckGo Lite 免费搜索（无需 API key，仅流量）
 L3 fetch — 直接抓取指定 URL 提取文本

结果自动缓存，相同关键词下次直接读缓存，零成本。
付费 API 搜索（秘塔等）请用 @search，建议通过子 agent 调用。
"""

import os
import re
import json
import hashlib
import logging
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

import requests

from config import DATA_DIR

log = logging.getLogger("tiao.tools.local_search")

CACHE_DIR = os.path.join(DATA_DIR, "search_cache")
_DDG_ENDPOINT = "https://lite.duckduckgo.com/lite/"

# ========== 统一数据模型 ==========

@dataclass
class SearchResult:
  title: str
  url: str = ""
  snippet: str = ""
  source: str = "" # cache / web / fetch


# ========== 缓存管理 ==========

def _cache_path(query: str) -> str:
  """根据查询词生成唯一缓存路径"""
  h = hashlib.md5(query.encode()).hexdigest()[:12]
  safe = re.sub(r'[^\w\u4e00-\u9fff]', '_', query)[:20]
  return os.path.join(CACHE_DIR, f"{safe}_{h}.md")


def _read_cache(filepath: str) -> Optional[str]:
  """读取缓存，检查是否在有效期内（默认 24h）"""
  if not os.path.isfile(filepath):
    return None
  try:
    mtime = os.path.getmtime(filepath)
    age = datetime.now().timestamp() - mtime
    if age > 86400: # 24 小时过期
      return None
    with open(filepath, "r", encoding="utf-8") as f:
      return f.read()
  except Exception:
    return None


def _write_cache(filepath: str, query: str, results: list[SearchResult],
         source: str, elapsed: float):
  """将搜索结果写入缓存 md 文件（带 front matter）"""
  os.makedirs(os.path.dirname(filepath), exist_ok=True)

  lines = [
    "---",
    f"query: {query}",
    f"date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    f"source: {source}",
    f"results: {len(results)}",
    f"elapsed: {elapsed:.1f}s",
    "---",
    "",
    f"## 搜索结果：{query}",
    "",
  ]
  for i, r in enumerate(results, 1):
    lines.append(f"### {i}. {r.title}")
    if r.snippet:
      lines.append(f"{r.snippet}")
    if r.url:
      lines.append(f"→ {r.url}")
    lines.append(f"*来源: {r.source}*")
    lines.append("")

  content = "\n".join(lines)
  with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)
  return content


# ========== L1：缓存搜索 ==========

def _search_cache(query: str, max_results: int = 5) -> list[SearchResult]:
  """在缓存目录中搜索匹配的历史结果"""
  results = []
  if not os.path.isdir(CACHE_DIR):
    return results

  keywords = query.lower().split()
  for fname in os.listdir(CACHE_DIR):
    if not fname.endswith(".md"):
      continue
    fpath = os.path.join(CACHE_DIR, fname)
    try:
      with open(fpath, "r", encoding="utf-8") as f:
        content = f.read()
      if all(kw in content.lower() for kw in keywords):
        # 从 front matter 取元数据
        title_match = re.search(r'^query:\s*(.+)', content, re.M)
        title = title_match.group(1) if title_match else fname
        snippet = content[:300].replace("\n", " ").strip()
        results.append(SearchResult(
          title=title,
          snippet=snippet,
          source="cache",
          url=f"file://{fpath}",
        ))
    except Exception:
      continue

  return results[:max_results]


# ========== L2：DuckDuckGo 免费搜索 ==========

def _parse_ddg_html(html: str, max_results: int = 5) -> list[SearchResult]:
  results = []
  rows = re.findall(
    r'(?:<tr[^>]*>.*?)?<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
    r'(?:<td[^>]*class="[^"]*result-snippet[^"]*"[^>]*>(.*?)</td>)?',
    html, re.DOTALL
  )

  seen_urls = set()
  for url, raw_title, raw_snippet in rows:
    url = url.strip()
    if not url or url == "https://duckduckgo.com":
      continue
    if url.startswith("//"):
      url = "https:" + url
    elif url.startswith("/"):
      url = "https://duckduckgo.com" + url
    if url in seen_urls:
      continue
    seen_urls.add(url)
    title = re.sub(r'<[^>]+>', '', raw_title).strip()
    snippet = re.sub(r'<[^>]+>', '', raw_snippet).strip() if raw_snippet else ""
    if not title and not snippet:
      continue
    results.append(SearchResult(
      title=title or "(无标题)", url=url,
      snippet=snippet[:200], source="web"
    ))
    if len(results) >= max_results:
      break

  if not results:
    from urllib.parse import urlparse, urlunparse
    for m in re.finditer(r'<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>', html):
      url = m.group(1)
      if url in seen_urls:
        continue
      seen_urls.add(url)
      title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
      if not title:
        continue
      after = html[m.end():m.end() + 300]
      snip_m = re.search(r'<td[^>]*class="[^"]*snippet[^"]*"[^>]*>(.*?)</td>', after, re.DOTALL)
      snippet = re.sub(r'<[^>]+>', '', snip_m.group(1)).strip() if snip_m else ""
      results.append(SearchResult(title=title, url=url, snippet=snippet[:200], source="web"))
      if len(results) >= max_results:
        break

  return results


def _search_ddg(query: str, max_results: int = 5) -> list[SearchResult]:
  """DuckDuckGo Lite 免费搜索（无需 API key）"""
  try:
    resp = requests.post(
      _DDG_ENDPOINT,
      data={"q": query.strip()},
      headers={
        "User-Agent": "Mozilla/5.0 (Linux; Android 14) "
               "AppleWebKit/537.36 (KHTML, like Gecko)",
      },
      timeout=15,
    )
    resp.raise_for_status()
    results = _parse_ddg_html(resp.text, max_results)
    log.debug("DDG 搜索 '%s' 返回 %d 条", query[:20], len(results))
    return results
  except requests.RequestException as e:
    log.warning("DDG 搜索失败: %s", e)
    return []


# ========== L3：网页抓取 ==========

def _fetch_url(url: str, max_chars: int = 2000) -> Optional[SearchResult]:
  """抓取 URL 并提取文本内容"""
  if not url.lower().startswith(("http://", "https://")):
    log.warning("禁止非 HTTP/HTTPS URL: %s", url)
    return None
  from urllib.parse import urlparse
  import ipaddress
  hostname = urlparse(url).hostname
  if hostname:
    try:
      ip = ipaddress.ip_address(hostname)
      if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
        log.warning("禁止内网/保留 IP: %s (%s)", url, ip)
        return None
    except ValueError:
      try:
        import socket
        resolved = socket.getaddrinfo(hostname, None)
        for family, _, _, _, sockaddr in resolved:
          ip = ipaddress.ip_address(sockaddr[0])
          if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            log.warning("禁止内网地址: %s → %s", hostname, ip)
            return None
      except (socket.gaierror, OSError) as e:
        log.warning("DNS 解析失败 %s: %s", hostname, e)
        return None
  try:
    resp = requests.get(
      url,
      headers={"User-Agent": "Mozilla/5.0 (Linux; Android 14)"},
      timeout=15,
    )
    resp.raise_for_status()
    html = resp.text

    # 提取标题
    title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.I | re.DOTALL)
    title = title_match.group(1).strip() if title_match else url

    # 提取正文（去除 script/style 标签）
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.I)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = text[:max_chars]

    return SearchResult(
      title=title,
      url=url,
      snippet=text,
      source="fetch",
    )
  except requests.RequestException as e:
    log.warning("抓取失败 %s: %s", url, e)
    return None


# ========== 入口 ==========

def local_search(q: str = "",
         scope: str = "auto",
         max_results: int = 5,
         fetch_url: str = "",
         refresh: bool = False) -> str:
  """本地搜索（免费，多源聚合+缓存）。

  搜索源：
   cache — 本地缓存（零成本，秒回）
   web  — DuckDuckGo 免费搜索（仅流量，可能几秒）
   fetch — 抓取指定 URL 提取文本
   all  — cache → web 逐级尝试（愿意等几秒用这个）
   auto — 仅查缓存，未命中时给提示（默认，不卡主对话）

  参数:
    q: 搜索关键词（必填，fetch 模式可选）
    scope: auto(默认) | all | cache | web | fetch
    max_results: 最大结果数（1-10）
    fetch_url: 当 scope=fetch 时指定要抓取的 URL
    refresh: 是否强制刷新缓存（默认 false，24h 内读缓存）
  """
  if scope == "fetch":
    if not fetch_url:
      return "错误: fetch 模式需要指定 fetch_url"
    result = _fetch_url(fetch_url, max_chars=3000)
    if not result:
      return f"✗ 抓取失败: {fetch_url}"
    filepath = _cache_path(fetch_url)
    _write_cache(filepath, fetch_url, [result], "fetch", 0)
    return (
      f"✓ 已抓取: {result.title}\n\n"
      f"{result.snippet[:1000]}\n\n"
      f"---\nfile 完整内容已缓存: {filepath}"
    )

  if not q or not q.strip():
    return "错误: 搜索关键词不能为空"

  q = q.strip()
  max_results = max(1, min(10, int(max_results)))
  cache_path = _cache_path(q)

  # L1：读缓存（除非强制刷新）
  if not refresh and scope in ("auto", "all", "cache"):
    cached = _read_cache(cache_path)
    if cached:
      lines = cached.split("\n")
      title_line = ""
      for line in lines:
        if line.startswith("## "):
          title_line = line
          break
      return (
        f" 缓存命中: {title_line[3:] if title_line else q}\n"
        f"```\n{cached[:800]}\n```\n"
        f"...（完整内容 {len(cached)} 字符）\n"
        f"file {cache_path}\n"
        f" 加 `refresh=true` 强制刷新，或 `scope=all` 联网搜索"
      )
    if scope == "cache":
      return "? 缓存未命中"
    if scope == "auto":
      # auto 模式：缓存未命中不自动联网，给提示让调用方决定
      return (
        f"? 缓存未命中: 「{q}」\n"
        f" 加 `scope=all` 联网搜索（免费，可能等几秒），"
        f"或 `scope=web` 仅网络搜索\n"
        f"  付费 API 搜索请用 @search（建议交给子 agent）"
      )

  # L2：免费网络搜索（scope=all 或 web 才会走到这里）
  if scope in ("all", "web"):
    import time
    t0 = time.time()
    results = _search_ddg(q, max_results)
    elapsed = time.time() - t0

    if results:
      _write_cache(cache_path, q, results, "web", elapsed)
      return _format_local_results(q, results, cache_path, elapsed)

  return "? 未找到相关结果"


def _format_local_results(query: str, results: list[SearchResult],
             cache_path: str, elapsed: float) -> str:
  """格式化本地搜索结果（简洁版，完整版在缓存文件里）"""
  lines = [
    f"? 本地搜索「{query}」找到 {len(results)} 条结果"
    f"（{elapsed:.1f}s）",
    "",
  ]
  for i, r in enumerate(results, 1):
    snippet = r.snippet[:120].replace("\n", " ").strip()
    lines.append(f"**{i}. {r.title}**")
    if snippet:
      lines.append(f"  {snippet}")
    if r.url:
      lines.append(f"  → {r.url}")
    lines.append("")

  lines.append(f"---\nfile 完整结果已缓存: {cache_path}")
  return "\n".join(lines)
