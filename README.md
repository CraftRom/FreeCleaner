# FreeCleaner

Current package: 1.2.0.0-build-59 — Smart Programs safety: uses conservative removed-app detection, skips Windows/system/vendor AppData, blocks active runtimes, and cleans only verified removed-app leftovers.


## 1.2.0.0 build-52 — Installer update mode and recent release changelog

- Installer detects an existing FreeCleaner installation and switches into update mode.
- Update mode reuses the existing installation folder and skips shortcut/directory steps that are only needed for first install.
- Installer records install mode and installed version for future maintenance.
- The app fetches the latest 5 GitHub releases and builds the update changelog from their tags and notes.
- Update dialog now shows recent release history instead of only the latest release body.
- Release notes are cleaned into short readable lines before they are shown in the UI.


## 1.2.0.0 build-49 — Localization cleanup

- Replaced the old QMessageBox update prompt with a non-blocking FreeCleaner-styled update window.
- Added version comparison cards, installer asset details, release notes and the exact local update path.
- Added live download progress with percentage, downloaded/total size, speed and estimated time remaining.
- Added cancellation support for active update downloads.
- Kept GitHub Release open action available directly from the update window.
- The installer is launched only after the download finishes and the UI clearly shows the handoff state.
- Failed/cancelled downloads can be retried from the same window.


## Build 27 highlights

- Removed the per-file PowerShell cleanup fallback that caused `Test-Path -LiteralPath $args[0]` errors on Windows 11 when locked temp files were encountered.
- Cleanup now stays native: Python file removal, extended-path handling, and `MoveFileExW` scheduling for reboot-delete where appropriate. No cmd.exe/PowerShell recursion is used for normal temp-file deletion.
- Locked/in-use temp files are classified as `skipped_busy` instead of application errors, keeping `errors.log` focused on real FreeCleaner failures.
- `system.log` still records full cleanup totals, remaining files, skipped busy items, scheduled reboot deletes, and elapsed time for QA/debugging.
- Powercfg status probing reuses the active scheme GUID cache and stops probing `/GETACVALUEINDEX` after `/QUERY` proves an OEM setting block is hidden.
- Dynamic tick toggling is now idempotent: if BCDEdit already has the desired value, FreeCleaner logs a no-op instead of writing the same boot option repeatedly.
- Toggle and background QThreads are no longer parented to the main window, reducing cross-thread QObject ownership warnings during worker cleanup.

## Build 25 highlights

- `system.log` now includes a per-launch session id, process snapshot, Qt/FreeCleaner environment flags, command context, return code, stdout/stderr and elapsed time for system calls.
- Optional Windows probes are no longer written as application errors when the OS simply does not expose a setting. Their raw answers still stay in `system.log` for QA.
- BCDEdit status detection now falls back from `bcdedit /enum {current}` to plain `bcdedit /enum` and `bcdedit /enum all`, fixing the Windows 11 “specified entry type is invalid” case from the uploaded logs.
- Power profile status detection now falls back from `/GETACVALUEINDEX` to `/QUERY` and parses both output formats.
- Admin-only optimizer switches stay clickable in non-admin mode so the user gets an admin-required message instead of dead-looking controls.
- Startup/source launch path stays windowed through `app.pyw`/`pythonw`; packaged `.exe` remains `console=False`.
- Added `FreeCleaner.pyw` as a no-console source launcher for Windows double-click testing.

