"""Background thumbnail rendering (via the sandboxed worker) with an LRU cache."""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QImage

from .errors import WorkerCrashed
from .worker_client import WorkerClient

BUCKETS = (128, 256, 384, 512)


def bucket_for(size: int) -> int:
    for b in BUCKETS:
        if size <= b:
            return b
    return BUCKETS[-1]


class _Worker(QThread):
    rendered = Signal(int, int, int, QImage)   # source_id, page, bucket, image
    failed = Signal(int, int, int)

    def __init__(self, client: WorkerClient, parent=None):
        super().__init__(parent)
        self._client = client
        self._cond = threading.Condition()
        self._queue: list[tuple[int, int, int]] = []   # LIFO: latest requests first
        self._stop = False

    def request(self, key: tuple[int, int, int]) -> None:
        with self._cond:
            if key in self._queue:
                self._queue.remove(key)
            self._queue.append(key)
            self._cond.notify()

    def drop_source(self, source_id: int) -> None:
        with self._cond:
            self._queue = [k for k in self._queue if k[0] != source_id]

    def stop(self) -> None:
        with self._cond:
            self._stop = True
            self._queue.clear()
            self._cond.notify()

    def run(self) -> None:
        while True:
            with self._cond:
                while not self._queue and not self._stop:
                    self._cond.wait()
                if self._stop:
                    break
                key = self._queue.pop()
            source_id, index, size = key
            try:
                w, h, stride, data = self._client.render(source_id, index, size)
            except WorkerCrashed:
                # the worker was restarted; don't retry a page that may have crashed it
                self.failed.emit(*key)
                continue
            except Exception:
                self.failed.emit(*key)
                continue
            img = QImage(data, w, h, stride, QImage.Format.Format_RGB888).copy()
            self.rendered.emit(source_id, index, size, img)


class ThumbnailService(QObject):
    """Ask for thumbnails with :meth:`get`; listen to :attr:`ready` for updates."""

    ready = Signal(int, int)   # source_id, page_index

    def __init__(self, client: WorkerClient, parent=None, max_items: int = 600):
        super().__init__(parent)
        self._cache: OrderedDict[tuple[int, int, int], QImage] = OrderedDict()
        self._pending: set[tuple[int, int, int]] = set()
        self._failed: set[tuple[int, int]] = set()
        self._max = max_items
        self._worker = _Worker(client)
        self._worker.rendered.connect(self._on_rendered)
        self._worker.failed.connect(self._on_failed)
        self._worker.start(QThread.Priority.LowPriority)

    def is_failed(self, source_id: int, index: int) -> bool:
        return (source_id, index) in self._failed

    def get(self, source_id: int, index: int, size: int) -> Optional[QImage]:
        """Return the best cached image (may be lower-res) and queue a render if needed."""
        b = bucket_for(size)
        key = (source_id, index, b)
        img = self._cache.get(key)
        if img is not None:
            self._cache.move_to_end(key)
            return img
        if key not in self._pending and (source_id, index) not in self._failed:
            self._pending.add(key)
            self._worker.request(key)
        for other in sorted(BUCKETS, reverse=True):   # fallback: any cached size
            img = self._cache.get((source_id, index, other))
            if img is not None:
                return img
        return None

    def forget_source(self, source_id: int) -> None:
        self._worker.drop_source(source_id)
        self._pending = {k for k in self._pending if k[0] != source_id}
        self._failed = {k for k in self._failed if k[0] != source_id}

    def _on_rendered(self, source_id: int, index: int, size: int, img: QImage) -> None:
        key = (source_id, index, size)
        self._pending.discard(key)
        self._cache[key] = img
        while len(self._cache) > self._max:
            self._cache.popitem(last=False)
        self.ready.emit(source_id, index)

    def _on_failed(self, source_id: int, index: int, size: int) -> None:
        self._pending.discard((source_id, index, size))
        self._failed.add((source_id, index))
        self.ready.emit(source_id, index)

    def shutdown(self) -> None:
        self._worker.stop()
        self._worker.wait(5000)
