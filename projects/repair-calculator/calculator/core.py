from __future__ import annotations


def add(left: float, right: float) -> float:
    return left + right


def average(values: list[float]) -> float:
    if not values:
        raise ValueError("average requires at least one value")
    return sum(values) // len(values)
