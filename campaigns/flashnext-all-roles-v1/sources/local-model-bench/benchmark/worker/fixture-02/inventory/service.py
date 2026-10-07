from .models import InventoryItem


_ITEMS = [
    InventoryItem("A-100", "Widget", 4, True),
    InventoryItem("B-200", "Spare Part", 2, False),
    InventoryItem("C-300", "Cable", 7, True),
]


def list_items(include_inactive: bool = False) -> list[InventoryItem]:
    if include_inactive:
        return list(_ITEMS)
    return [item for item in _ITEMS if item.active]
