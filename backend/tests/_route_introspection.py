"""Route-table introspection helpers resilient to FastAPI's lazy includes.

FastAPI 0.137 changed ``APIRouter.include_router`` to register a lazy
``_IncludedRouter`` wrapper in ``router.routes`` instead of eagerly copying the
child ``APIRoute`` objects up into the parent. The wrapper exposes neither
``.path``/``.methods`` nor ``.tags`` (it resolves them on demand), which broke
the refactor-guard snapshots that walk ``router.routes`` directly — every row
came back as an attribute-less ``_IncludedRouter``.

``flatten_routes`` expands those wrappers back into concrete route rows, so the
guards keep working on FastAPI <=0.136 (eager, concrete routes) and >=0.137
(lazy includes). It also flattens app-level includes, so it can be pointed at a
sub-router or the whole ``app``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FlatRoute:
    """A concrete API route row, decoupled from FastAPI's internal types."""

    path: str
    methods: frozenset[str]
    name: str
    tags: tuple[str, ...]


def flatten_routes(router) -> list[FlatRoute]:
    """Return concrete ``FlatRoute`` rows in registration order.

    Concrete ``APIRoute`` objects (FastAPI <=0.136, or routes added directly)
    are emitted as-is. FastAPI >=0.137 ``_IncludedRouter`` wrappers are expanded
    via their ``effective_route_contexts()`` — which already resolves the full
    prefixed path, methods and tags, and recurses through nested includes.
    Non-API entries (WebSocket routes, Mounts, Hosts) carry no ``(method, path)``
    row and are skipped.
    """
    rows: list[FlatRoute] = []
    for route in getattr(router, "routes", []):
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if methods is not None and path is not None:
            # Concrete APIRoute — eager FastAPI, or a directly-registered route.
            rows.append(
                FlatRoute(
                    path=path,
                    methods=frozenset(methods),
                    name=getattr(route, "name", ""),
                    tags=tuple(getattr(route, "tags", ()) or ()),
                )
            )
        elif hasattr(route, "effective_route_contexts"):
            # FastAPI >=0.137 lazy `_IncludedRouter` — expand to real routes.
            for ctx in route.effective_route_contexts():
                rows.append(
                    FlatRoute(
                        path=ctx.path,
                        methods=frozenset(ctx.methods),
                        name=ctx.name,
                        tags=tuple(ctx.tags or ()),
                    )
                )
        # else: Mount / WebSocketRoute / Host — no (method, path) row to emit.
    return rows