![Platform](https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-blue)
![Python](https://img.shields.io/badge/python-3.x-green)
![License](https://img.shields.io/badge/license-MIT-black)
![Status](https://img.shields.io/badge/status-active%20development-brightgreen)

FreeCleaner is a lightweight Windows desktop utility focused on cleaning temporary and non-essential files in a simple, clear, and privacy-friendly way.

The project is designed around a local-first workflow, understandable actions, and a clean desktop experience without unnecessary clutter.

---

## Overview

FreeCleaner helps users remove junk data, temporary files, and other low-value leftovers that build up over time on Windows systems.

The main goal of the project is not to become a bloated "all-in-one miracle optimizer," but to stay:

- simple
- readable
- local-first
- user-controlled
- practical for everyday use

The gaming optimizer is intentionally conservative. It can adjust Windows-level policies such as Game Mode, High Performance power profile, AC-only CPU/PCIe latency settings without forcing CPU min/max state, an optional maximum CPU latency/performance profile, Hardware-Accelerated GPU Scheduling registry flags, MMCSS gaming scheduling, Power Throttling policy, standby RAM cache cleanup, shader cache cleanup, and an optional dynamic-tick latency test. It does not overclock hardware, change voltages, disable thermal protection, edit fan curves, patch the kernel, or call vendor-specific GPU tuning APIs.

---

## Features

- Clean temporary and non-essential files
- Expanded Windows, browser, app, launcher, shader cache, Windows log, ProgramData/SystemTemp and packaged-app temp cleanup
- Safer cleanup traversal that skips symlinks/junctions instead of following them
- Safe gaming optimizer actions for Windows Game Mode, power policy, optional maximum CPU latency profile, GPU scheduling settings, MMCSS, Power Throttling, dynamic-tick testing, standby RAM cleanup, streaming diagnostics, OneDrive background-impact checks and a read-only gaming compatibility report
- Conservative registry leftovers cleanup for clearly broken Open With/Application, App Paths and startup entries, with registry backup before deletion
- UI filtering that hides empty sections and keeps large task lists easier to scan
- Full Qt / PySide6 interface with Home, Cleaner, Optimizer, Registry Safety, Diagnostics and Settings areas
- Cleaner dashboard shows the system drive label, letter and free/total capacity.
- Per-run QA logs are recreated in the FreeCleaner user-data `logs/` folder: `startup.log`, `app.log`, `errors.log`, `actions.log`, `security.log`, `system.log` and `qa.log`. `system.log` keeps raw Windows/HTTP/registry responses for debugging.
- Checkboxes for cleanup modules with dynamic selected-size estimates and instant switch-style controls for optimizer/registry tweaks initialized from real status
- Manual registry backup and guided restore flow for optimizer registry changes
- Local-first workflow
- Privacy-friendly design
- Built-in access to bundled project documents
- Support for custom language packs
- Lightweight structure focused on clarity and usability

---

## Why FreeCleaner

Many cleanup tools become overloaded with ads, confusing controls, background behavior, or unnecessary features.

FreeCleaner is built with a different approach:

- predictable behavior
- clear interface
- understandable cleanup actions
- no intentional hidden data collection
- easier customization and localization

In short: it tries to clean the PC, not the user’s patience.

---

## Screenshots

Add your screenshots here after publishing visuals for the project.

![Main Window](https://raw.githubusercontent.com/CraftRom/FreeCleaner/refs/heads/main/assets/screenshots/main-window.png)

---



## Cleanup scope notes

FreeCleaner targets rebuildable caches, temporary folders, logs and dumps. Newer cleanup coverage includes CryptnetUrlCache, IconCache.db, Windows user caches, Windows Update / WaaSMedic logs, setup/upgrade logs, WMI diagnostic ETL logs, ProgramData temp, Windows SystemTemp, DeviceMetadataCache, additional Delivery Optimization cache locations and conservative Microsoft Store packaged-app temp folders.

Registry cleanup is deliberately narrow. It does not touch COM, services, drivers, uninstall entries, shell extensions or broad file associations. It only removes clearly broken application/open-with/startup records that point to missing executable files and creates a registry backup first.


## OneDrive handling

FreeCleaner treats OneDrive as a background-impact component, not as a normal junk folder.

OneDrive actions are intentionally conservative:

- clean only OneDrive logs, setup logs, crash reports and rebuildable WebView/GPU caches;
- never delete the user's OneDrive sync folders or documents;
- provide a read-only OneDrive report for installed/running/autostart/policy/cache status;
- stop the current OneDrive process and remove current-user startup when the disable action is selected;
- enable the Windows OneDrive sync-blocking policy only when FreeCleaner is running with administrator rights;
- provide a restore action that removes that policy and starts OneDrive again when possible.

Account unlinking and uninstalling are left to the official OneDrive UI because forcing those steps from a cleaner can confuse users and break expected sync behavior.

## Streaming and OBS diagnostics

FreeCleaner includes read-only diagnostics for OBS and streaming workflows. It checks OBS profiles, selected encoders, recording format, Replay Buffer state, recent OBS logs, dropped-frame hints, encoder/rendering overload hints, current CPU/RAM/GPU pressure and a small temporary disk write test.

The diagnostics do not rewrite OBS profiles automatically. That is intentional: changing encoders, scenes, recording paths or containers without user review can break a working streaming setup. The tool reports findings so the user can adjust OBS deliberately.

## Windows 10/11 gaming optimizer notes

FreeCleaner does not assume that Windows secretly throttles older CPUs on purpose. The practical, user-controllable performance limiters are regular Windows policies and security features:

- **Power policy**: High Performance, EPP=0, boost policy, faster frequency ramp-up, core parking policy and PCIe ASPM can reduce power-saving latency when the PC is plugged in. FreeCleaner does not force CPU min/max state to 100%.
- **Maximum CPU latency/performance profile**: optional, not selected by default. It uses official `powercfg` aliases for AC-only EPP=0, aggressive boost, faster frequency ramp-up, unparked cores and PCIe ASPM off. This can help frametime consistency on some old and modern CPUs, but it can also increase heat and fan noise. Use it one change at a time and monitor temperatures.
- **Balanced rollback**: a separate action switches Windows back to the built-in Balanced power plan without deleting custom OEM plans.
- **Power Throttling / Efficiency behavior**: the advanced optimizer can disable the system-wide PowerThrottling registry policy, but this requires testing and a reboot.
- **MMCSS Games profile**: the app uses the documented lowest useful `SystemResponsiveness` value instead of the old `0` tweak, because Windows clamps invalid values.
- **HAGS**: Hardware-Accelerated GPU Scheduling is optional. Some systems benefit, others get stutter, so both enable and disable actions are available and protected from running together.
- **Dynamic tick**: the advanced `disabledynamictick=yes` task is only a latency experiment for problematic frametime jitter. Microsoft documents this BCDEdit option mainly as a debugging switch, so it is not selected by default and a restore-default action is included.
- **VBS / Memory integrity**: FreeCleaner only opens the official Windows Security page. It does not disable this automatically because it is a security trade-off, not a harmless cleanup tweak.

Recommended flow for gaming: apply the normal gaming profile first, reboot, test a real game session, then try advanced options one at a time. Do not stack every tweak blindly. For laptops, use the maximum CPU profile only when plugged in and temperatures are under control.

## Project Structure

A typical structure may look like this:

```text
FreeCleaner/
├─ app.py
├─ freecleaner/
│  ├─ app.py
│  ├─ design.py
│  ├─ logic.py
│  ├─ version_info.py
│  └─ ...
├─ lang/
│  └─ *.json
├─ assets/
│  ├─ icons/
│  └─ screenshots/
├─ LICENSE
├─ PRIVACY_POLICY.txt
└─ README.md
```

---

## Requirements

- Windows 10 or Windows 11
- Python 3.x
- Administrator rights for registry, power policy, DISM, BCDEdit and system cleanup actions
- Project dependencies required by the application

---

## Installation

### Run from source

Make sure Python is installed, then run:

```bash
python app.py
```

If the entry point is different in your setup, run the correct startup file for your project.

### Install dependencies

If the project includes a requirements file:

```bash
pip install -r requirements.txt
```

If not, install the dependencies manually according to the project modules you use.

---

## Build an executable

If you package FreeCleaner into an `.exe`, make sure all required assets are included:

- icons
- language files
- `LICENSE`
- `PRIVACY_POLICY.txt`
- images and other UI resources

Example with PyInstaller:

```bash
pyinstaller FreeCleaner.spec
```

Or:

```bash
pyinstaller --noconfirm --onefile --windowed app.py
```

Adjust the command to fit your real project structure.

---

## Custom Language Packs

FreeCleaner supports external JSON language files.

Each custom language file should include a `NAME` field used as the visible language name in the UI.

Example:

```json
{
  "NAME": "English",
  "app_title": "FreeCleaner",
  "close": "Close"
}
```

### Notes

- Built-in languages may be handled separately from external ones
- External language files should be placed in the correct language folder next to the application
- Translation keys should stay consistent with the application’s expected structure
- User-friendly naming is recommended for public distributions

---

## Documents

FreeCleaner includes bundled project documents that can be opened from the application:

- **LICENSE** — explains how the software may be used and distributed
- **PRIVACY_POLICY.txt** — explains what the app does and does not do with user data

---

## Privacy

FreeCleaner is designed to work locally on the user’s PC.

It does **not** intentionally upload personal files, cleanup results, or private documents to external servers.

Typical operations are performed locally and only for the cleanup actions selected by the user.

For more details, see:

- `PRIVACY_POLICY.txt`
- `LICENSE`

---

## Main Principles

- **Local first** — cleanup happens on the user’s device
- **User control** — the user decides what to run
- **Clear UI** — no hidden magic and no unnecessary clutter
- **Readable documentation** — bundled documents are easy to access
- **Extensible languages** — translations can be added through JSON files

---

## Current Focus

Current development priorities include:

- improving UI clarity
- expanding safe cleanup targets without touching personal data
- refining quick profiles so they do not duplicate each other
- improving cleanup safety around protected links, junctions, and system paths
- improving rendering performance
- keeping language packs complete and easy to maintain
- keeping the project lightweight and understandable

---

## Limitations

FreeCleaner is not intended to be:

- a cloud sync utility
- a remote monitoring tool
- an antivirus
- a full replacement for professional enterprise maintenance tools

It is a focused desktop cleanup utility.

---

## FAQ

### Does FreeCleaner upload my files?

No. FreeCleaner is designed as a local-first desktop utility and is not intended to upload your personal files as part of normal usage.

### Does it require an account?

No. FreeCleaner does not require an account for local use.

### Can I add my own language?

Yes. External JSON language packs can be added if they follow the expected translation key structure.

### Is it safe to use?

It is designed to be simple and transparent, but users should always review cleanup actions before confirming deletion.

### Can I build it into an `.exe`?

Yes. A packaged executable can be built with tools such as PyInstaller, as long as required resources are included.

---

## Contributing

Contributions, improvements, bug reports, UI suggestions, and translation updates are welcome.

You can contribute by:

- reporting bugs
- improving translations
- refining the interface
- optimizing performance
- improving documentation

---

## License

This project is licensed under the MIT License.

See the `LICENSE` file for details.

## Windows 32-bit / 64-bit builds

FreeCleaner supports both Windows x86 and x64 targets for Windows 10/11 compatibility:

- `*-win64.exe` is built with 64-bit Python and is intended for 64-bit Windows 10/11.

The application also detects whether it is running as a 32-bit process on 64-bit Windows (WOW64), so path discovery can correctly distinguish native x64, native x86, and WOW64 environments.

## Windows installer builds

The release workflow now produces both portable EXE files and installable setup files:

- `FreeCleaner-<version>-win64.exe` — portable 64-bit executable.
- `FreeCleaner-<version>-win64-setup.exe` — installer for 64-bit Windows only.

The installer is built with Inno Setup and includes:

- installation into `Program Files` / `Program Files (x86)` depending on architecture;
- Start Menu shortcut;
- optional Desktop shortcut;
- uninstall entry in Windows “Programs and Features”;
- license page;
- admin privileges, because cleaner functions need system-level access.

Manual installer build after PyInstaller:

```powershell
.\scripts\build_installer.ps1 `
  -ExePath "dist\FreeCleaner-0.2.0.0-build-1-win64.exe" `
  -Arch "win64" `
  -Version "0.2.0.0-build-1" `
  -OutputDir "dist"
```


## User-writable runtime data

Installed copies can live under `C:\Program Files`, which is read-only for normal users.
FreeCleaner therefore stores mutable runtime data in the current user's local data folder instead of the installation directory:

- config: `%LOCALAPPDATA%\FreeCleaner\config.json`;
- update downloads: `%LOCALAPPDATA%\FreeCleaner\updates`;
- registry backups: `%LOCALAPPDATA%\FreeCleaner\registry_backups`.

This lets update downloads complete without administrator rights. Windows may still show a UAC prompt when the downloaded installer starts, because replacing files under `Program Files` requires elevation.

## Update asset selection

The in-app updater selects the installer by the current Windows architecture:

- 32-bit Windows is not supported by the PySide6/Qt build.
- 64-bit Windows downloads `FreeCleaner-<version>-win64-setup.exe`.
- 64-bit Windows downloads `FreeCleaner-<version>-win64-setup.exe`.

The updater avoids downloading an incompatible `win64-setup.exe` on 32-bit Windows.

## Adaptive scan/clean threading

FreeCleaner now chooses worker counts dynamically instead of using fixed limits:

- Scan starts around half of logical CPU threads because scanning is mostly disk-bound.
- Cleaning starts at logical CPU threads minus two to keep Windows responsive.
- During work, each batch re-checks CPU and RAM pressure through Windows APIs and reduces workers on loaded systems.
- No extra runtime dependency is required; the logic remains compatible with Python 3.8+ and Windows 10/11.

## Diagnostics dashboard

FreeCleaner includes a read-only **Diagnostics** tab for gaming and streaming checks.
It does not change OBS profiles, Windows registry values, power plans, scenes, or recording settings automatically.

The dashboard shows cards for:

- OBS profiles, stream/record encoders, recording format, Replay Buffer and recent overload/NVENC issues;
- Windows Game Mode, Captures/Game DVR, HAGS, active power plan and per-app GPU preference entries;
- quick write-speed test for the OBS recording folder or the system temp folder;
- dropped-frame warnings found in recent OBS logs;
- practical recommendations that avoid unsafe one-click tweak behavior.


## Cleanup engine and conflict handling

Recent stability improvements focus on doing less duplicate work while keeping cleanup safe:

- directory task paths are normalized and cached so analysis and cleanup do not repeatedly resolve the same targets;
- scan and clean operations use one adaptive worker pool per run phase instead of repeatedly creating short-lived pools;
- OneDrive disable actions run before cache cleanup when selected, which reduces locked files without deleting synced user data;
- mutually exclusive optimizer actions are resolved before execution, including HAGS on/off, dynamic tick custom/default and competing power-plan profiles;
- the OneDrive cleanup category is included in analysis summaries so estimates no longer fall into an untranslated/mixed category.

The cleaner still preserves target root folders, skips symlinks/junctions/reparse points, and avoids deleting user documents or OneDrive sync folders.

## Modern Qt UI performance layer

The UI layer now uses PySide6/Qt instead of the old legacy UI frontend:

- one Qt application layer (`freecleaner.qt_app`) is used for startup and builds;
- cleanup work stays off the UI thread through `QThread` workers;
- cleanup modules use checkbox rows, while optimizer/settings actions use switch controls;
- task rows cache translated title/description text for search and filtering;
- registry switches sync against the real current registry state before display;
- admin-only and unsupported actions have separate visual states instead of looking broken.

## Earlier Qt migration — Qt UI rebuild

- Primary frontend moved to PySide6/Qt.
- Removed Quick profiles completely.
- Rebuilt the interface into Cleaner, Optimizer, Registry safety, Diagnostics and Settings pages.
- Cleanup modules use checkboxes; optimizer tweaks use switch controls.
- Registry tweak switches read current registry state and show whether the target value is already applied.
- Registry backup/restore is now a dedicated safety page.

## Earlier Qt build — full Qt migration polish

- Added a Qt splash screen for startup.
- Updated the UI closer to a modern NVIDIA-App-style layout: compact left rail, dark surfaces, green active accent, right-side toggles and flat section rows.
- Restored visible app functions in the Qt interface: license, privacy policy, update check, admin relaunch, config folder, diagnostics, registry backup and registry restore.
- Added visual status pills for available, admin-only, applied and unavailable actions.
- Added animated switches and page fade transitions.
- Updated runtime requirement to the PySide6 6.11.x line on Python 3.10+ x64/ARM64 supported wheels.


## Build 17 notes

- Startup now uses a lightweight Qt bootstrap so the splash appears before heavy imports.
- High DPI policy is applied before `QApplication`, removing the Qt warning.
- Splash and toast animations no longer use unsafe signal disconnects.
- Side navigation uses generated original SVG icons in `assets/icons/nav`.
- Optimizer switches execute immediately; the old duplicate “apply selected tweaks” button was removed.
- Cleaner checkbox changes update selected count and estimated selected cleanup size dynamically.
- Diagnostics now uses separate system/gaming/streaming/OneDrive cards.


## Build 19

- Removed the grey main-window flash behind the splash by delaying the main window show until the splash fade starts closing.
- Guarded Qt high-DPI setup so it is never called after QApplication already exists.
- Added `app.pyw` for source GUI launches without a console window on Windows.
- Centralized hidden subprocess startup options for Windows helper commands.
- Fixed optimizer toggles that stayed visually disabled after a worker finished.
- Deferred registry/power status sync until controls are re-enabled.
- Admin-only optimizer toggles remain clickable and revert with a clear admin-required message instead of looking broken.
- Improved power-plan recognition using `powercfg /GETACVALUEINDEX` for AC settings when available.



## 0.2.1.0 build-37 — Home tiles, UI animations and nav icon stability

- Made every Home dashboard block a full clickable navigation card instead of relying on a small text link.
- Added lightweight fade-in/fade-out animations for page switches, toast notifications, Home cards and filtered task rows.
- Added `FREECLEANER_DISABLE_UI_ANIMATIONS=1` as a fallback for problematic GPU/Qt environments.
- Cached and re-applied side navigation icons after minimize/restore/application state changes to prevent missing icons.
- Kept fallback glyphs for nav buttons if an SVG/PNG asset cannot be loaded.


## 0.2.1.0 build-36 — Home header admin button cleanup

- Removed the duplicate admin access status pill from the Home hero header.
- Kept the administrator action button in the same header position.
- Left other admin status indicators and settings controls unchanged.

## 0.2.1.0 build-35 — CI PySide6 packaging compatibility

- Fixed GitHub Actions dependency installation by moving release builds from Python 3.8 to Python 3.13.
- Removed the unsupported Windows x86/win32 build matrix entry for the Qt/PySide6 package.
- Kept `PySide6==6.11.1` but now installs it only on supported Python `>=3.10,<3.15` runtimes.
- Switched dependency install commands to `python -m pip ...` so the workflow always uses the selected setup-python interpreter.
- Updated release documentation to describe the current x64-only Windows build path.



## 0.2.1.0 build-45 — Native splash name/version and paint stability

- Shows the application name and exact package version directly on the native startup splash.
- Fixes Win32 GDI paint API prototypes so 64-bit HBRUSH/HFONT handles are not truncated during `WM_PAINT`.
- Prevents repeated ctypes callback tracebacks from escaping splash painting.
- Keeps the quiet native splash visible while PySide6 and Qt modules are prepared.

## 0.2.1.0 build-41 — Native splash Python 3.13 handle fix

- Fixed native Win32 splash creation on Python 3.13 where `ctypes.wintypes.HCURSOR` may be missing.
- Added explicit fallback handle aliases for `HICON`, `HCURSOR`, `HBRUSH`, `HWND` and `HINSTANCE`.
- Pinned Win32 API return types and arguments for 64-bit-safe `HWND`/GDI handle usage.
- Fixed `LoadCursorW(IDC_ARROW)` so the integer resource is passed as a raw pointer, not as a Unicode string.
- Prevented the app from falling back to the flickery Qt splash because of Python ctypes metadata differences.

## 0.2.1.0 build-40 — Quiet native Qt startup splash

- show a silent native Win32 splash before importing PySide6/Qt modules;
- keep the splash visible while QApplication, QtWidgets and the full FreeCleaner UI are prepared;
- prevent the splash from disappearing during “Підготовка модулів Qt…”;
- avoid taskbar/activation flicker by using a no-activate toolwindow splash;
- close the splash only after the main Qt window is constructed and ready to show;
- keep a Qt splash fallback for non-Windows/source environments.

## 0.2.1.0 build-39 — Startup splash flicker guard

- Kept the bootstrap splash as a single native splash window without Tool/topmost owner transitions.
- Processed one safe paint pass before heavy Qt module import so the splash is stable during startup.
- Delayed global Qt stylesheet application until after the splash is closed and before the main window is shown.
- Reworded the startup progress sequence so Qt module preparation is displayed before importing the full UI.
- Reduced QPA startup logging noise that could surface as transient background activity in source/debug runs.

## 0.2.1.0 build-38 — Settings UX, config toggles and UI polish

- Rebuilt Settings into clearer Interface, Startup, Safety, Notifications, Info and License tabs.
- Added UI controls for settings that were previously only configurable through config keys or environment flags: UI animations, animation duration, startup status sync, startup update gate and background worker limit.
- Kept existing controls for auto update checks, heavy-action confirmations, compact UI logs and notification behavior, but moved them into more logical sections.
- Runtime flags now apply from config at startup and update live where safe.
- Added clickable setting cards with hover/pressed states and lightweight fade-in polish.
- Background diagnostics/update/registry job limit is now configurable from Settings instead of being hardcoded.
- Compact event log mode now hides noisy helper command lines from the visible UI log while retaining full disk logs for QA.