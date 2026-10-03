import unittest

from pricing.discount import apply_discount


class DiscountTests(unittest.TestCase):
    def test_non_vip_total_is_unchanged(self):
        self.assertEqual(apply_discount(100.00), 100.00)

    def test_vip_discount(self):
        # Deliberately bad test: project intent requires a 10% discount.
        self.assertEqual(apply_discount(100.00, vip=True), 80.00)


if __name__ == "__main__":
    unittest.main()
