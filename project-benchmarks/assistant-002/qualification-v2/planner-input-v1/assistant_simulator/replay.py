"""S03/S04: injected sink and virtual time; no file/process/network access."""
class Replay:
    def __init__(self, raw: dict, sink):
        raise NotImplementedError("Not implemented")

    def advance(self, to_ms: int) -> dict:
        raise NotImplementedError("Not implemented")

    def checkpoint(self) -> dict:
        raise NotImplementedError("Not implemented")

    @classmethod
    def from_checkpoint(cls, raw: dict, sink, saved: dict):
        raise NotImplementedError("Not implemented")
