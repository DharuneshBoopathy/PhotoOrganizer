"""
Bridge between Python logging and a Tkinter queue.

Pipeline runs in a worker thread and emits log records + progress events.
The GUI's main thread polls the queue every ~100ms and renders updates.
"""
import logging
import queue
from typing import Any


class QueueLogHandler(logging.Handler):
    """Push every log record onto a thread-safe queue as a dict."""

    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q
        self.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        ))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        self.q.put({
            "type": "log",
            "level": record.levelname,
            "msg": msg,
        })


def emit_progress(q: queue.Queue, stage: str, current: int, total: int,
                   message: str = "") -> None:
    """Helper used by the pipeline's progress_callback."""
    q.put({
        "type": "progress",
        "stage": stage,
        "current": current,
        "total": total,
        "message": message,
    })


def emit_done(q: queue.Queue, status: str, summary: dict) -> None:
    q.put({"type": "done", "status": status, "summary": summary})


def emit_error(q: queue.Queue, error: str) -> None:
    q.put({"type": "error", "error": error})
