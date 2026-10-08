"""Implement R01 from CONTRACT.md. Standard library only."""

class EventConflictError(ValueError):
    """An event ID was already used for different normalized content."""


def normalize_event(event: dict) -> dict:
    """Return an independent normalized event or raise ValueError."""
    raise NotImplementedError("T01")
