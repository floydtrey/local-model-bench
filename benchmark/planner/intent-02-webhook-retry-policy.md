# Planner Intent 02 — webhook retry policy

A small Python service sends webhook deliveries to external HTTP endpoints.

Current project facts:
- Delivery code: `src/webhooks/delivery.py`
- Existing tests: `tests/test_delivery.py`
- The public function `send_delivery(url, payload)` performs one delivery attempt and returns a `DeliveryResult`.
- Existing callers depend on the current `send_delivery(url, payload)` signature and the current `DeliveryResult` shape.
- The current implementation performs no retries.
- Existing request timeout behavior must not change.
- The current result/error handling does not classify failures as transient or permanent.

Requested change:
Automatically retry transient delivery failures. A delivery may make at most 3 total attempts, including the initial attempt. Permanent failures must return after the first attempt without retrying. Retries, when allowed, should occur immediately; no delay or backoff is requested.

Constraints:
- Do not add third-party dependencies.
- Preserve the existing public function signature.
- Preserve the existing `DeliveryResult` shape.
- Preserve the existing request timeout behavior.
- Add or update tests covering retry count, eventual success after a transient failure, permanent failure without retry, and exhaustion of all allowed attempts.
