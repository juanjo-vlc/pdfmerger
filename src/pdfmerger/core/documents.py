"""GUI-side registry of opened documents; all parsing happens in the worker."""
from __future__ import annotations

import itertools
import os
from dataclasses import dataclass, field
from typing import Optional

from .worker_client import WorkerClient


@dataclass
class DocInfo:
    id: int
    path: str
    password: Optional[str] = field(repr=False)
    page_count: int
    metadata: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return os.path.basename(self.path)


class DocumentStore:
    def __init__(self, client: WorkerClient):
        self.client = client
        self._docs: dict[int, DocInfo] = {}
        self._ids = itertools.count(1)

    def add(self, path: str, password: Optional[str] = None) -> DocInfo:
        """Open ``path`` in the worker. Raises PasswordRequired / NotAPdf / UnsafePdf /
        WorkerCrashed."""
        path = os.path.abspath(path)
        sid = next(self._ids)
        count, meta = self.client.open(sid, path, password)
        info = DocInfo(sid, path, password, count, meta)
        self._docs[sid] = info
        return info

    def restore(self, info: DocInfo) -> None:
        """Re-insert a removed document (undo); re-opens it in the worker."""
        self._docs[info.id] = info
        try:
            self.client.open(info.id, info.path, info.password)
        except Exception:
            pass   # thumbnails will show as failed; export reports the error

    def remove(self, sid: int) -> DocInfo:
        info = self._docs.pop(sid)
        self.client.close_source(sid)
        return info

    def get(self, sid: int) -> DocInfo:
        return self._docs[sid]

    def __contains__(self, sid: int) -> bool:
        return sid in self._docs

    def __iter__(self):
        return iter(list(self._docs.values()))

    def __len__(self) -> int:
        return len(self._docs)

    def close_all(self) -> None:
        for sid in list(self._docs):
            self.remove(sid)
