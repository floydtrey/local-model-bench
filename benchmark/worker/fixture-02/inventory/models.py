from dataclasses import dataclass


@dataclass(frozen=True)
class InventoryItem:
    sku: str
    name: str
    quantity: int
    active: bool
