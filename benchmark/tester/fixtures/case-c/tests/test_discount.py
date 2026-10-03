import unittest

from pricing.discount import apply_discount


class DiscountTests(unittest.TestCase):
    def test_non_vip_total_is_unchanged(self):
        self.assertEqual(apply_discount(100.00), 100.00)


if __name__ == "__main__":
    unittest.main()
