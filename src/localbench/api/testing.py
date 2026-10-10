"""Explicit isolated fixture admission, never exposed through HTTP or a launcher."""
from dataclasses import dataclass
from datetime import datetime

@dataclass(frozen=True)
class FixturePrincipal:
    subject: str
    audience: str
    grants: frozenset[str]
    expires_at: datetime

def create_fixture_app(*, read_port, validator, clock=None):
    if read_port.source.mode != 'fixture':
        raise ValueError('Synthetic admission requires an isolated fixture source')
    from .app import _build_app
    return _build_app(read_port=read_port,validator=validator,clock=clock)
