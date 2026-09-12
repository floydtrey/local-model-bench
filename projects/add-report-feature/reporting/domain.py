from __future__ import annotations


def summarize(values: list[float]) -> dict[str, float | int]:
    if not values:
        raise ValueError("at least one value is required")
    total = sum(values)
    return {
        "count": len(values),
        "total": total,
        "average": total / len(values),
    }
