## 2025-02-20 - Service Selection Chips
**Learning:** Replacing `<select multiple>` with a custom Alpine.js chip selection component significantly improves mobile usability and accessibility. Users no longer need to know the "Hold Ctrl/Cmd" secret handshake.
**Action:** When designing forms with multi-select requirements, prefer toggleable chips or checkboxes over native multi-select listboxes. Use hidden inputs to maintain backend compatibility without changing API endpoints.

## 2025-02-21 - Clickable Dashboard Stat Cards
**Learning:** Turning summary statistic cards into clickable links (using anchor tags wrapping the card content) significantly improves navigation efficiency. It allows users to "drill down" into the data they are viewing immediately. However, it requires careful CSS overrides to reset default anchor styles (text-decoration, color) to maintain the card's visual identity.
**Action:** When displaying summary metrics that correspond to a list view or actionable page, always make the metric card clickable. Ensure links are semantically correct (using `<a>` tags) rather than relying on JavaScript `onclick` events for better accessibility and SEO.
