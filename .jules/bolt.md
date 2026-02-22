## 2025-02-22 - Notification Polling Optimization
**Learning:** The notification polling endpoint (`/notifications/check_new`) lazily generates notifications inside a loop, causing N+1 queries. Since this endpoint is polled by the client, it amplifies database load significantly.
**Action:** When optimizing notification generation or similar "check" logic, prefer batch fetching existing records and performing existence checks in memory (using sets/dictionaries) to reduce read queries to O(1) (constant number of queries regardless of items).
