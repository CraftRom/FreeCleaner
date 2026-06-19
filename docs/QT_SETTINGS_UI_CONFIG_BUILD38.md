# FreeCleaner 0.2.1.0 build-38 — Settings UI and config-backed runtime options

This build expands the Settings page so options that were previously available only through `config.json` or environment flags can be controlled from the interface.

## Added UI settings

- `ui_animations_enabled` — enables or disables lightweight Qt fade animations.
- `ui_animation_duration_ms` — controls animation duration.
- `startup_status_sync_enabled` — enables optional async status scan after startup.
- `startup_update_check_enabled` — gates startup update checks.
- `auto_check_updates` — controls automatic update checks when the startup gate is enabled.
- `background_worker_limit` — limits concurrent background jobs.
- `confirm_heavy_actions` — keeps protection prompts for heavy actions.
- `compact_event_log` — keeps the visible UI log readable while full logs remain on disk.
- `notify_on_finish` and `notify_admin_required` — user-facing notification behavior.

## UI polish

Settings rows were converted into larger clickable cards with hover/pressed states, key labels, and lightweight fade-in effects.  The layout is split into Interface, Startup, Safety, Notifications, Info and License tabs so the Settings page no longer feels like a miscellaneous list.

## Safety

The default remains conservative: startup status sync and startup update checks stay disabled unless the user enables them. This avoids returning to the earlier freeze behavior while still giving power users a visible control.
