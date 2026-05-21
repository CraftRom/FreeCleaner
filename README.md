# FreeCleaner

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
- Expanded Windows, browser, app, launcher, shader cache, Windows log and packaged-app temp cleanup
- Safer cleanup traversal that skips symlinks/junctions instead of following them
- Quick profiles: Safe, Gaming cleanup, and Deep cleanup
- Safe gaming optimizer actions for Windows Game Mode, power policy, optional maximum CPU latency profile, GPU scheduling settings, MMCSS, Power Throttling, dynamic-tick testing and standby RAM cleanup
- Conservative registry leftovers cleanup for clearly broken Open With/Application, App Paths and startup entries, with registry backup before deletion
- UI filtering that hides empty sections and keeps large task lists easier to scan
- Simple desktop interface
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

FreeCleaner targets rebuildable caches, temporary folders, logs and dumps. Newer cleanup coverage includes CryptnetUrlCache, IconCache.db, Windows user caches, Windows Update / WaaSMedic logs, setup/upgrade logs, WMI diagnostic ETL logs, additional Delivery Optimization cache locations and conservative Microsoft Store packaged-app temp folders.

Registry cleanup is deliberately narrow. It does not touch COM, services, drivers, uninstall entries, shell extensions or broad file associations. It only removes clearly broken application/open-with/startup records that point to missing executable files and creates a registry backup first.

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
pyinstaller app.spec
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

- `*-win32.exe` is built with 32-bit Python and is intended for 32-bit Windows 10/11 or compatibility fallback on 64-bit Windows.
- `*-win64.exe` is built with 64-bit Python and is intended for 64-bit Windows 10/11.

The application also detects whether it is running as a 32-bit process on 64-bit Windows (WOW64), so path discovery can correctly distinguish native x64, native x86, and WOW64 environments.

## Windows installer builds

The release workflow now produces both portable EXE files and installable setup files:

- `FreeCleaner-<version>-win32.exe` — portable 32-bit executable.
- `FreeCleaner-<version>-win64.exe` — portable 64-bit executable.
- `FreeCleaner-<version>-win32-setup.exe` — installer for 32-bit Windows and compatible 64-bit systems.
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

- 32-bit Windows downloads `FreeCleaner-<version>-win32-setup.exe`.
- 64-bit Windows downloads `FreeCleaner-<version>-win64-setup.exe`.
- If the native x64 installer is missing, 64-bit Windows can fall back to `FreeCleaner-<version>-win32-setup.exe` because the 32-bit installer is compatible.

The updater avoids downloading an incompatible `win64-setup.exe` on 32-bit Windows.

## Adaptive scan/clean threading

FreeCleaner now chooses worker counts dynamically instead of using fixed limits:

- Scan starts around half of logical CPU threads because scanning is mostly disk-bound.
- Cleaning starts at logical CPU threads minus two to keep Windows responsive.
- During work, each batch re-checks CPU and RAM pressure through Windows APIs and reduces workers on loaded systems.
- No extra runtime dependency is required; the logic remains compatible with Python 3.8+ and Windows 10/11.
