"""ORM → Pydantic generator (M21 — single source of truth).

Builds Pydantic v2 models at import time by introspecting SQLAlchemy ORM
column metadata via ``sqlalchemy.inspect()``. The generator emits one field
per mapped column with its Python type + nullability, producing a base model
that mirrors the database schema exactly.

Hand-authored Pydantic response / request models then *subclass* these bases
and layer on:

* computed / synthesized fields that live outside the column list
  (e.g. ``CardResponse.dependency_ids`` is derived from the ``dependencies``
  relationship, not a column);
* type overrides where the wire format differs from storage
  (e.g. ``Card.files`` is JSON text in the DB but emitted as ``list[str]``);
* request-side validators (``pattern``, ``ge``/``le``) that are API concerns,
  not schema concerns.

This keeps one source of truth for *column set and nullability* while letting
the API layer author its own validation rules. ``pydantic-sqlalchemy`` was
considered and rejected: last release 2020, no Pydantic v2 support.

Regression guard: if someone adds a column to an ORM model, every response
model that subclasses the generated base automatically picks it up — no
second file to edit. If someone removes or renames one, the generated field
disappears / changes and downstream code fails loudly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, create_model
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
)

from app.database import Card, Chat, Document, Message, Project


# Map SQLAlchemy column types → Python types. Keep conservative: anything
# outside this table falls back to ``Any`` and surfaces on import rather
# than at request time.
_SA_TYPE_TO_PY: dict[type, type] = {
    String: str,
    Text: str,
    Integer: int,
    Float: float,
    Boolean: bool,
    DateTime: datetime,
}


def _python_type_for(column: Any) -> type:
    """Resolve the Python type for a SQLAlchemy Column."""
    col_type = column.type
    for sa_type, py_type in _SA_TYPE_TO_PY.items():
        if isinstance(col_type, sa_type):
            return py_type
    # Unknown column type — fail loud at import time so the generator stays honest.
    raise TypeError(
        f"_generated: unsupported SQLAlchemy column type {col_type!r} "
        f"on column {column.key!r}. Extend _SA_TYPE_TO_PY."
    )


def orm_base_model(
    orm_cls: type,
    *,
    name: str,
    exclude: frozenset[str] = frozenset(),
) -> type[BaseModel]:
    """Build a Pydantic v2 BaseModel mirroring the ORM column list.

    Parameters
    ----------
    orm_cls:
        The SQLAlchemy ORM class (a DeclarativeBase subclass).
    name:
        Name for the generated Pydantic class.
    exclude:
        Column names to skip — useful when the wire format intentionally
        diverges (e.g. ``Card.files`` stored as JSON text but exposed as
        ``list[str]`` on an overriding subclass).

    The generated model enables ``from_attributes`` so it can be built
    directly from an ORM instance via ``Model.model_validate(orm_obj)``.
    """
    mapper = sa_inspect(orm_cls)
    fields: dict[str, tuple[Any, Any]] = {}

    for column in mapper.columns:
        if column.key in exclude:
            continue
        py_type = _python_type_for(column)
        # Nullability: column.nullable OR column has a default (server/Python).
        # If a column is nullable the field is Optional with default None.
        # Otherwise the field has no default and must be supplied.
        if column.nullable:
            field_type: Any = py_type | None
            default: Any = None
        else:
            field_type = py_type
            default = ...  # required
        fields[column.key] = (field_type, default)

    model = create_model(  # type: ignore[call-overload]
        name,
        __config__=ConfigDict(from_attributes=True),
        **fields,
    )
    return model


# ---------------------------------------------------------------------------
# Generated bases — one per ORM model with a public response surface.
#
# NOTE on `exclude`: we drop columns whose wire format intentionally differs
# from the stored format. The overriding subclass re-declares the field with
# the correct wire type.
# ---------------------------------------------------------------------------

CardBase = orm_base_model(
    Card,
    name="CardBase",
    # `files` is stored as a JSON string, emitted as list[str].
    exclude=frozenset({"files"}),
)

ProjectBase = orm_base_model(Project, name="ProjectBase")

ChatBase = orm_base_model(Chat, name="ChatBase")

MessageBase = orm_base_model(Message, name="MessageBase")

DocumentBase = orm_base_model(Document, name="DocumentBase")


__all__ = [
    "CardBase",
    "ChatBase",
    "DocumentBase",
    "MessageBase",
    "ProjectBase",
    "orm_base_model",
]
