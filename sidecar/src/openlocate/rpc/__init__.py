"""JSON-RPC 2.0 over newline-delimited stdio."""

from openlocate.rpc.handlers import SidecarHandlers
from openlocate.rpc.server import (
    MAX_LINE_BYTES,
    RpcServer,
    StreamLineWriter,
    ThreadedLineReader,
)

__all__ = [
    "MAX_LINE_BYTES",
    "RpcServer",
    "SidecarHandlers",
    "StreamLineWriter",
    "ThreadedLineReader",
]
