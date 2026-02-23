## 2025-05-15 - [Stored XSS in System Logs]
**Vulnerability:** A Stored XSS vulnerability in the System Logs page allowed execution of arbitrary JavaScript via malicious log messages when a search term was highlighted. The template used `{{ log.message|replace(...)|safe }}` which marked the entire message as safe HTML after highlighting, exposing any existing scripts in the log message.
**Learning:** The `|safe` filter is powerful and dangerous. Using it on the result of a string replacement applied to potentially unsafe input (even if intended to add safe HTML tags) exposes the original unsafe content. Highlighting logic must operate on *already escaped* content.
**Prevention:** Escape the base content first (`|e`). Then apply highlighting by replacing the *escaped* search term with a safe HTML string that wraps the *escaped* term. Use Jinja2's `format` or string concatenation with `|safe` for the replacement pattern only, not the whole string.

## 2026-02-21 - [CSRF in Opt-In Environment]
**Vulnerability:** Superadmin User Management routes (create, update, delete, reset password) were vulnerable to CSRF because the application uses `WTF_CSRF_CHECK_DEFAULT = False` (opt-in protection), but these critical routes did not manually call `csrf.protect()`.
**Learning:** Opt-in CSRF protection is risky as developers often assume protection is automatic or forget to add it. Critical administrative functions are especially dangerous targets.
**Prevention:** When using opt-in CSRF, audit all state-changing routes (POST/PUT/DELETE) to ensure `csrf.protect()` is called. Consider enabling global protection (`WTF_CSRF_CHECK_DEFAULT = True`) and opting-out specific routes instead.

## 2026-02-23 - [SQL Injection via Dynamic Filters]
**Vulnerability:** A SQL Injection vulnerability was found in the `superadmin_data_export` endpoint. The code dynamically constructed a `WHERE` clause by concatenating a user-provided filter string into a SQL query executed via `db.session.execute()`, despite using a regex blacklist.
**Learning:** String concatenation for SQL queries is almost always vulnerable, even with regex validation. Dynamic filter logic should parse structured input and reconstruct the query using parameterized bindings, rather than accepting raw SQL fragments.
**Prevention:** Avoid accepting raw SQL conditions from users. Instead, accept structured components (column, operator, value), validate them against allowlists (for columns and operators), and use parameterized queries (`:param`) for values.
