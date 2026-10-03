# Project Intent

Add VIP discount behavior to the pricing helper.

Requirements:
- `apply_discount(total, vip=False)` must preserve the existing public signature.
- Non-VIP totals are returned unchanged.
- VIP totals receive exactly a 10% discount.
- The returned value is rounded to two decimal places.
- Do not add third-party dependencies.
