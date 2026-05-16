# utils/watcher.py - 工作区文件变化监听（可选 watchdog 集成）
"""watchdog 不可用时回退到轮询模式。变化时通过 callback 通知上层。"""

import os
import time
import threading
from typing import Callable


class WorkspaceWatcher:
  def __init__(self, workspace: str, callback: Callable = None, poll_interval: float = 2.0):
    self.workspace = workspace
    self.callback = callback
    self.poll_interval = poll_interval
    self._running = False
    self._thread = None
    self._snapshots: dict[str, float] = {}
    self._use_watchdog = False

  def start(self):
    if self._running:
      return
    self._running = True
    try:
      from watchdog.observers import Observer
      from watchdog.events import FileSystemEventHandler
      _cb = self.callback
      class _Handler(FileSystemEventHandler):
        def on_modified(self, event):
          if _cb:
            _cb(event.src_path)

        def on_created(self, event):
          if _cb:
            _cb(event.src_path)

      self._observer = Observer()
      self._observer.schedule(_Handler(), self.workspace, recursive=True)
      self._observer.start()
      self._use_watchdog = True
    except ImportError:
      self._thread = threading.Thread(target=self._poll_loop, daemon=True)
      self._thread.start()

  def stop(self):
    self._running = False
    if self._use_watchdog:
      try:
        self._observer.stop()
        self._observer.join()
      except Exception:
        pass
    else:
      pass

  def _poll_loop(self):
    while self._running:
      self._check_changes()
      time.sleep(self.poll_interval)

  def _check_changes(self):
    try:
      current_files = set()
      for root, dirs, files in os.walk(self.workspace):
        for f in files:
          fpath = os.path.join(root, f)
          current_files.add(fpath)
          try:
            mtime = os.path.getmtime(fpath)
            old = self._snapshots.get(fpath)
            if old and mtime != old:
              self._snapshots[fpath] = mtime
              if self.callback:
                try:
                  self.callback(fpath)
                except Exception as cb_e:
                  import logging
                  logging.getLogger("tiao").error(
                    "文件变更 callback 异常 %s: %s", fpath, cb_e, exc_info=True
                  )
            else:
              self._snapshots[fpath] = mtime
          except OSError:
            pass
      for stale in list(self._snapshots):
        if stale not in current_files:
          del self._snapshots[stale]
    except Exception as e:
      import logging
      logging.getLogger("tiao").error("文件变更监听异常: %s", e, exc_info=True)
