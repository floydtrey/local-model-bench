"""S03/S04: injected sink and virtual time; no file/process/network access."""
class Replay:
    def __init__(self, raw: dict, sink):
        raise NotImplementedError("T03")

    def advance(self, to_ms: int) -> dict:
        raise NotImplementedError("T03")

    def checkpoint(self) -> dict:
        raise NotImplementedError("T04")

    @classmethod
    def from_checkpoint(cls, raw: dict, sink, saved: dict):
        raise NotImplementedError("T04")
