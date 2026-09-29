class NotFoundError(Exception):
    """Raised by a domain service when a tenant-scoped lookup finds nothing.
    Routes translate this to a 404 — never to a raw SQLAlchemy exception."""


class ConflictError(Exception):
    """Raised when a write would violate a uniqueness rule (e.g. a username
    or SKU already taken within the tenant)."""
