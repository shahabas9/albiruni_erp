from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.deps import RequestContext

ToolHandler = Callable[[Session, RequestContext, dict[str, Any]], dict[str, Any]]


class ToolValidationError(Exception):
    """Raised by a tool handler when arguments fail domain validation
    (unknown customer, insufficient stock, ...). The gateway turns this into
    a 422 and still writes an audit record — a rejected attempt is not a
    silent failure.
    """


@dataclass(frozen=True)
class ToolDefinition:
    """A typed, permissioned contract over a domain operation — the blueprint's
    "thin contract over a domain application service" (Section 12). This is
    the *only* interface the AI orchestrator is allowed to call; it never
    touches models or the database directly.
    """

    name: str
    purpose: str
    permission: str
    risk_level: str  # "L1 Read" | "L2 Prepare" | "L3 Execute"
    handler: ToolHandler


_REGISTRY: dict[str, ToolDefinition] = {}


def register_tool(definition: ToolDefinition) -> None:
    if definition.name in _REGISTRY:
        raise ValueError(f"Tool already registered: {definition.name}")
    _REGISTRY[definition.name] = definition


def get_tool(name: str) -> ToolDefinition | None:
    return _REGISTRY.get(name)


def list_tools() -> list[ToolDefinition]:
    return list(_REGISTRY.values())
