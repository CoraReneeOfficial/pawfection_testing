## 2025-02-20 - Service Selection Chips
**Learning:** Replacing `<select multiple>` with a custom Alpine.js chip selection component significantly improves mobile usability and accessibility. Users no longer need to know the "Hold Ctrl/Cmd" secret handshake.
**Action:** When designing forms with multi-select requirements, prefer toggleable chips or checkboxes over native multi-select listboxes. Use hidden inputs to maintain backend compatibility without changing API endpoints.

## 2025-02-21 - Clickable Dashboard Stat Cards
**Learning:** Turning summary statistic cards into clickable links (using anchor tags wrapping the card content) significantly improves navigation efficiency. It allows users to "drill down" into the data they are viewing immediately. However, it requires careful CSS overrides to reset default anchor styles (text-decoration, color) to maintain the card's visual identity.
**Action:** When displaying summary metrics that correspond to a list view or actionable page, always make the metric card clickable. Ensure links are semantically correct (using `<a>` tags) rather than relying on JavaScript `onclick` events for better accessibility and SEO.

## 2025-03-01 - Aria Label for Chat Widget
**Learning:** Icon-only buttons without textual context are completely invisible to screen reader users, providing a poor experience for accessibility. Always add `aria-label` attributes to icon-only buttons (like the AI chat send button).
**Action:** Before declaring an icon-only button complete, ensure it has an explicitly declared, descriptive `aria-label`.

## 2025-03-05 - Inline Confirmations for Destructive Actions
**Learning:** Native `confirm()` dialogs provided by the browser are jarring and break the user's immersion in the application interface. Replacing them with an inline Alpine.js confirmation state (toggling between a regular button and an "Are you sure?" prompt with Cancel/Confirm options) provides a much smoother, intentional, and aesthetically consistent user experience for destructive actions like deleting an owner.
**Action:** When implementing destructive actions (deletes, resets), use an Alpine.js `x-data="{ confirming: false }"` component with `x-show` to handle the confirmation flow directly within the UI instead of relying on `onsubmit="return confirm(...)"`.
