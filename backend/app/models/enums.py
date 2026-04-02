"""Shared status enums — use these instead of hardcoded strings."""

from enum import StrEnum


class CardStatus(StrEnum):
    CARD = "card"          # inbox / unsorted
    IDEA = "idea"
    TODO = "todo"
    IN_PROGRESS = "in-progress"
    DONE = "done"
    ARCHIVED = "archived"


class WorkerTaskStatus(StrEnum):
    """Status values for the WorkerTask DB table."""
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class WorkerSessionStatus(StrEnum):
    """Status values for in-memory worker sessions (worker_session_store)."""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
