## 2025-02-22 - Notification Polling Optimization
**Learning:** The notification polling endpoint (`/notifications/check_new`) lazily generates notifications inside a loop, causing N+1 queries. Since this endpoint is polled by the client, it amplifies database load significantly.
**Action:** When optimizing notification generation or similar "check" logic, prefer batch fetching existing records and performing existence checks in memory (using sets/dictionaries) to reduce read queries to O(1) (constant number of queries regardless of items).

## 2025-03-04 - Context Processor Query Optimization
**Learning:** The `inject_notifications` context processor in `app.py` runs on *every single page render*. Previously, it executed a `.limit(5).all()` query for the UI list, and a separate `.count()` query to get the total number of unread notifications, even for users with 0 or a few unread notifications, effectively doubling the query load.
**Action:** By over-fetching by one (`.limit(6).all()`), we can use `len(notifications)` to get the exact count when the user has fewer than 6 unread notifications. Only perform the `.count()` query when `len >= 6`. This eliminates an entire SQL query per page load for the vast majority of users who actively manage their notifications.

## 2025-03-05 - Notification Queries Database Indexing
**Learning:** Context processors (like `inject_notifications` in `app.py`) execute on *every single page load*, and the frontend AlpineJS notification polling hits the backend *every 10 seconds per active user*. Both of these trigger queries looking for unread notifications by `store_id` and `is_read`. Without a specific index covering these two columns, the database is forced to do sequential scans on the Notification table under extreme frequency, creating a hidden, massive performance tax as the data grows.
**Action:** Always identify queries executed inside context processors and high-frequency polling endpoints, and ensure they are covered by dedicated, highly-specific composite database indexes (e.g., `db.Index('idx_notification_store_is_read', 'store_id', 'is_read')`) to turn O(N) table scans into fast index lookups.

## 2025-03-06 - Unnecessary JOIN Optimization
**Learning:** In the `/logs` route, `ActivityLog.query` was performing an unnecessary `.join(User)` just to filter by `store_id` (via `User.store_id == store_id`). Since `ActivityLog` already has a `store_id` column, the JOIN can be safely removed.
**Action:** Review models for existing foreign keys or reference columns before performing JOINs solely for filtering, as JOIN operations are computationally expensive and can often be bypassed by directly querying the available relationships' keys.

## 2025-03-11 - In-Memory Aggregation of Fetched Data
**Learning:** In the `superadmin_dashboard` endpoint, the code was fetching all stores with `Store.query.all()`, and then executing multiple `.count()` queries on the same table (e.g., `Store.query.filter_by(subscription_status='active').count()`). This causes redundant database queries (N+1 style aggregations) for data that is already fully loaded in memory.
**Action:** When a full table or significant dataset is already loaded into a Python list (e.g., for rendering in a UI), avoid executing additional SQL aggregation queries (`.count()`, `.sum()`) on that same dataset. Instead, use Python list comprehensions or generator expressions (e.g., `sum(1 for x in items if condition)`) to calculate the aggregations in-memory.
## 2026-03-12 - Combine related aggregate queries
**Learning:** Performing multiple independent `.count()` queries on the same table (e.g., `Store.query.count()` and `Store.query.filter_by(...).count()`) requires a full network round-trip per query, leading to N+1 style aggregation overhead.
**Action:** When calculating multiple aggregate metrics on the same table, merge them into a single query using SQLAlchemy's `db.session.query()` combined with `func.count()` and `func.sum(case(...))` to retrieve all metrics in one efficient round-trip.
