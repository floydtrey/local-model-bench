"""Implement cumulative R02–R05 from CONTRACT.md. No benchmark imports."""

class Journal:
    def __init__(self, db_path):
        raise NotImplementedError("T02")

    def append(self, event: dict) -> bool:
        raise NotImplementedError("T02")

    def get(self, event_id: str) -> dict | None:
        raise NotImplementedError("T02")

    def count(self) -> int:
        raise NotImplementedError("T02")

    def close(self) -> None:
        raise NotImplementedError("T02")

    def history(self, *, limit=100, offset=0, source=None, entity=None,
                event_type=None, since=None, until=None) -> list[dict]:
        raise NotImplementedError("T03")

    def current_state(self, *, as_of: str) -> list[dict]:
        raise NotImplementedError("T04")

    def append_many(self, events: list[dict]) -> list[bool]:
        raise NotImplementedError("T05")
