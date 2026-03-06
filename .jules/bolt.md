## 2025-02-22 - Notification Polling Optimization
**Learning:** The notification polling endpoint (`/notifications/check_new`) lazily generates notifications inside a loop, causing N+1 queries. Since this endpoint is polled by the client, it amplifies database load significantly.
**Action:** When optimizing notification generation or similar "check" logic, prefer batch fetching existing records and performing existence checks in memory (using sets/dictionaries) to reduce read queries to O(1) (constant number of queries regardless of items).

## 2025-03-04 - Context Processor Query Optimization
**Learning:** The `inject_notifications` context processor in `app.py` runs on *every single page render*. Previously, it executed a `.limit(5).all()` query for the UI list, and a separate `.count()` query to get the total number of unread notifications, even for users with 0 or a few unread notifications, effectively doubling the query load.
**Action:** By over-fetching by one (`.limit(6).all()`), we can use `len(notifications)` to get the exact count when the user has fewer than 6 unread notifications. Only perform the `.count()` query when `len >= 6`. This eliminates an entire SQL query per page load for the vast majority of users who actively manage their notifications.

## 2025-03-05 - Notification Queries Database Indexing
**Learning:** Context processors (like `inject_notifications` in `app.py`) execute on *every single page load*, and the frontend AlpineJS notification polling hits the backend *every 10 seconds per active user*. Both of these trigger queries looking for unread notifications by `store_id` and `is_read`. Without a specific index covering these two columns, the database is forced to do sequential scans on the Notification table under extreme frequency, creating a hidden, massive performance tax as the data grows.
**Action:** Always identify queries executed inside context processors and high-frequency polling endpoints, and ensure they are covered by dedicated, highly-specific composite database indexes (e.g., `db.Index('idx_notification_store_is_read', 'store_id', 'is_read')`) to turn O(N) table scans into fast index lookups.

## 2025-05-15 - Bulk Update Optimization for Record Unlinking
**Learning:** Iterating over a collection of SQLAlchemy objects to update a single field (like unlinking an owner from appointment requests) triggers N+1 update patterns, causing excessive database round-trips and session flush overhead.
**Action:** Use SQLAlchemy's bulk `update()` method (e.g., `Model.query.filter_by(...).update({'field': None}, synchronize_session=False)`) to perform the update in a single SQL statement. This moves the logic from the application to the database layer, significantly improving performance for large record sets.
