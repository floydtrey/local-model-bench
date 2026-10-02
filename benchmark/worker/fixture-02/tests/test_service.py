import unittest

from inventory.service import list_items


class InventoryServiceTests(unittest.TestCase):
    def test_default_lists_only_active_items(self):
        items = list_items()
        self.assertEqual([item.sku for item in items], ["A-100", "C-300"])
        self.assertTrue(all(item.active for item in items))

    def test_include_inactive_returns_all_items(self):
        items = list_items(include_inactive=True)
        self.assertEqual([item.sku for item in items], ["A-100", "B-200", "C-300"])


if __name__ == "__main__":
    unittest.main()
