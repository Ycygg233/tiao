# utils/metrics.py - 进程资源观测（可选 psutil 依赖）
import os
import threading


def get_process_stats() -> dict:
  """获取当前进程资源占用。优先使用 psutil，不可用时回退到 /proc。"""
  stats = {
    "rss_mb": 0,
    "cpu_percent": 0,
    "threads": 0,
    "open_files": 0,
  }
  try:
    import psutil
    proc = psutil.Process()
    mem = proc.memory_info()
    stats["rss_mb"] = round(mem.rss / 1024 / 1024, 1)
    stats["cpu_percent"] = round(proc.cpu_percent(), 1)
    stats["threads"] = proc.num_threads()
    try:
      stats["open_files"] = len(proc.open_files())
    except Exception:
      pass
  except ImportError:
    try:
      with open("/proc/self/status", "r") as f:
        for line in f:
          if line.startswith("VmRSS:"):
            stats["rss_mb"] = round(int(line.split()[1]) / 1024, 1)
          elif line.startswith("Threads:"):
            stats["threads"] = int(line.split()[1])
    except Exception:
      pass
  return stats


def get_tool_stats() -> dict:
  """获取工具注册统计"""
  from tools.registry import _TOOL_REGISTRY
  global_count = len(_TOOL_REGISTRY["global"])
  session_count = 0
  for sid, tools in _TOOL_REGISTRY["session"].items():
    session_count += len(tools)
  return {
    "global_tools": global_count,
    "session_tools": session_count,
    "total_tools": global_count + session_count,
  }
