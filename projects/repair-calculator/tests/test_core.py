import unittest

from calculator.core import add, average


class CalculatorTests(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)

    def test_average_whole_number(self):
        self.assertEqual(average([2, 4]), 3)

    def test_average_fractional(self):
        self.assertEqual(average([2, 3]), 2.5)

    def test_average_rejects_empty_input(self):
        with self.assertRaises(ValueError):
            average([])


if __name__ == "__main__":
    unittest.main()
