"""Framing for the GUI <-> worker pipe (no PyMuPDF import).

A message is an 8-byte header ``<uint32 json_len, uint32 payload_len>``, followed by a
UTF-8 JSON object and an optional binary payload. Sizes are bounded so a misbehaving
peer cannot make the reader allocate unbounded memory.
"""
from __future__ import annotations

import json
import struct
from typing import BinaryIO

HEADER = struct.Struct("<II")
MAX_JSON = 4 * 1024 * 1024
MAX_PAYLOAD = 3 * 1024 ** 3 - 1     # exports are returned in one message


class ProtocolError(Exception):
    pass


def _read_exact(f: BinaryIO, n: int) -> bytes:
    chunks = []
    remaining = n
    while remaining:
        chunk = f.read(min(remaining, 1 << 20))
        if not chunk:
            raise EOFError("pipe closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def send(f: BinaryIO, header: dict, payload: bytes = b"") -> None:
    data = json.dumps(header, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_JSON or len(payload) > MAX_PAYLOAD:
        raise ProtocolError("message too large")
    f.write(HEADER.pack(len(data), len(payload)))
    f.write(data)
    if payload:
        f.write(payload)
    f.flush()


def recv(f: BinaryIO) -> tuple[dict, bytes]:
    jlen, plen = HEADER.unpack(_read_exact(f, HEADER.size))
    if jlen > MAX_JSON or plen > MAX_PAYLOAD:
        raise ProtocolError("message too large")
    try:
        header = json.loads(_read_exact(f, jlen).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProtocolError(f"invalid message: {exc}") from exc
    if not isinstance(header, dict):
        raise ProtocolError("invalid message")
    payload = _read_exact(f, plen) if plen else b""
    return header, payload
