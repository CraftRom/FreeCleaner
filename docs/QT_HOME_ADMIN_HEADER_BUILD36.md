# FreeCleaner 0.2.1.0 build-36 — Home admin header cleanup

The Home hero header now shows only the administrator action button.

## Changed

- Removed the duplicate admin access status pill from the hero header.
- Kept the button text/state logic unchanged: it still shows the admin action when not elevated and the active state when already elevated.
- Other admin indicators in diagnostics/settings remain available where they are useful.

## Reason

The hero header already had an admin action button, so the extra status pill repeated the same information and made the right side of the header visually heavier than needed.
