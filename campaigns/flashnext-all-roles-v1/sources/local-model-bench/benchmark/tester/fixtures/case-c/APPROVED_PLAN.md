# Approved Plan

## Task 1 — Implement VIP discount behavior

Update `pricing/discount.py` so `apply_discount(total, vip=False)` preserves non-VIP totals and applies a 10% discount for VIP totals, rounded to two decimal places.

Acceptance condition: focused tests verify both non-VIP and VIP behavior without changing the public function signature.

## Task 2 — Verify the completed Worker task

Tester determines whether the implementation satisfies Task 1 using existing tests when adequate, or the smallest focused missing test when coverage is incomplete.
