import unittest

from pricing.discount import apply_discount


class DiscountTests(unittest.TestCase):
    def test_non_vip_total_is_unchanged(self):
        self.assertEqual(apply_discount(100.00), 100.00)

    def test_vip_receives_ten_percent_discount(self):
        self.assertEqual(apply_discount(100.00, vip=True), 90.00)

    def test_result_is_rounded_to_two_decimals(self):
        self.assertEqual(apply_discount(10.01, vip=True), 9.01)


if __name__ == "__main__":
    unittest.main()
