from .config import ReportConfig


def render_report(items: list[str], config: ReportConfig) -> str:
    lines = ["Report"]
    lines.extend(f"- {item}" for item in items)
    if config.include_totals:
        lines.append(f"Total: {len(items)}")
    return "\n".join(lines)
