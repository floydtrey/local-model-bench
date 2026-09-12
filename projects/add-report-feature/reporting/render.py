from __future__ import annotations


def render_text(summary: dict[str, float | int]) -> str:
    return (
        f"count={summary['count']} "
        f"total={summary['total']} "
        f"average={summary['average']}"
    )
