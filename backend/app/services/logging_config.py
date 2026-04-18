"""Structured logging setup — structlog + stdlib bridge.

One `configure_logging()` call sets up:
  - structlog processors (contextvars merging, ISO timestamps, level)
  - A single renderer (JSON when `VOXYFLOW_LOG_JSON` is truthy, pretty console otherwise)
  - A stdlib `ProcessorFormatter` so plain `logging.getLogger(...).info(...)` calls
    share the same format — existing code keeps working, it just gets structured.
  - A rotating file handler when `log_dir` is given (systemd already collects
    stderr, so stream logging stays on stderr).

Contextvars are the async-safe carrier for per-request/per-WS context
(request_id, chat_id, project_id, session_id, ...). Bind via
`bound_contextvars(...)` (a context manager) or `bind_contextvars(...)`
directly — both are re-exported here for convenience.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Any

import structlog
from structlog.contextvars import (
    bind_contextvars,
    bound_contextvars,
    clear_contextvars,
    merge_contextvars,
    unbind_contextvars,
)

__all__ = [
    "configure_logging",
    "get_logger",
    "bind_contextvars",
    "bound_contextvars",
    "unbind_contextvars",
    "clear_contextvars",
]


_configured = False


def _is_json_mode() -> bool:
    return os.environ.get("VOXYFLOW_LOG_JSON", "").lower() in ("1", "true", "yes", "on")


def configure_logging(
    *,
    level: int = logging.INFO,
    log_dir: str | None = None,
    log_filename: str = "backend.log",
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 3,
    stream: Any = None,
) -> None:
    """Initialise structlog + stdlib logging.

    Idempotent — calling twice is a no-op (later calls silently return). This
    matters because `app/main.py` and `app/startup.py` both import each other.

    Args:
        level:         Root log level.
        log_dir:       Directory for rotating file handler. None disables file output.
        log_filename:  Log file name under log_dir.
        max_bytes:     Rotation threshold per file.
        backup_count:  How many rotated files to keep.
        stream:        Where to stream logs. Default: stderr (systemd-friendly).
                       Pass `False` to disable the stream handler entirely.
    """
    global _configured
    if _configured:
        return

    json_mode = _is_json_mode()

    # Shared processor chain — runs for both structlog-native and stdlib-origin records.
    shared_processors: list[Any] = [
        merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    if json_mode:
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    # structlog configuration
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Stdlib bridge — this formatter is what RootHandler uses, and it runs the
    # same processor chain against stdlib LogRecords.
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    handlers: list[logging.Handler] = []

    if stream is not False:
        stream_handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
        stream_handler.setFormatter(formatter)
        handlers.append(stream_handler)

    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, log_filename),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    root = logging.getLogger()
    # Clear any prior handlers so we don't duplicate lines when reconfiguring
    # in tests or when a prior basicConfig() call added a default handler.
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in handlers:
        root.addHandler(h)
    root.setLevel(level)

    # Third-party loggers: tame the noisy ones so structured output stays useful.
    for noisy in ("httpx", "httpcore", "asyncio", "watchfiles", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))

    _configured = True


def get_logger(name: str | None = None) -> Any:
    """Return a structlog BoundLogger. Usable anywhere you'd use `logging.getLogger`."""
    return structlog.get_logger(name) if name else structlog.get_logger()
