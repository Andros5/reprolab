"""Proof that a replay does not touch the network: any connection attempt fails."""

from __future__ import annotations

import socket
from contextlib import contextmanager
from typing import Iterator


class NetworkBlocked(RuntimeError):
    pass


@contextmanager
def no_network() -> Iterator[None]:
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_create = socket.create_connection

    def refuse(*args, **kwargs):
        raise NetworkBlocked("network access attempted during an offline replay")

    socket.socket.connect = refuse  # type: ignore[method-assign]
    socket.socket.connect_ex = refuse  # type: ignore[method-assign]
    socket.create_connection = refuse  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]
        socket.create_connection = original_create  # type: ignore[assignment]
