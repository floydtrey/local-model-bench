from dataclasses import dataclass


@dataclass
class ReportConfig:
    include_totals: bool = True
