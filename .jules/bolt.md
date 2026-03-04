## 2025-02-22 - Notification Polling Optimization
**Learning:** The notification polling endpoint (`/notifications/check_new`) lazily generates notifications inside a loop, causing N+1 queries. Since this endpoint is polled by the client, it amplifies database load significantly.
**Action:** When optimizing notification generation or similar "check" logic, prefer batch fetching existing records and performing existence checks in memory (using sets/dictionaries) to reduce read queries to O(1) (constant number of queries regardless of items).

## 2025-03-04 - Context Processor Query Optimization
**Learning:** The `inject_notifications` context processor in `app.py` runs on *every single page render*. Previously, it executed a `.limit(5).all()` query for the UI list, and a separate `.count()` query to get the total number of unread notifications, even for users with 0 or a few unread notifications, effectively doubling the query load.
**Action:** By over-fetching by one (`.limit(6).all()`), we can use `len(notifications)` to get the exact count when the user has fewer than 6 unread notifications. Only perform the `.count()` query when `len >= 6`. This eliminates an entire SQL query per page load for the vast majority of users who actively manage their notifications.
