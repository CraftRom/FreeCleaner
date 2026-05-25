"""Application layer: UI (CustomTkinter) for FreeCleaner.

This module contains UI code only and imports core logic from freecleaner.logic.
"""

from __future__ import annotations

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import os
import ctypes
import threading
import time
import concurrent.futures
import subprocess
import re
import queue
import json
import locale
from datetime import datetime
from typing import Callable, Dict, List, Tuple, Optional, Sequence, Any

try:
    import winreg  # type: ignore
except Exception:  # pragma: no cover
    winreg = None  # type: ignore

from .design import COLORS, SummaryCard, SectionCard, ModernTabButton, AnimatedButton, DiagnosticStatusCard, init_ui_theme, mix_colors
from .logic import (
    IS_WINDOWS,
    ICONS_DIRNAME,
    LANG_PACKS,
    LANG_PACK_SOURCES,
    APP_VERSION,
    APP_VERSION_RAW,
    CONFIG_PATH,
    LEGACY_CONFIG_PATH,
    CleanerTask,
    RegistryValueSpec,
    PathFinder,
    WindowsOps,
    SafeFS,
    UpdateInfo,
    compare_versions,
    fetch_latest_github_release,
    download_url_to_file,
    guess_download_filename,
    get_updates_dir,
    get_update_download_path,
    cleanup_old_update_files,
    is_installable_update_file,
    launch_update_installer,
    schedule_update_cleanup_after_install,
    SCAN_WORKERS,
    CLEAN_WORKERS,
    get_adaptive_workers,
    get_adaptive_thread_status,
    get_runtime_base_dir,
    get_bundle_base_dir,
    find_icon_path,
    language_display_name,
)

# Initialize CTk appearance/theme once on import (safe to call multiple times).
init_ui_theme()

class Cleaner(ctk.CTk):

    def _normalize_ui_text(self, text: str) -> str:
        if not isinstance(text, str):
            return text
        return text.replace("\r\n", "\n").replace("\\n", "\n").replace("\\t", "\t")

    def _icon_candidates(self) -> List[str]:
        ordered: List[str] = []
        for name in ("app_16.ico", "app.ico", "app.png"):
            path = find_icon_path(name)
            if path and path not in ordered:
                ordered.append(path)
        return ordered

    def _apply_icon_to_window(self, win, *, default: bool = False) -> None:
        try:
            if not win or not win.winfo_exists():
                return
        except Exception:
            return

        try:
            if IS_WINDOWS:
                try:
                    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FreeCleaner.App")
                except Exception:
                    pass

            for path in self._icon_candidates():
                lower = path.lower()
                if lower.endswith(".ico") and IS_WINDOWS:
                    try:
                        if default:
                            win.iconbitmap(default=path)
                        else:
                            win.iconbitmap(path)
                    except Exception:
                        pass
                    try:
                        win.wm_iconbitmap(path)
                    except Exception:
                        pass

                if lower.endswith(".png"):
                    try:
                        import tkinter as tk
                        photo = tk.PhotoImage(file=path)
                        if default:
                            self._icon_image_ref = photo
                        else:
                            win._icon_image_ref = photo  # type: ignore[attr-defined]
                        try:
                            win.iconphoto(True, photo)
                        except Exception:
                            pass
                        try:
                            win.tk.call("wm", "iconphoto", win._w, photo)
                        except Exception:
                            pass
                    except Exception:
                        pass
        except Exception:
            pass

    def apply_window_icon(self):
        """Apply program icon to the main window/taskbar."""
        self._apply_icon_to_window(self, default=True)
        try:
            self.after(80, lambda: self._apply_icon_to_window(self, default=True))
        except Exception:
            pass

    def load_config(self) -> Dict[str, str]:
        for path in (CONFIG_PATH, LEGACY_CONFIG_PATH):
            try:
                if not path or not os.path.isfile(path):
                    continue
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    # Migrate legacy install-dir config to the per-user writable path.
                    if os.path.abspath(path) != os.path.abspath(CONFIG_PATH):
                        try:
                            folder = os.path.dirname(CONFIG_PATH)
                            if folder:
                                os.makedirs(folder, exist_ok=True)
                            tmp_path = f"{CONFIG_PATH}.tmp"
                            with open(tmp_path, "w", encoding="utf-8") as fh:
                                json.dump(data, fh, ensure_ascii=False, indent=2)
                                fh.write("\n")
                            os.replace(tmp_path, CONFIG_PATH)
                        except Exception:
                            pass
                    return data
            except Exception:
                continue
        return {}


    def save_config(self):
        try:
            data = dict(getattr(self, "config", {}) or {})
            data["language"] = getattr(self, "lang_preference", "auto")
            folder = os.path.dirname(CONFIG_PATH)
            if folder:
                os.makedirs(folder, exist_ok=True)
            tmp_path = f"{CONFIG_PATH}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(tmp_path, CONFIG_PATH)
            self.config = data
        except Exception:
            pass


    def normalize_language_preference(self, value: Optional[str]) -> str:
        code = (value or "auto").strip().lower()
        if code == "auto":
            return "auto"
        return code if code in LANG_PACKS else "auto"

    def _normalize_search_text(self, value: str) -> str:
        """Normalize text once for cheaper, language-friendly UI filtering."""
        text = self._normalize_ui_text(value or "")
        return re.sub(r"\s+", " ", text.casefold()).strip()


    def __init__(self):
        super().__init__()
        self.config = self.load_config()
        self.lang_preference = self.normalize_language_preference(self.config.get("language", "auto"))
        self.lang = self.detect_initial_language()
        self.title(self.app_title())
        self.configure(fg_color=COLORS["bg_main"])
        self._layout_state: Dict[str, Any] = {}
        self.configure_window_geometry()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._responsive_after_id = None
        self._log_line_count = 0
        self._max_log_lines = 900
        self._progress_after_id = None
        self._pending_progress: Optional[Tuple[float, Optional[float]]] = None
        self._progress_target_value = 0.0
        self._progress_display_value = 0.0
        self._progress_anim_after_id = None
        self._running_pulse_after_id = None
        self._running_pulse_phase = 0
        self._selection_refresh_suspended = False
        self._search_after_id = None
        self._last_search_query = ""
        self._about_header_icon_cache = None
        self.active_module_tab = "cleaner"
        self._diagnostics_in_progress = False
        self._last_diagnostics_report: Dict[str, Any] = {}
        self._update_check_in_progress = False
        self._last_update_info: Optional[UpdateInfo] = None
        self._ignored_update_tag = ""
        self._update_download_in_progress = False
        self._update_download_cancel: Optional[threading.Event] = None
        self.apply_window_icon()
        self.after(45, lambda: self.fade_in_window(self))

        self.is_admin = WindowsOps.is_admin()
        self.vars: Dict[str, ctk.BooleanVar] = {}
        self.tasks: Dict[str, CleanerTask] = {}
        self.section_cards: List[SectionCard] = []
        self.total_lock = threading.Lock()
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.cancel_event = threading.Event()
        self.is_running = False
        self.cleaned_bytes = 0
        self.total_size_bytes = 0
        self.analysis_total_bytes = 0
        self._last_progress_ui_at = 0.0
        self._last_progress_ui_bytes = 0
        self.last_analysis: Dict[str, int] = {}
        self.dism_running = False
        self.current_profile_name = self.tr("profile_manual")

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.build_sidebar()
        self.build_main_area()
        self.build_footer()
        self.bind("<Configure>", self.on_window_configure)
        self.after(120, self.flush_log_queue)
        self.after(180, self.refresh_responsive_layout)

        self.log(self.trf("app_started", title=self.app_title()))
        initial_scan_workers = get_adaptive_workers("scan")
        initial_clean_workers = get_adaptive_workers("clean")
        self.log(self.trf("threads_info", scan=initial_scan_workers, clean=initial_clean_workers))
        self.log(self.trf("adaptive_threads_fmt", status=get_adaptive_thread_status("scan")))
        self.log(self.tr("mode_admin") if self.is_admin else self.tr("mode_limited"))
        self.refresh_selection_stats()
        self.apply_language()
        self.after(900, lambda: self.cleanup_stale_update_files(silent=True))
        self.after(1400, lambda: self.check_for_updates(silent_if_latest=True, source="startup"))


    def _apply_dynamic_ui_scaling(self, screen_w: int, screen_h: int) -> None:
        """Keep the UI readable on small notebooks and sharper on large monitors."""
        try:
            if screen_w <= 1180 or screen_h <= 720:
                scale = 0.90
            elif screen_w >= 2200 and screen_h >= 1200:
                scale = 1.06
            elif screen_w >= 1700 and screen_h >= 950:
                scale = 1.02
            else:
                scale = 1.0
            if self._layout_state.get("ui_scale") != scale:
                ctk.set_widget_scaling(scale)
                self._layout_state["ui_scale"] = scale
        except Exception:
            pass

    def configure_window_geometry(self):
        screen_w = max(900, int(self.winfo_screenwidth() or 1366))
        screen_h = max(620, int(self.winfo_screenheight() or 768))
        self._apply_dynamic_ui_scaling(screen_w, screen_h)

        usable_w = max(860, screen_w - 40)
        usable_h = max(560, screen_h - 72)
        if screen_w >= 1800:
            preferred_w = 1420
        elif screen_w >= 1500:
            preferred_w = 1320
        elif screen_w >= 1280:
            preferred_w = 1160
        else:
            preferred_w = int(usable_w * 0.96)

        if screen_h >= 1000:
            preferred_h = 900
        elif screen_h >= 820:
            preferred_h = 780
        else:
            preferred_h = int(usable_h * 0.94)

        target_w = min(usable_w, max(940, preferred_w))
        target_h = min(usable_h, max(620, preferred_h))
        min_w = min(target_w, 940 if screen_w >= 1280 else 860)
        min_h = min(target_h, 620 if screen_h >= 760 else 560)

        pos_x = max(0, (screen_w - target_w) // 2)
        pos_y = max(0, (screen_h - target_h) // 2)

        self.geometry(f"{target_w}x{target_h}+{pos_x}+{pos_y}")
        self.minsize(min_w, min_h)

    def configure_toplevel_geometry(self, win: ctk.CTkToplevel, preferred: Sequence[int], minimum: Sequence[int]) -> None:
        screen_w = max(640, int(self.winfo_screenwidth() or preferred[0]))
        screen_h = max(520, int(self.winfo_screenheight() or preferred[1]))
        usable_w = max(520, screen_w - 48)
        usable_h = max(420, screen_h - 88)

        pref_w, pref_h = int(preferred[0]), int(preferred[1])
        min_w = min(pref_w, max(420, int(minimum[0])))
        min_h = min(pref_h, max(360, int(minimum[1])))
        width = min(pref_w, max(min_w, int(usable_w * 0.86)))
        height = min(pref_h, max(min_h, int(usable_h * 0.86)))
        pos_x = max(0, (screen_w - width) // 2)
        pos_y = max(0, (screen_h - height) // 2)

        win.geometry(f"{width}x{height}+{pos_x}+{pos_y}")
        win.minsize(min_w, min_h)
        self.fade_in_window(win, start=0.92, step=0.04)

    def fade_in_window(self, win, *, start: float = 0.94, step: float = 0.03) -> None:
        """Small opacity transition. It is cheap and ignored on platforms that reject alpha."""
        try:
            if not win or not win.winfo_exists():
                return
            win.attributes("-alpha", start)
        except Exception:
            return

        def tick(value: float) -> None:
            try:
                if not win.winfo_exists():
                    return
                value = min(1.0, value + step)
                win.attributes("-alpha", value)
                if value < 1.0:
                    win.after(16, lambda: tick(value))
            except Exception:
                pass

        try:
            win.after(16, lambda: tick(start))
        except Exception:
            pass

    def schedule_responsive_layout(self):
        pending = getattr(self, "_responsive_after_id", None)
        if pending:
            try:
                self.after_cancel(pending)
            except Exception:
                pass
        self._responsive_after_id = self.after(70, self.refresh_responsive_layout)

    def on_window_configure(self, event=None):
        if event is not None and getattr(event, "widget", None) is not self:
            return
        try:
            size_key = (int(self.winfo_width() or 0), int(self.winfo_height() or 0))
            last_size = self._layout_state.get("last_root_size")
            if last_size and abs(last_size[0] - size_key[0]) < 8 and abs(last_size[1] - size_key[1]) < 8:
                return
            self._layout_state["last_root_size"] = size_key
        except Exception:
            pass
        self.schedule_responsive_layout()

    def layout_summary_cards(self, columns: int, compact: bool = False):
        cards = [
            self.card_selected,
            self.card_profile,
            self.card_estimate,
            self.card_admin,
        ]
        columns = 4 if columns >= 4 else 2 if columns >= 2 else 1
        compact = bool(compact)
        for card in cards:
            try:
                card.set_compact(compact)
            except Exception:
                pass
        state = (columns, compact)
        if self._layout_state.get("summary_columns") == state:
            return
        self._layout_state["summary_columns"] = state

        for card in cards:
            card.grid_forget()

        for idx in range(4):
            self.summary_top.grid_columnconfigure(idx, weight=0)
        for idx in range(columns):
            self.summary_top.grid_columnconfigure(idx, weight=1)

        for index, card in enumerate(cards):
            row = index // columns
            column = index % columns
            pad_x = (0, 10) if column < columns - 1 else (0, 0)
            pad_y = (0, 10) if columns == 1 or (columns == 2 and row == 0) else (0, 0)
            card.grid(row=row, column=column, sticky="ew", padx=pad_x, pady=pad_y)

    def layout_toolbar(self, compact: bool):
        compact = bool(compact)
        if self._layout_state.get("toolbar_compact") == compact:
            return
        self._layout_state["toolbar_compact"] = compact

        if compact:
            self.search_label.grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 6))
            self.search_entry.grid(row=1, column=0, sticky="ew", padx=(14, 10), pady=(0, 10))
            self.btn_clear_search.grid(row=1, column=1, sticky="ew", padx=(0, 14), pady=(0, 10))
            self.toolbar.grid_columnconfigure(0, weight=1)
            self.toolbar.grid_columnconfigure(1, weight=0)
            self.toolbar.grid_columnconfigure(2, weight=0)
        else:
            self.search_label.grid(row=0, column=0, columnspan=1, sticky="w", padx=14, pady=12)
            self.search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=10)
            self.btn_clear_search.grid(row=0, column=2, sticky="ew", padx=(0, 12), pady=10)
            self.toolbar.grid_columnconfigure(0, weight=0)
            self.toolbar.grid_columnconfigure(1, weight=1)
            self.toolbar.grid_columnconfigure(2, weight=0)

    def layout_action_buttons(self, stacked: bool):
        stacked = bool(stacked)
        if self._layout_state.get("buttons_stacked") == stacked:
            return
        self._layout_state["buttons_stacked"] = stacked

        buttons = [self.btn_start, self.btn_analyze, self.btn_reset_all]
        for button in buttons:
            button.pack_forget()

        btn_height = 42 if stacked else 48
        self.btn_start.configure(height=btn_height, font=("Segoe UI", 15 if stacked else 16, "bold"))
        self.btn_analyze.configure(height=btn_height, font=("Segoe UI", 13 if stacked else 14, "bold"), width=148 if stacked else 160)
        self.btn_reset_all.configure(height=btn_height, font=("Segoe UI", 13 if stacked else 14, "bold"), width=140 if stacked else 150)

        if stacked:
            for button in buttons:
                button.pack(fill="x", pady=(0, 8))
        else:
            self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 8))
            self.btn_analyze.pack(side="left", padx=(0, 8))
            self.btn_reset_all.pack(side="left")

    def layout_tab_bar(self, stacked: bool, subtitle_wrap: int):
        stacked = bool(stacked)
        subtitle_wrap = max(180, int(subtitle_wrap))
        state = (stacked, subtitle_wrap)
        if self._layout_state.get("tab_layout") == state:
            return
        self._layout_state["tab_layout"] = state

        buttons = [self.tab_cleaner_button, self.tab_optimizer_button, self.tab_diagnostics_button]
        for button in buttons:
            button.grid_forget()
        for column in range(3):
            self.tab_bar.grid_columnconfigure(column, weight=1)

        if stacked:
            for column in range(1, 3):
                self.tab_bar.grid_columnconfigure(column, weight=0)
            for index, button in enumerate(buttons):
                pady = (12, 8) if index == 0 else (0, 8) if index == 1 else (0, 12)
                button.grid(row=index, column=0, sticky="ew", padx=12, pady=pady)
        else:
            pads = [(12, 7), (7, 7), (7, 12)]
            for index, button in enumerate(buttons):
                button.grid(row=0, column=index, sticky="ew", padx=pads[index], pady=12)

        for button in buttons:
            button.set_subtitle_wrap(subtitle_wrap)
            button.set_compact(stacked)

    def layout_sidebar_bottom(self, stacked: bool):
        stacked = bool(stacked)
        if self._layout_state.get("sidebar_bottom_stacked") == stacked:
            return
        self._layout_state["sidebar_bottom_stacked"] = stacked

        for button in (self.btn_copy_log, self.btn_clear_log, self.btn_cancel):
            button.pack_forget()

        if stacked:
            self.btn_copy_log.pack(fill="x", pady=(0, 8))
            self.btn_clear_log.pack(fill="x", pady=(0, 8))
            self.btn_cancel.pack(fill="x")
        else:
            self.btn_copy_log.pack(side="left")
            self.btn_clear_log.pack(side="left", padx=8)
            self.btn_cancel.pack(side="right")

    def module_tab_title(self, key: str) -> str:
        if key == "optimizer":
            return self.tr("tab_optimizer")
        if key == "diagnostics":
            return self.tr("tab_diagnostics")
        return self.tr("tab_cleaner")

    def module_tab_subtitle(self, key: str) -> str:
        if key == "optimizer":
            return self.tr("tab_optimizer_sub")
        if key == "diagnostics":
            return self.tr("tab_diagnostics_sub")
        return self.tr("tab_cleaner_sub")

    def on_module_tab_changed(self, key: str):
        self.show_module_tab(key)

    def show_module_tab(self, key: str):
        key = key if key in {"cleaner", "optimizer", "diagnostics"} else "cleaner"
        self.active_module_tab = key

        if hasattr(self, "cleaner_scroll") and hasattr(self, "optimizer_scroll") and hasattr(self, "diagnostics_scroll"):
            self.cleaner_scroll.grid_remove()
            self.optimizer_scroll.grid_remove()
            self.diagnostics_scroll.grid_remove()
            if key == "optimizer":
                self.optimizer_scroll.grid()
            elif key == "diagnostics":
                self.diagnostics_scroll.grid()
            else:
                self.cleaner_scroll.grid()

        if hasattr(self, "tab_cleaner_button"):
            self.tab_cleaner_button.set_active(key == "cleaner")
        if hasattr(self, "tab_optimizer_button"):
            self.tab_optimizer_button.set_active(key == "optimizer")
        if hasattr(self, "tab_diagnostics_button"):
            self.tab_diagnostics_button.set_active(key == "diagnostics")

        self.schedule_responsive_layout()

    def refresh_responsive_layout(self):
        try:
            self._responsive_after_id = None
            width = max(int(self.winfo_width() or 0), int(self.winfo_reqwidth() or 0), 860)
            height = max(int(self.winfo_height() or 0), int(self.winfo_reqheight() or 0), 560)

            compact_window = width < 1240 or height < 760
            tight_window = width < 1060 or height < 700
            sidebar_width = 370 if width >= 1600 else 338 if width >= 1420 else 306 if width >= 1240 else 276 if width >= 1060 else 246
            footer_height = 188 if height >= 900 else 166 if height >= 760 else 146 if height >= 670 else 132
            content_width = max(300, width - sidebar_width - (58 if compact_window else 78))
            wraplength = max(280, min(980, content_width - (96 if compact_window else 120)))
            main_pad_x = 18 if not compact_window else 12 if not tight_window else 8
            main_pad_y = 18 if not compact_window else 12 if not tight_window else 8
            tab_stacked = content_width < 720
            tab_subtitle_wrap = max(180, min(380, content_width // (1 if tab_stacked else 2) - 54))

            if self._layout_state.get("sidebar_width") != sidebar_width:
                self._layout_state["sidebar_width"] = sidebar_width
                self.sidebar.configure(width=sidebar_width)
            if self._layout_state.get("sidebar_compact") != tight_window:
                self._layout_state["sidebar_compact"] = tight_window
                self.brand_label.configure(font=("Segoe UI Black", 24 if tight_window else 30))
                self.app_subtitle.configure(font=("Segoe UI", 10 if tight_window else 12), wraplength=max(180, sidebar_width - 42))
                self.event_log_label.configure(font=("Segoe UI", 11 if tight_window else 12, "bold"))
                self.console.configure(font=("Consolas", 10 if tight_window else 11))
            if self._layout_state.get("footer_height") != footer_height:
                self._layout_state["footer_height"] = footer_height
                self.footer.configure(height=footer_height)
            if self._layout_state.get("main_padding") != (main_pad_x, main_pad_y):
                self._layout_state["main_padding"] = (main_pad_x, main_pad_y)
                self.main_wrap.grid_configure(padx=main_pad_x, pady=main_pad_y)
            console_height = 176 if not compact_window else 132 if not tight_window else 96
            if self._layout_state.get("console_height") != console_height:
                self._layout_state["console_height"] = console_height
                self.console.configure(height=console_height)

            summary_columns = 4 if content_width >= 1040 else 2 if content_width >= 590 else 1
            self.layout_summary_cards(summary_columns, compact=compact_window)
            self.layout_toolbar(content_width < 720)
            self.layout_action_buttons(content_width < 860 or height < 700)
            self.layout_tab_bar(tab_stacked, tab_subtitle_wrap)
            self.layout_sidebar_bottom(sidebar_width < 285)

            section_compact = tight_window or content_width < 700
            if self._layout_state.get("section_compact") != section_compact:
                self._layout_state["section_compact"] = section_compact
                for card in self.section_cards:
                    try:
                        card.set_compact(section_compact)
                    except Exception:
                        pass

            if self._layout_state.get("desc_wraplength") != wraplength:
                self._layout_state["desc_wraplength"] = wraplength
                for card in self.section_cards:
                    card.update_layout(wraplength)
            if hasattr(self, "diagnostics_cards"):
                diag_columns = 2 if content_width >= 820 else 1
                if self._layout_state.get("diagnostics_columns") != diag_columns:
                    self._layout_state["diagnostics_columns"] = diag_columns
                    try:
                        self.diagnostics_scroll.grid_columnconfigure(0, weight=1)
                        self.diagnostics_scroll.grid_columnconfigure(1, weight=1 if diag_columns == 2 else 0)
                        cards_order = ["obs", "windows", "disk", "network", "recommendations"]
                        for index, key in enumerate(cards_order):
                            card = self.diagnostics_cards.get(key)
                            if not card:
                                continue
                            card.grid_forget()
                            if diag_columns == 1 or key == "recommendations":
                                row = index + 1 if diag_columns == 1 else 3
                                card.grid(row=row, column=0, columnspan=diag_columns, sticky="nsew", padx=0, pady=(0, 14))
                            else:
                                row = 1 + index // 2
                                col = index % 2
                                card.grid(row=row, column=col, sticky="nsew", padx=(0, 8) if col == 0 else (8, 0), pady=(0, 14))
                    except Exception:
                        pass
                diag_wrap = max(240, (content_width // diag_columns) - 72)
                for card in self.diagnostics_cards.values():
                    try:
                        card.set_compact(section_compact)
                        card.set_wraplength(diag_wrap)
                    except Exception:
                        pass
                try:
                    self.diagnostics_subtitle.configure(wraplength=max(280, content_width - 220))
                except Exception:
                    pass

        except Exception:
            pass

    def detect_system_language(self) -> str:
        if IS_WINDOWS:
            try:
                lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
                primary = lang_id & 0x3FF
                lang_map = {
                    0x22: "uk",
                    0x09: "en",
                }
                code = lang_map.get(primary)
                if code and code in LANG_PACKS:
                    return code
            except Exception:
                pass

        try:
            loc = locale.getdefaultlocale()[0]
            if loc:
                code = loc.split("_")[0].split("-")[0].lower()
                if code in LANG_PACKS:
                    return code
        except Exception:
            pass

        for key in ("LANG", "LC_ALL", "LC_MESSAGES"):
            env_lang = os.environ.get(key, "").lower()
            if not env_lang:
                continue
            code = env_lang.split(".")[0].split("_")[0].split("-")[0]
            if code in LANG_PACKS:
                return code

        return "en" if "en" in LANG_PACKS else next(iter(LANG_PACKS.keys()), "uk")


    def detect_initial_language(self) -> str:
        pref = getattr(self, "lang_preference", "auto")
        if pref != "auto" and pref in LANG_PACKS:
            return pref
        return self.detect_system_language()


    def tr(self, key: str) -> str:
        pack = LANG_PACKS.get(self.lang, {})
        if key in pack:
            return self._normalize_ui_text(pack[key])
        fallback = LANG_PACKS.get("uk", {})
        return self._normalize_ui_text(fallback.get(key, key))

    def trf(self, key: str, **kwargs) -> str:
        text = self.tr(key)
        try:
            return text.format(**kwargs)
        except Exception:
            return text


    def app_title(self) -> str:
        # Title always uses version from version_info (or embedded exe resource built from it)
        return self.trf("app_title", brand=self.tr("app_brand"), version=APP_VERSION)


    def task_title(self, task: CleanerTask) -> str:
        return self.trf(task.title_key, **(task.fmt or {}))

    def task_desc(self, task: CleanerTask) -> str:
        desc = self.trf(task.desc_key, **(task.fmt or {}))
        status = self.registry_status_block(task)
        return f"{desc}\n\n{status}" if status else desc

    def registry_status_block(self, task: CleanerTask) -> str:
        specs = task.registry_values or []
        if not specs:
            return ""
        lines = [self.tr("registry_status_header")]
        statuses = WindowsOps.registry_statuses(specs)
        max_rows = 5
        for item in statuses[:max_rows]:
            status = str(item.get("status") or "error")
            matches = bool(item.get("matches"))
            requires_admin = bool(item.get("requires_admin"))
            if matches:
                marker = "✓"
                label_key = "registry_status_done"
            elif requires_admin and not self.is_admin:
                marker = "⚠"
                label_key = "registry_status_admin_only"
            elif status == "missing":
                marker = "•"
                label_key = "registry_status_missing"
            elif status == "different":
                marker = "•"
                label_key = "registry_status_change_needed"
            elif status == "access_denied":
                marker = "⚠"
                label_key = "registry_status_access_denied"
            elif status == "unavailable":
                marker = "⚠"
                label_key = "registry_status_unavailable"
            else:
                marker = "⚠"
                label_key = "registry_status_error"
            lines.append(self.trf(
                "registry_status_line_fmt",
                marker=marker,
                label=str(item.get("label") or item.get("name") or "registry"),
                current=str(item.get("current_display") or "missing"),
                desired=str(item.get("desired_display") or ""),
                status=self.tr(label_key),
            ))
        if len(statuses) > max_rows:
            lines.append(self.trf("registry_status_more_fmt", count=len(statuses) - max_rows))
        return "\n".join(lines)

    def refresh_registry_status_descriptions(self) -> None:
        for attr in ("card_opt", "card_opt_adv"):
            card = getattr(self, attr, None)
            if card is not None:
                try:
                    card.refresh_rows_language()
                except Exception:
                    pass

    def refresh_registry_statuses(self) -> None:
        self.refresh_registry_status_descriptions()
        self.log(self.tr("registry_status_refresh_ok"))

    @staticmethod
    def registry_keys_for_specs(specs: Sequence[RegistryValueSpec]) -> List[str]:
        keys: List[str] = []
        for spec in specs or []:
            if spec.key_path and spec.key_path not in keys:
                keys.append(spec.key_path)
        return keys

    def category_label(self, key: str) -> str:
        return self.tr(f"category_{key}")


    def auto_language_label(self) -> str:
            detected = self.detect_system_language()
            detected_name = language_display_name(detected)
            return f"auto — {self.tr('lang_auto')} [{detected_name}]"

    def available_language_labels(self) -> List[str]:
            labels = [self.auto_language_label()]
            for code in sorted(LANG_PACKS.keys()):
                labels.append(f"{code} — {language_display_name(code)}")
            return labels

    def current_language_label(self) -> str:
            pref = getattr(self, "lang_preference", "auto")
            if pref == "auto":
                return self.auto_language_label()
            code = pref if pref in LANG_PACKS else self.lang
            return f"{code} — {language_display_name(code)}"

    def on_language_change(self, value: str):
        selected = value.split(" — ", 1)[0].strip().lower()
        new_pref = "auto" if selected == "auto" else selected

        if new_pref != "auto" and new_pref not in LANG_PACKS:
            return

        manual_before = self.current_profile_name in {
            self.tr("profile_manual"),
            LANG_PACKS.get("uk", {}).get("profile_manual", ""),
            LANG_PACKS.get("en", {}).get("profile_manual", ""),
        }

        self.lang_preference = new_pref
        self.lang = self.detect_system_language() if new_pref == "auto" else new_pref
        self.save_config()

        if manual_before:
            self.current_profile_name = self.tr("profile_manual")

        self.apply_language()
        self.refresh_selection_stats()

        if new_pref == "auto":
            self.log(self.trf("language_switched", lang=f"AUTO → {self.lang.upper()}"))
        else:
            self.log(self.trf("language_switched", lang=self.lang.upper()))

    def apply_language(self):
        self.title(self.app_title())
        self.brand_label.configure(text=self.tr("app_brand"))
        self.app_subtitle.configure(text=self.tr("app_subtitle"))
        self.status_badge.configure(text=self.tr("admin_active") if self.is_admin else self.tr("limited_mode"))
        if hasattr(self, "btn_admin"):
            self.btn_admin.configure(text=self.tr("relaunch_admin"))
        self.lbl_language.configure(text=self.tr("language"))
        self.quick_profiles_label.configure(text=self.tr("quick_profiles"))
        self.btn_safe.configure(text=self.tr("safe"))
        self.btn_gaming.configure(text=self.tr("gaming_profile"))
        if hasattr(self, "btn_streamer"):
            self.btn_streamer.configure(text=self.tr("streamer"))
        self.btn_deep_profile.configure(text=self.tr("deep_profile"))
        self.btn_reset_selection.configure(text=self.tr("reset_selection"))
        if hasattr(self, "btn_restore_registry"):
            self.btn_restore_registry.configure(text=self.tr("restore_registry_backup"))
        if hasattr(self, "btn_about"):
            self.btn_about.configure(text=self.tr("about"))
        if hasattr(self, "btn_check_updates"):
            self.btn_check_updates.configure(text=self.tr("check_updates"))
        self.event_log_label.configure(text=self.tr("event_log"))
        self.btn_copy_log.configure(text=self.tr("copy_log"))
        self.btn_clear_log.configure(text=self.tr("clear_log"))
        self.btn_cancel.configure(text=self.tr("stop"))
        self.card_selected.set_title(self.tr("selected_modules"))
        self.card_profile.set_title(self.tr("active_profile"))
        self.card_estimate.set_title(self.tr("junk_found"))
        self.card_admin.set_title(self.tr("admin_access"))
        self.search_label.configure(text=self.tr("search_modules"))
        self.search_entry.configure(placeholder_text=self.tr("search_placeholder"))
        self.btn_clear_search.configure(text=self.tr("clear_search"))
        self.cleaner_scroll.configure(label_text=self.tr("cleaner_modules"))
        self.optimizer_scroll.configure(label_text=self.tr("optimizer_modules"))
        if hasattr(self, "tab_cleaner_button"):
            self.tab_cleaner_button.set_text(self.module_tab_title("cleaner"), self.module_tab_subtitle("cleaner"))
        if hasattr(self, "tab_optimizer_button"):
            self.tab_optimizer_button.set_text(self.module_tab_title("optimizer"), self.module_tab_subtitle("optimizer"))
        if hasattr(self, "tab_diagnostics_button"):
            self.tab_diagnostics_button.set_text(self.module_tab_title("diagnostics"), self.module_tab_subtitle("diagnostics"))
        if hasattr(self, "diagnostics_scroll"):
            self.diagnostics_scroll.configure(label_text=self.tr("diagnostics_modules"))
        if hasattr(self, "diagnostics_title"):
            self.refresh_diagnostics_language()
        self.show_module_tab(self.active_module_tab)
        self.card_sys.set_header(self.tr("sec_system_title"), self.tr("sec_system_sub"))
        self.card_net.set_header(self.tr("sec_net_title"), self.tr("sec_net_sub"))
        self.card_deep.set_header(self.tr("sec_deep_title"), self.tr("sec_deep_sub"))
        self.card_gamer.set_header(self.tr("sec_gamer_title"), self.tr("sec_gamer_sub"))
        self.card_opt.set_header(self.tr("sec_optimizer_title"), self.tr("sec_optimizer_sub"))
        self.card_opt_adv.set_header(self.tr("sec_optimizer_registry_title"), self.tr("sec_optimizer_registry_sub"))
        self.card_opt_tools.set_header(self.tr("sec_optimizer_tools_title"), self.tr("sec_optimizer_tools_sub"))
        self.card_ult.set_header(self.tr("sec_ult_title"), self.tr("sec_ult_sub"))
        for card in self.section_cards:
            card.refresh_rows_language()
        self.apply_search_filter(force=True)
        if self.cleaned_bytes == 0:
            self.lbl_stats.configure(text=self.tr("freed_zero"))
        else:
            self.lbl_stats.configure(text=self.trf("freed_fmt", mb=self.cleaned_bytes / (1024 ** 2)))
        if self.analysis_total_bytes == 0:
            self.lbl_analysis.configure(text=self.tr("analysis_idle"))
        self.btn_start.configure(text=self.tr("running") if self.is_running else self.tr("analyze_clean"))
        self.btn_analyze.configure(text=self.tr("analyze_only"))
        self.btn_reset_all.configure(text=self.tr("reset_all"))
        if self.current_profile_name in {LANG_PACKS.get("uk", {}).get("profile_manual", ""), LANG_PACKS.get("en", {}).get("profile_manual", "")}:
            self.set_profile_name(self.tr("profile_manual"), COLORS["gamer"])
        self.language_menu.configure(values=self.available_language_labels())
        self.language_menu.set(self.current_language_label())
        admin_text = self.tr("yes") if self.is_admin else self.tr("no")
        self.card_admin.set(admin_text, COLORS["success"] if self.is_admin else COLORS["ultimate"])
        self.schedule_responsive_layout()

    def build_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=390, corner_radius=0, fg_color=COLORS["bg_panel"])
        self.sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.sidebar.grid_propagate(False)

        head = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        head.pack(fill="x", padx=20, pady=(24, 12))
        self.brand_label = ctk.CTkLabel(head, text=self.tr("app_brand"), font=("Segoe UI Black", 30), text_color=COLORS["white"])
        self.brand_label.pack(anchor="w")
        self.app_subtitle = ctk.CTkLabel(head, text=self.tr("app_subtitle"), font=("Segoe UI", 12), text_color=COLORS["text_gray"])
        self.app_subtitle.pack(anchor="w", pady=(2, 0))

        status_color = COLORS["success"] if self.is_admin else COLORS["ultimate"]
        self.status_badge = ctk.CTkButton(
            self.sidebar,
            text=self.tr("admin_active") if self.is_admin else self.tr("limited_mode"),
            fg_color="transparent",
            text_color=status_color,
            font=("Segoe UI", 12, "bold"),
            border_width=1,
            border_color=status_color,
            hover=False,
            height=34,
        )
        self.status_badge.pack(fill="x", padx=20, pady=(0, 10))

        if not self.is_admin:
            self.btn_admin = AnimatedButton(
                self.sidebar,
                text=self.tr("relaunch_admin"),
                fg_color=COLORS["ultimate"],
                hover_color="#DC2626",
                font=("Segoe UI", 12, "bold"),
                command=self.run_as_admin,
                height=38,
            )
            self.btn_admin.pack(fill="x", padx=20, pady=(0, 14))

        lang_box = ctk.CTkFrame(self.sidebar, fg_color=COLORS["bg_card"], corner_radius=14, border_width=1, border_color=COLORS["border"])
        lang_box.pack(fill="x", padx=20, pady=(0, 14))
        self.lbl_language = ctk.CTkLabel(lang_box, text=self.tr("language"), font=("Segoe UI", 13, "bold"), text_color=COLORS["white"])
        self.lbl_language.pack(anchor="w", padx=14, pady=(12, 6))
        self.language_menu = ctk.CTkOptionMenu(lang_box, values=self.available_language_labels(), command=self.on_language_change)
        self.language_menu.pack(fill="x", padx=14, pady=(0, 14))
        self.language_menu.set(self.current_language_label())

        quick = ctk.CTkFrame(self.sidebar, fg_color=COLORS["bg_card"], corner_radius=14, border_width=1, border_color=COLORS["border"])
        quick.pack(fill="x", padx=20, pady=(0, 14))
        self.quick_profiles_label = ctk.CTkLabel(quick, text=self.tr("quick_profiles"), font=("Segoe UI", 13, "bold"), text_color=COLORS["white"])
        self.quick_profiles_label.pack(anchor="w", padx=14, pady=(12, 8))
        self.btn_safe = AnimatedButton(quick, text=self.tr("safe"), height=34, command=self.apply_safe_preset, fg_color="#1E293B", hover_color="#334155")
        self.btn_safe.pack(fill="x", padx=14, pady=(0, 8))
        self.btn_gaming = AnimatedButton(quick, text=self.tr("gaming_profile"), height=34, command=self.apply_gaming_mode, fg_color="#0F766E", hover_color="#115E59")
        self.btn_gaming.pack(fill="x", padx=14, pady=(0, 8))
        self.btn_streamer = AnimatedButton(quick, text=self.tr("streamer"), height=34, command=self.apply_streaming_mode, fg_color="#164E63", hover_color="#155E75")
        self.btn_streamer.pack(fill="x", padx=14, pady=(0, 8))
        self.btn_deep_profile = AnimatedButton(quick, text=self.tr("deep_profile"), height=34, command=self.apply_deep_clean_mode, fg_color="#166534", hover_color="#14532D")
        self.btn_deep_profile.pack(fill="x", padx=14, pady=(0, 8))
        self.btn_reset_selection = AnimatedButton(quick, text=self.tr("reset_selection"), height=34, command=self.clear_selection, fg_color="#374151", hover_color="#4B5563")
        self.btn_reset_selection.pack(fill="x", padx=14, pady=(0, 8))
        self.btn_restore_registry = AnimatedButton(
            quick,
            text=self.tr("restore_registry_backup"),
            height=34,
            command=self.open_restore_registry_dialog,
            fg_color="#4C1D95",
            hover_color="#5B21B6",
        )
        self.btn_restore_registry.pack(fill="x", padx=14, pady=(0, 8))
        self.refresh_restore_backup_button()
        # About
        self.btn_about = AnimatedButton(
            quick,
            text=self.tr("about"),
            height=34,
            command=self.open_about_dialog,
            fg_color="#1E293B",
            hover_color="#334155",
        )
        self.btn_about.pack(fill="x", padx=14, pady=(0, 14))

        self.event_log_label = ctk.CTkLabel(self.sidebar, text=self.tr("event_log"), font=("Segoe UI", 12, "bold"), text_color=COLORS["text_gray"], anchor="w")
        self.event_log_label.pack(fill="x", padx=20, pady=(0, 6))
        self.console = ctk.CTkTextbox(self.sidebar, font=("Consolas", 11), fg_color="#05070A", text_color="#34D399", border_width=1, border_color=COLORS["border"])
        self.console.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        self.console.configure(state="disabled")

        btn_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=(0, 14))
        self.btn_copy_log = AnimatedButton(btn_frame, text=self.tr("copy_log"), fg_color="#334155", hover_color="#475569", width=118, command=self.copy_log_to_clipboard)
        self.btn_copy_log.pack(side="left")
        self.btn_clear_log = AnimatedButton(btn_frame, text=self.tr("clear_log"), fg_color="#334155", hover_color="#475569", width=110, command=self.clear_log)
        self.btn_clear_log.pack(side="left", padx=8)
        self.btn_cancel = AnimatedButton(btn_frame, text=self.tr("stop"), fg_color="#4B5563", hover_color="#6B7280", width=110, state="disabled", command=self.cancel_current_run)
        self.btn_cancel.pack(side="right")

    def refresh_restore_backup_button(self):
        if not hasattr(self, "btn_restore_registry"):
            return
        has_backup = WindowsOps.has_registry_backup()
        self.btn_restore_registry.configure(
            state="normal" if has_backup else "disabled",
            fg_color="#4C1D95" if has_backup else "#3F3F46",
            hover_color="#5B21B6" if has_backup else "#3F3F46",
        )

    def backup_registry_for_tasks(self, tasks: List[CleanerTask]) -> bool:
        registry_keys: List[str] = []
        for task in tasks:
            specs = list(task.registry_values or [])
            if specs:
                keys = self.registry_keys_for_specs([spec for spec in specs if not spec.requires_admin or self.is_admin])
            else:
                keys = list(task.registry_keys or [])
            for key in keys:
                if key not in registry_keys:
                    registry_keys.append(key)
        if not registry_keys:
            return True
        folder = WindowsOps.backup_registry_keys(registry_keys)
        if folder:
            self.log(self.trf("registry_backup_created", path=folder))
            self.after(0, self.refresh_restore_backup_button)
            return True
        self.log(self.tr("registry_backup_failed"))
        return False

    def restore_registry_backup(self, backup_dir: Optional[str] = None):
        if not self.is_admin:
            self.log(self.tr("restore_registry_admin_required"))
            return False
        target = backup_dir or WindowsOps.latest_registry_backup_dir()
        if not target:
            self.log(self.tr("registry_restore_missing"))
            return False
        ok = WindowsOps.restore_registry_backup_dir(target)
        self.log(self.trf("registry_restore_ok", name=os.path.basename(target)) if ok else self.trf("registry_restore_fail", name=os.path.basename(target)))
        self.after(0, self.refresh_restore_backup_button)
        self.after(0, self.refresh_registry_status_descriptions)
        return ok

    def _format_backup_time(self, path: str) -> str:
        try:
            stamp = datetime.fromtimestamp(os.path.getmtime(path))
            return stamp.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return self.tr("unknown")

    def open_restore_registry_dialog(self):
        backups = WindowsOps.list_registry_backups()
        if not backups:
            self.log(self.tr("registry_restore_missing"))
            return

        try:
            if getattr(self, "_restore_win", None) and self._restore_win.winfo_exists():  # type: ignore[attr-defined]
                self._restore_win.focus()  # type: ignore[attr-defined]
                return
        except Exception:
            pass

        win = ctk.CTkToplevel(self)
        self._restore_win = win  # type: ignore[attr-defined]
        win.title(self.tr("restore_registry_backup"))
        self.configure_toplevel_geometry(win, preferred=(900, 660), minimum=(700, 520))
        win.configure(fg_color=COLORS["bg_main"])
        try:
            win.transient(self)
            win.grab_set()
        except Exception:
            pass
        self._apply_icon_to_toplevel(win)

        selected = ctk.StringVar(value=backups[0]["path"])

        wrap = ctk.CTkFrame(win, fg_color=COLORS["bg_card"], corner_radius=18, border_width=1, border_color=COLORS["border"])
        wrap.pack(fill="both", expand=True, padx=18, pady=18)
        wrap.grid_columnconfigure(0, weight=0)
        wrap.grid_columnconfigure(1, weight=1)
        wrap.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(wrap, fg_color="transparent")
        head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=18, pady=(18, 10))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(head, text=self.tr("restore_dialog_title"), font=("Segoe UI Black", 20), text_color=COLORS["white"]).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(head, text=self.tr("restore_dialog_sub"), font=("Segoe UI", 12), text_color=COLORS["text_gray"], justify="left").grid(row=1, column=0, sticky="w", pady=(4, 0))

        list_card = ctk.CTkFrame(wrap, fg_color=COLORS["bg_soft"], corner_radius=16, border_width=1, border_color=COLORS["border"])
        list_card.grid(row=1, column=0, sticky="ns", padx=(18, 12), pady=(0, 18))
        list_card.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(list_card, text=self.tr("restore_dialog_backups"), font=("Segoe UI", 13, "bold"), text_color=COLORS["white"]).grid(row=0, column=0, sticky="w", padx=14, pady=(14, 10))
        backup_list = ctk.CTkScrollableFrame(list_card, width=255, fg_color="transparent", label_text="")
        backup_list.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        details = ctk.CTkFrame(wrap, fg_color=COLORS["bg_soft"], corner_radius=16, border_width=1, border_color=COLORS["border"])
        details.grid(row=1, column=1, sticky="nsew", padx=(0, 18), pady=(0, 18))
        details.grid_columnconfigure(0, weight=1)
        details.grid_rowconfigure(3, weight=1)

        title_lbl = ctk.CTkLabel(details, text="", font=("Segoe UI", 15, "bold"), text_color=COLORS["white"], anchor="w")
        title_lbl.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 6))
        meta_lbl = ctk.CTkLabel(details, text="", font=("Segoe UI", 11), text_color=COLORS["text_gray"], justify="left", anchor="w")
        meta_lbl.grid(row=1, column=0, sticky="ew", padx=16)
        note_lbl = ctk.CTkLabel(details, text=self.tr("restore_dialog_note"), font=("Segoe UI", 11), text_color=COLORS["muted"], justify="left", wraplength=480)
        note_lbl.grid(row=2, column=0, sticky="ew", padx=16, pady=(10, 10))
        manifest_box = ctk.CTkTextbox(details, font=("Consolas", 11), fg_color=COLORS["bg_panel"], text_color=COLORS["white"], border_width=1, border_color=COLORS["border"])
        manifest_box.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 12))
        manifest_box.configure(state="disabled")

        action_bar = ctk.CTkFrame(details, fg_color="transparent")
        action_bar.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 16))

        btn_open_folder = AnimatedButton(action_bar, text=self.tr("open_backup_folder"), height=40, fg_color=COLORS["bg_card"], hover_color="#1F2937")
        btn_open_folder.pack(side="left")
        btn_restore = AnimatedButton(action_bar, text=self.tr("restore_selected_backup"), height=40, fg_color="#4C1D95", hover_color="#5B21B6")
        btn_restore.pack(side="right")

        buttons = {}

        def render_selected(path: str):
            data = WindowsOps.describe_registry_backup(path)
            title_lbl.configure(text=data.get("name") or os.path.basename(path))
            kind = data.get("kind")
            kind_label = self.tr("backup_kind_pre_restore") if kind == "pre_restore" else self.tr("backup_kind_backup")
            meta_lbl.configure(text=self.trf(
                "restore_dialog_meta",
                created=data.get("created", self._format_backup_time(path)),
                count=data.get("count", 0),
                kind=kind_label,
            ))
            manifest_text = data.get("manifest_text") or self.tr("restore_dialog_manifest_empty")
            manifest_box.configure(state="normal")
            manifest_box.delete("1.0", "end")
            manifest_box.insert("1.0", manifest_text)
            manifest_box.configure(state="disabled")
            for backup_path, button in buttons.items():
                is_active = backup_path == path
                button.configure(
                    fg_color=mix_colors("#4C1D95", COLORS["bg_soft"], 0.18) if is_active else COLORS["bg_card"],
                    border_color="#6D28D9" if is_active else COLORS["border"],
                    text_color=COLORS["white"] if is_active else COLORS["text_gray"],
                )
            selected.set(path)
            btn_open_folder.configure(command=lambda current=path: WindowsOps.open_in_file_manager(current))
            btn_restore.configure(command=lambda current=path: do_restore(current))

        def do_restore(path: str):
            ok = self.restore_registry_backup(path)
            if ok:
                try:
                    win.destroy()
                except Exception:
                    pass

        for item in backups:
            path = item["path"]
            label = f"{item['name']}\n{item['created']}"
            button = AnimatedButton(
                backup_list,
                text=label,
                anchor="w",
                height=56,
                corner_radius=12,
                fg_color=COLORS["bg_card"],
                hover_color="#1F2937",
                border_width=1,
                border_color=COLORS["border"],
                text_color=COLORS["text_gray"],
                command=lambda current=path: render_selected(current),
            )
            button.pack(fill="x", padx=4, pady=(0, 8))
            buttons[path] = button

        render_selected(selected.get())

        foot = ctk.CTkFrame(wrap, fg_color="transparent")
        foot.grid(row=2, column=0, columnspan=2, sticky="ew", padx=18, pady=(0, 18))
        AnimatedButton(foot, text=self.tr("about_close"), height=40, fg_color=COLORS["bg_panel"], hover_color="#1F2937", command=win.destroy).pack(side="right")

    def build_main_area(self):
        self.main_wrap = ctk.CTkFrame(self, fg_color="transparent")
        self.main_wrap.grid(row=0, column=1, sticky="nsew", padx=18, pady=18)
        self.main_wrap.grid_columnconfigure(0, weight=1)
        self.main_wrap.grid_rowconfigure(3, weight=1)

        self.summary_top = ctk.CTkFrame(self.main_wrap, fg_color="transparent")
        self.summary_top.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self.summary_top.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.card_selected = SummaryCard(self.summary_top, self.tr("selected_modules"), "0", COLORS["white"])
        self.card_selected.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.card_profile = SummaryCard(self.summary_top, self.tr("active_profile"), self.current_profile_name, COLORS["gamer"])
        self.card_profile.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        self.card_estimate = SummaryCard(self.summary_top, self.tr("junk_found"), "—", COLORS["system"])
        self.card_estimate.grid(row=0, column=2, sticky="ew", padx=(0, 10))
        admin_text = self.tr("yes") if self.is_admin else self.tr("no")
        self.card_admin = SummaryCard(self.summary_top, self.tr("admin_access"), admin_text, COLORS["success"] if self.is_admin else COLORS["ultimate"])
        self.card_admin.grid(row=0, column=3, sticky="ew")

        self.toolbar = ctk.CTkFrame(self.main_wrap, fg_color=COLORS["bg_card"], corner_radius=14, border_width=1, border_color=COLORS["border"])
        self.toolbar.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self.toolbar.grid_columnconfigure(1, weight=1)

        self.search_label = ctk.CTkLabel(self.toolbar, text=self.tr("search_modules"), font=("Segoe UI", 12, "bold"), text_color=COLORS["white"])
        self.search_label.grid(row=0, column=0, padx=14, pady=12)
        self.search_var = ctk.StringVar(value="")
        self.search_var.trace_add("write", lambda *_: self.schedule_search_filter())
        self.search_entry = ctk.CTkEntry(self.toolbar, textvariable=self.search_var, placeholder_text=self.tr("search_placeholder"), height=38, border_color=COLORS["border"], fg_color=COLORS["bg_soft"])
        self.search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=10)
        self.btn_clear_search = AnimatedButton(self.toolbar, text=self.tr("clear_search"), width=130, command=lambda: self.search_var.set(""), fg_color="#334155", hover_color="#475569")
        self.btn_clear_search.grid(row=0, column=2, padx=(0, 12))

        self.tab_bar = ctk.CTkFrame(
            self.main_wrap,
            fg_color=COLORS["bg_panel"],
            corner_radius=18,
            border_width=1,
            border_color=COLORS["border"],
        )
        self.tab_bar.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        self.tab_bar.grid_columnconfigure((0, 1, 2), weight=1)

        self.tab_cleaner_button = ModernTabButton(
            self.tab_bar,
            title=self.module_tab_title("cleaner"),
            subtitle=self.module_tab_subtitle("cleaner"),
            accent=COLORS["system"],
            command=lambda: self.on_module_tab_changed("cleaner"),
        )
        self.tab_cleaner_button.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=12)

        self.tab_optimizer_button = ModernTabButton(
            self.tab_bar,
            title=self.module_tab_title("optimizer"),
            subtitle=self.module_tab_subtitle("optimizer"),
            accent=COLORS["gamer"],
            command=lambda: self.on_module_tab_changed("optimizer"),
        )
        self.tab_optimizer_button.grid(row=0, column=1, sticky="ew", padx=(8, 8), pady=12)

        self.tab_diagnostics_button = ModernTabButton(
            self.tab_bar,
            title=self.module_tab_title("diagnostics"),
            subtitle=self.module_tab_subtitle("diagnostics"),
            accent=COLORS["system"],
            command=lambda: self.on_module_tab_changed("diagnostics"),
        )
        self.tab_diagnostics_button.grid(row=0, column=2, sticky="ew", padx=(8, 12), pady=12)

        self.cleaner_scroll = ctk.CTkScrollableFrame(self.main_wrap, fg_color="transparent", label_text=self.tr("cleaner_modules"))
        self.cleaner_scroll.grid(row=3, column=0, sticky="nsew")
        self.cleaner_scroll.grid_columnconfigure(0, weight=1)

        self.optimizer_scroll = ctk.CTkScrollableFrame(self.main_wrap, fg_color="transparent", label_text=self.tr("optimizer_modules"))
        self.optimizer_scroll.grid(row=3, column=0, sticky="nsew")
        self.optimizer_scroll.grid_columnconfigure(0, weight=1)

        self.diagnostics_scroll = ctk.CTkScrollableFrame(self.main_wrap, fg_color="transparent", label_text=self.tr("diagnostics_modules"))
        self.diagnostics_scroll.grid(row=3, column=0, sticky="nsew")
        self.diagnostics_scroll.grid_columnconfigure((0, 1), weight=1)

        self.card_sys = SectionCard(self, self.cleaner_scroll, self.tr("sec_system_title"), self.tr("sec_system_sub"), COLORS["system"])
        self.card_sys.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        self.section_cards.append(self.card_sys)
        self.register_system_tasks()

        self.card_net = SectionCard(self, self.cleaner_scroll, self.tr("sec_net_title"), self.tr("sec_net_sub"), COLORS["browsers"])
        self.card_net.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        self.section_cards.append(self.card_net)
        self.register_browser_tasks()

        self.card_deep = SectionCard(self, self.cleaner_scroll, self.tr("sec_deep_title"), self.tr("sec_deep_sub"), COLORS["deep"])
        self.card_deep.grid(row=2, column=0, sticky="ew", pady=(0, 16))
        self.section_cards.append(self.card_deep)
        self.register_deep_tasks()

        self.card_gamer = SectionCard(self, self.cleaner_scroll, self.tr("sec_gamer_title"), self.tr("sec_gamer_sub"), COLORS["gamer"])
        self.card_gamer.grid(row=3, column=0, sticky="ew", pady=(0, 16))
        self.section_cards.append(self.card_gamer)
        self.register_gaming_cleanup_tasks()

        self.card_ult = SectionCard(self, self.cleaner_scroll, self.tr("sec_ult_title"), self.tr("sec_ult_sub"), COLORS["ultimate"])
        self.card_ult.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        self.section_cards.append(self.card_ult)
        self.register_ultimate_tasks()

        self.card_opt = SectionCard(self, self.optimizer_scroll, self.tr("sec_optimizer_title"), self.tr("sec_optimizer_sub"), COLORS["gamer"])
        self.card_opt.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        self.section_cards.append(self.card_opt)
        self.register_optimizer_tasks()

        self.card_opt_adv = SectionCard(self, self.optimizer_scroll, self.tr("sec_optimizer_registry_title"), self.tr("sec_optimizer_registry_sub"), COLORS["ultimate"])
        self.card_opt_adv.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        self.section_cards.append(self.card_opt_adv)
        self.register_optimizer_registry_tasks()

        self.card_opt_tools = SectionCard(self, self.optimizer_scroll, self.tr("sec_optimizer_tools_title"), self.tr("sec_optimizer_tools_sub"), COLORS["system"])
        self.card_opt_tools.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.section_cards.append(self.card_opt_tools)
        self.register_optimizer_helper_tasks()

        self.build_diagnostics_tab()

        self.show_module_tab(self.active_module_tab)


    def _diagnostic_status_text(self, severity: str) -> str:
        return self.tr({
            "ok": "diag_status_ok",
            "warn": "diag_status_warn",
            "error": "diag_status_error",
            "info": "diag_status_info",
            "loading": "diag_status_loading",
        }.get(severity, "diag_status_unknown"))

    def build_diagnostics_tab(self):
        self.diagnostics_cards: Dict[str, DiagnosticStatusCard] = {}
        self.diagnostics_header = ctk.CTkFrame(self.diagnostics_scroll, fg_color=COLORS["bg_card"], corner_radius=18, border_width=1, border_color=COLORS["border"])
        self.diagnostics_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        self.diagnostics_header.grid_columnconfigure(0, weight=1)
        self.diagnostics_title = ctk.CTkLabel(self.diagnostics_header, text=self.tr("diagnostics_title"), font=("Segoe UI Semibold", 18, "bold"), text_color=COLORS["white"], anchor="w")
        self.diagnostics_title.grid(row=0, column=0, sticky="w", padx=16, pady=(14, 2))
        self.diagnostics_subtitle = ctk.CTkLabel(self.diagnostics_header, text=self.tr("diagnostics_subtitle"), font=("Segoe UI", 11), text_color=COLORS["text_gray"], anchor="w", justify="left", wraplength=860)
        self.diagnostics_subtitle.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 14))
        self.btn_refresh_diagnostics = AnimatedButton(
            self.diagnostics_header,
            text=self.tr("diagnostics_refresh"),
            height=38,
            width=170,
            fg_color=mix_colors(COLORS["system"], COLORS["bg_soft"], 0.22),
            hover_color=mix_colors(COLORS["system"], COLORS["bg_soft"], 0.38),
            accent=COLORS["system"],
            command=self.refresh_diagnostics_dashboard,
        )
        self.btn_refresh_diagnostics.grid(row=0, column=1, rowspan=2, sticky="e", padx=16, pady=14)

        definitions = [
            ("obs", "diag_card_obs_title", "diag_card_obs_sub", COLORS["browsers"]),
            ("windows", "diag_card_windows_title", "diag_card_windows_sub", COLORS["gamer"]),
            ("disk", "diag_card_disk_title", "diag_card_disk_sub", COLORS["deep"]),
            ("network", "diag_card_network_title", "diag_card_network_sub", COLORS["system"]),
            ("recommendations", "diag_card_recommendations_title", "diag_card_recommendations_sub", COLORS["success"]),
        ]
        for index, (key, title_key, sub_key, accent) in enumerate(definitions, start=1):
            card = DiagnosticStatusCard(self.diagnostics_scroll, self.tr(title_key), self.tr(sub_key), accent=accent)
            row = 1 + (index - 1) // 2
            col = (index - 1) % 2
            colspan = 2 if key == "recommendations" else 1
            card.grid(row=row, column=col, columnspan=colspan, sticky="nsew", padx=(0, 8) if col == 0 and colspan == 1 else (8, 0) if col == 1 else 0, pady=(0, 14))
            self.diagnostics_cards[key] = card
        self._set_diagnostics_placeholder()

    def refresh_diagnostics_language(self):
        self.diagnostics_title.configure(text=self.tr("diagnostics_title"))
        self.diagnostics_subtitle.configure(text=self.tr("diagnostics_subtitle"))
        self.btn_refresh_diagnostics.configure(text=self.tr("diagnostics_refresh"))
        mapping = {
            "obs": ("diag_card_obs_title", "diag_card_obs_sub"),
            "windows": ("diag_card_windows_title", "diag_card_windows_sub"),
            "disk": ("diag_card_disk_title", "diag_card_disk_sub"),
            "network": ("diag_card_network_title", "diag_card_network_sub"),
            "recommendations": ("diag_card_recommendations_title", "diag_card_recommendations_sub"),
        }
        for key, card in getattr(self, "diagnostics_cards", {}).items():
            title_key, sub_key = mapping.get(key, ("diagnostics_title", "diagnostics_subtitle"))
            card.set_text(self.tr(title_key), self.tr(sub_key))
        if not self._last_diagnostics_report:
            self._set_diagnostics_placeholder()
        else:
            self.render_diagnostics_dashboard(self._last_diagnostics_report)

    def _set_diagnostics_placeholder(self):
        for card in getattr(self, "diagnostics_cards", {}).values():
            card.set_status(self._diagnostic_status_text("info"), self.tr("diagnostics_not_run"), "info")

    def refresh_diagnostics_dashboard(self):
        if self._diagnostics_in_progress:
            return
        self._diagnostics_in_progress = True
        self.btn_refresh_diagnostics.configure(state="disabled", text=self.tr("diagnostics_running"))
        for card in self.diagnostics_cards.values():
            card.set_status(self._diagnostic_status_text("loading"), self.tr("diagnostics_collecting"), "loading")
        self.log(self.tr("diagnostics_dashboard_started"))

        def worker():
            try:
                return {
                    "streaming": WindowsOps.collect_streaming_diagnostics(),
                    "gaming": WindowsOps.collect_gaming_compat_report(),
                    "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            except Exception as exc:
                return {"error": str(exc), "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

        def done(report: Dict[str, Any]):
            self._diagnostics_in_progress = False
            self._last_diagnostics_report = report
            self.btn_refresh_diagnostics.configure(state="normal", text=self.tr("diagnostics_refresh"))
            self.render_diagnostics_dashboard(report)
            self.log(self.tr("diagnostics_dashboard_done"))

        threading.Thread(target=lambda: (lambda report: self.after(0, lambda: done(report)))(worker()), daemon=True).start()

    def _format_state(self, value: Any) -> str:
        key = f"state_{str(value or 'unknown').strip().lower()}"
        translated = self.tr(key)
        return translated if translated != key else str(value or self.tr("unknown"))

    def _format_gpu_preference_line(self, item: Dict[str, Any]) -> str:
        name = str(item.get("name") or item.get("path") or "app")
        return self.trf("diag_gpu_pref_line", app=name, pref=self._format_state(item.get("preference")))

    def _build_diagnostic_recommendations(self, streaming: Dict[str, Any], gaming: Dict[str, Any]) -> List[str]:
        recommendations: List[str] = []
        profiles = list(streaming.get("obs_profiles") or [])
        issues = list(streaming.get("obs_log_issues") or [])
        for profile in profiles:
            stream_kind = self._diagnostic_encoder_kind(str(profile.get("stream_encoder") or ""))
            record_kind = self._diagnostic_encoder_kind(str(profile.get("record_encoder") or ""))
            if stream_kind == "cpu" or record_kind == "cpu":
                recommendations.append(self.tr("diag_rec_hardware_encoder"))
                break
        for profile in profiles:
            record_format = str(profile.get("record_format") or "").lower()
            if record_format and record_format not in {"mkv", "hybrid_mp4", "unknown"}:
                recommendations.append(self.tr("diag_rec_mkv"))
                break
        if any(str(issue.get("kind")) == "dropped_frames" for issue in issues):
            recommendations.append(self.tr("diag_rec_network_bitrate"))
        if any(str(issue.get("kind")) == "rendering_lag" for issue in issues):
            recommendations.append(self.tr("diag_rec_reduce_gpu_load"))
        if str(gaming.get("game_dvr")) == "enabled":
            recommendations.append(self.tr("diag_rec_disable_captures"))
        summary = dict(gaming.get("gpu_preference_summary") or {})
        if int(summary.get("power_saving") or 0) > 0 or int(summary.get("total_relevant") or 0) == 0:
            recommendations.append(self.tr("diag_rec_gpu_high_performance"))
        disk = dict(streaming.get("disk_write") or {})
        if disk.get("ok") and float(disk.get("mbps") or 0.0) < 80.0:
            recommendations.append(self.tr("diag_rec_recording_disk"))
        if not recommendations:
            recommendations.append(self.tr("diag_rec_all_good"))
        # keep order, remove duplicates
        unique: List[str] = []
        for item in recommendations:
            if item not in unique:
                unique.append(item)
        return unique[:7]

    def render_diagnostics_dashboard(self, report: Dict[str, Any]):
        if report.get("error"):
            details = self.trf("diagnostics_error_fmt", error=str(report.get("error")))
            for card in self.diagnostics_cards.values():
                card.set_status(self._diagnostic_status_text("error"), details, "error")
            return

        streaming = dict(report.get("streaming") or {})
        gaming = dict(report.get("gaming") or {})
        issues = list(streaming.get("obs_log_issues") or [])
        profiles = list(streaming.get("obs_profiles") or [])

        # OBS card
        obs_lines: List[str] = []
        obs_severity = "ok"
        if not profiles:
            obs_severity = "warn"
            obs_lines.append(self.tr("diag_obs_no_profiles"))
        for profile in profiles[:4]:
            name = str(profile.get("name") or "OBS")
            stream_encoder = str(profile.get("stream_encoder") or "unknown")
            record_encoder = str(profile.get("record_encoder") or "unknown")
            record_format = str(profile.get("record_format") or "unknown")
            replay = self.tr("yes") if profile.get("replay_buffer") else self.tr("no")
            stream_kind = self._diagnostic_encoder_kind(stream_encoder)
            record_kind = self._diagnostic_encoder_kind(record_encoder)
            if stream_kind == "cpu" or record_kind == "cpu":
                obs_severity = "warn"
            if record_format not in {"mkv", "hybrid_mp4", "unknown"}:
                obs_severity = "warn"
            obs_lines.append(self.trf("diag_obs_profile_line", profile=name, stream=stream_encoder, record=record_encoder, format=record_format, replay=replay))
        if issues:
            bad = ", ".join(sorted({self.tr(f"obs_log_issue_{str(item.get('kind') or 'unknown')}") for item in issues})[:4])
            obs_lines.append(self.trf("diag_obs_issues_line", issues=bad))
            obs_severity = "warn"
        else:
            obs_lines.append(self.tr("diag_obs_logs_clean"))
        self.diagnostics_cards["obs"].set_status(self._diagnostic_status_text(obs_severity), "\n".join(obs_lines), obs_severity)

        # Windows card
        win_lines = [
            self.trf("diag_windows_state_line", label=self.tr("diag_label_game_mode"), value=self._format_state(gaming.get("game_mode"))),
            self.trf("diag_windows_state_line", label=self.tr("diag_label_captures"), value=self._format_state(gaming.get("game_dvr"))),
            self.trf("diag_windows_state_line", label=self.tr("diag_label_hags"), value=self._format_state(gaming.get("hags"))),
            self.trf("diag_windows_state_line", label=self.tr("diag_label_power_plan"), value=str(gaming.get("active_power_scheme") or "unknown")),
        ]
        summary = dict(gaming.get("gpu_preference_summary") or {})
        relevant = list(summary.get("relevant") or [])
        if relevant:
            win_lines.append(self.tr("diag_gpu_pref_header"))
            for item in relevant[:4]:
                win_lines.append(self._format_gpu_preference_line(item))
            if int(summary.get("total_relevant") or 0) > 4:
                win_lines.append(self.trf("diag_more_items_fmt", count=int(summary.get("total_relevant") or 0) - 4))
        else:
            win_lines.append(self.tr("diag_gpu_pref_missing"))
        win_severity = "ok"
        if str(gaming.get("game_dvr")) == "enabled" or str(gaming.get("game_mode")) == "disabled":
            win_severity = "warn"
        self.diagnostics_cards["windows"].set_status(self._diagnostic_status_text(win_severity), "\n".join(win_lines), win_severity)

        # Disk card
        disk = dict(streaming.get("disk_write") or {})
        if disk.get("ok"):
            mbps = float(disk.get("mbps") or 0.0)
            disk_severity = "ok" if mbps >= 80.0 else "warn"
            disk_details = self.trf("diag_disk_ok_fmt", mbps=mbps, folder=str(disk.get("folder") or ""), size=int(disk.get("size_mb") or 0))
        else:
            disk_severity = "error"
            disk_details = self.trf("diag_disk_fail_fmt", folder=str(disk.get("folder") or ""), error=str(disk.get("error") or ""))
        self.diagnostics_cards["disk"].set_status(self._diagnostic_status_text(disk_severity), disk_details, disk_severity)

        # Network card
        dropped = [item for item in issues if str(item.get("kind")) == "dropped_frames"]
        activity = dict(streaming.get("obs_log_activity") or {})
        network_lines = [self.trf("diag_network_activity_fmt", stream=self.tr("yes") if activity.get("stream") else self.tr("no"), record=self.tr("yes") if activity.get("record") else self.tr("no"), replay=self.tr("yes") if activity.get("replay") else self.tr("no"))]
        if dropped:
            total = sum(int(item.get("count") or 0) for item in dropped)
            network_lines.append(self.trf("diag_network_dropped_fmt", count=total))
            network_severity = "warn"
        else:
            network_lines.append(self.tr("diag_network_no_drops"))
            network_severity = "ok"
        if activity.get("stream") and activity.get("record") and activity.get("replay"):
            network_lines.append(self.tr("diag_network_triple_warn"))
            network_severity = "warn"
        self.diagnostics_cards["network"].set_status(self._diagnostic_status_text(network_severity), "\n".join(network_lines), network_severity)

        # Recommendations card
        recs = self._build_diagnostic_recommendations(streaming, gaming)
        rec_text = "\n".join(f"• {item}" for item in recs)
        rec_severity = "ok" if recs == [self.tr("diag_rec_all_good")] else "info"
        self.diagnostics_cards["recommendations"].set_status(self._diagnostic_status_text(rec_severity), rec_text, rec_severity)

    def build_footer(self):

        self.footer = ctk.CTkFrame(self, height=198, fg_color=COLORS["bg_panel"], corner_radius=0)
        self.footer.grid(row=1, column=1, sticky="ew")
        self.footer.grid_propagate(False)

        content = ctk.CTkFrame(self.footer, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=24, pady=16)

        self.lbl_stats = ctk.CTkLabel(content, text=self.tr("freed_zero"), font=("Segoe UI", 19, "bold"), text_color=COLORS["white"])
        self.lbl_stats.pack(anchor="w")

        self.lbl_analysis = ctk.CTkLabel(content, text=self.tr("analysis_idle"), font=("Segoe UI", 12), text_color=COLORS["text_gray"])
        self.lbl_analysis.pack(anchor="w", pady=(6, 10))

        self.progress = ctk.CTkProgressBar(content, height=12, progress_color=COLORS["success"], border_width=0)
        self.progress.pack(fill="x", pady=(0, 14))
        self.progress.set(0)

        self.footer_actions = ctk.CTkFrame(content, fg_color="transparent")
        self.footer_actions.pack(fill="x")
        self.btn_start = AnimatedButton(self.footer_actions, text=self.tr("analyze_clean"), font=("Segoe UI", 16, "bold"), height=48, corner_radius=10, fg_color=COLORS["success"], hover_color="#16A34A", command=self.start_thread)
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.btn_analyze = AnimatedButton(self.footer_actions, text=self.tr("analyze_only"), font=("Segoe UI", 14, "bold"), width=160, height=48, fg_color=COLORS["system"], hover_color="#2563EB", command=self.start_analysis_thread)
        self.btn_analyze.pack(side="left", padx=(0, 8))

        self.btn_reset_all = AnimatedButton(self.footer_actions, text=self.tr("reset_all"), font=("Segoe UI", 14, "bold"), width=150, height=48, fg_color="#374151", hover_color="#4B5563", command=self.clear_selection)
        self.btn_reset_all.pack(side="left")

    def _task_paths(self, task: CleanerTask) -> List[str]:
        raw_paths: List[str] = []
        if getattr(task, "paths", None):
            raw_paths.extend([p for p in (task.paths or []) if p])
        elif task.path:
            raw_paths.append(task.path)
        return PathFinder.unique_existing(raw_paths)

    def _task_visible_signature(self, task: CleanerTask) -> Tuple[Any, ...]:
        """Signature used to merge rows that would look identical in the UI.

        Different folders belonging to the same logical cleaner action (for
        example Battle.net cache + logs, or Epic webcache variants) should be
        one checkbox with several paths, not repeated rows with identical text.
        Tasks with an app/profile/browser formatter stay separate because their
        labels are intentionally unique.
        """
        fmt = dict(task.fmt or {})
        identity_fmt = tuple(sorted((k, v) for k, v in fmt.items() if k in {"app", "browser", "profile"}))
        return (
            task.kind,
            task.category,
            task.title_key,
            task.desc_key,
            task.requires_admin,
            task.state,
            identity_fmt,
        )

    def _merge_task_paths(self, existing: CleanerTask, incoming: CleanerTask) -> None:
        merged = PathFinder.unique_existing((existing.paths or ([existing.path] if existing.path else [])) + (incoming.paths or ([incoming.path] if incoming.path else [])))
        if merged:
            existing.paths = merged
            existing.path = merged[0]

    def add_task(self, parent_card: SectionCard, task: CleanerTask):
        # Do not render duplicate actions. Duplicates made the Cleaner menu look
        # broken and could scan/clean the same folder more than once.
        if task.key in self.tasks:
            self._merge_task_paths(self.tasks[task.key], task)
            return

        if task.kind == "directory":
            unique_paths = self._task_paths(task)
            if not unique_paths:
                return
            task.paths = unique_paths
            task.path = unique_paths[0]

            visible_index = getattr(self, "_registered_visible_tasks", {})
            visible_signature = self._task_visible_signature(task)
            existing_key = visible_index.get(visible_signature)
            if existing_key and existing_key in self.tasks:
                self._merge_task_paths(self.tasks[existing_key], task)
                return

            seen_paths = getattr(self, "_registered_clean_paths", set())
            path_signature = tuple(os.path.normcase(os.path.abspath(p)) for p in unique_paths)
            if path_signature in seen_paths:
                return
            seen_paths.add(path_signature)
            self._registered_clean_paths = seen_paths
            visible_index[visible_signature] = task.key
            self._registered_visible_tasks = visible_index

        self.tasks[task.key] = task
        var = None
        if not task.instant_action:
            var = ctk.BooleanVar(value=task.default)
            var.trace_add("write", lambda *_: self.refresh_selection_stats())
            self.vars[task.key] = var
        parent_card.add_option(var, task)

    def register_system_tasks(self):
        for index, path in enumerate(PathFinder.existing(PathFinder.get_user_temp_paths())):
            self.add_task(self.card_sys, CleanerTask(
                key=f"user_temp_{index}", title_key="task.user_temp.title", desc_key="task.user_temp.desc",
                path=path, category="system", default=True, fmt={"path": path},
            ))

        sys_state = "normal" if self.is_admin else "disabled"
        for index, path in enumerate(PathFinder.existing(PathFinder.get_system_temp_paths())):
            self.add_task(self.card_sys, CleanerTask(
                key=f"sys_temp_{index}", title_key="task.system_temp.title", desc_key="task.system_temp.desc",
                path=path, category="system", default=self.is_admin, state=sys_state, requires_admin=True, fmt={"path": path},
            ))

        for key, tkey, dkey, path, requires_admin in PathFinder.get_windows_junk_targets():
            # Deep/admin-only or potentially disruptive targets are registered
            # in the Deep section below, not mixed into the quick System card.
            if key in {
                "prefetch", "update_cache_files", "delivery_opt_programdata", "delivery_opt_networkservice", "wer_system",
                "windows_logs_cbs", "windows_logs_dism", "windows_logs_mosetup", "windows_logs_waasmedic",
                "windows_setupcln_logs", "windows_wmi_diagtrack_logs", "windows_panther_logs",
                "windows_minidump", "windows_memory_dump", "windows_old",
            }:
                continue
            state = sys_state if requires_admin else "normal"
            self.add_task(self.card_sys, CleanerTask(
                key=key, title_key=tkey, desc_key=dkey, path=path, category="system",
                default=False, state=state, requires_admin=requires_admin, fmt={"path": path},
            ))

        uwp_paths = PathFinder.get_uwp_temp_cache_targets()
        if uwp_paths:
            self.add_task(self.card_sys, CleanerTask(
                key="uwp_temp_caches", title_key="task.uwp_temp_caches.title", desc_key="task.uwp_temp_caches.desc",
                path=uwp_paths[0], paths=uwp_paths, category="system", default=False,
                fmt={"count": str(len(uwp_paths)), "path": uwp_paths[0]},
            ))

    def register_browser_tasks(self):
        # Chromium exposes many separate cache folders per profile. Showing each
        # folder as a separate checkbox creates visible duplicates, so we group
        # them into one action per browser profile while still cleaning every
        # underlying cache path.
        chromium_groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for key, tkey, dkey, path, fmt in PathFinder.get_chromium_cache_targets():
            browser = fmt.get("browser", "Chromium")
            profile = fmt.get("profile", "Default")
            group_key = (browser, profile)
            group = chromium_groups.setdefault(group_key, {
                "slug": key.split("_")[1] if "_" in key else "chromium",
                "browser": browser,
                "profile": profile,
                "paths": [],
            })
            group["paths"].append(path)

        for (browser, profile), group in sorted(chromium_groups.items(), key=lambda item: item[0]):
            paths = PathFinder.unique_existing(group["paths"])
            if not paths:
                continue
            safe_key = re.sub(r"[^a-zA-Z0-9_]+", "_", f"browser_{browser}_{profile}_cache").strip("_").lower()
            self.add_task(self.card_net, CleanerTask(
                key=safe_key,
                title_key="task.browser_generic.title",
                desc_key="task.browser_generic.desc",
                path=paths[0],
                paths=paths,
                category="browsers",
                default=False,
                fmt={"browser": browser, "profile": profile, "path": paths[0]},
            ))

        firefox_groups: Dict[str, List[str]] = {}
        for key, tkey, dkey, path, fmt in PathFinder.get_firefox_cache_targets():
            profile = fmt.get("profile", "Default")
            firefox_groups.setdefault(profile, []).append(path)

        for profile, paths_raw in sorted(firefox_groups.items()):
            paths = PathFinder.unique_existing(paths_raw)
            if not paths:
                continue
            safe_key = re.sub(r"[^a-zA-Z0-9_]+", "_", f"firefox_{profile}_cache").strip("_").lower()
            self.add_task(self.card_net, CleanerTask(
                key=safe_key,
                title_key="task.firefox_cache2.title",
                desc_key="task.firefox_cache2.desc",
                path=paths[0],
                paths=paths,
                category="browsers",
                default=False,
                fmt={"profile": profile, "path": paths[0]},
            ))

        app_groups: Dict[str, Dict[str, Any]] = {}
        for key, tkey, dkey, path, fmt in PathFinder.get_app_cache_targets():
            app_name = (fmt or {}).get("app") or key.split("_")[0].title()
            base = re.sub(r"[^a-zA-Z0-9_]+", "_", app_name).strip("_").lower()
            if key.startswith("discord_"):
                base = "discord"
                app_name = "Discord"
            group = app_groups.setdefault(base, {"keys": [], "title_key": tkey, "desc_key": dkey, "paths": [], "app": app_name})
            group["keys"].append(key)
            group["paths"].append(path)

        for base, group in sorted(app_groups.items()):
            paths = PathFinder.unique_existing(group["paths"])
            if not paths:
                continue
            self.add_task(self.card_net, CleanerTask(
                key=f"{base}_cache_group",
                title_key=group["title_key"],
                desc_key=group["desc_key"],
                path=paths[0],
                paths=paths,
                category="browsers",
                default=False,
                fmt={"app": group["app"], "path": paths[0]},
            ))

        self.add_task(self.card_net, CleanerTask(
            key="dns_flush", title_key="task.dns_flush.title", desc_key="task.dns_flush.desc",
            kind="command", category="browsers", default=True,
            command=lambda: self.run_logged_command_args(["ipconfig.exe", "/flushdns"], "dns_ok", "dns_fail"),
        ))

    def register_deep_tasks(self):
        state = "normal" if self.is_admin else "disabled"
        for key, tkey, dkey, path, requires_admin in PathFinder.get_windows_junk_targets():
            if key not in {
                "prefetch", "update_cache_files", "delivery_opt_programdata", "delivery_opt_networkservice", "wer_system",
                "windows_logs_cbs", "windows_logs_dism", "windows_logs_mosetup", "windows_logs_waasmedic",
                "windows_setupcln_logs", "windows_wmi_diagtrack_logs", "windows_panther_logs",
                "windows_minidump", "windows_memory_dump", "windows_old",
            }:
                continue
            self.add_task(self.card_deep, CleanerTask(
                key=key, title_key=tkey, desc_key=dkey, path=path, category="deep", default=False,
                state=state if requires_admin else "normal", requires_admin=requires_admin, fmt={"path": path},
            ))

        self.add_task(self.card_deep, CleanerTask(
            key="recycle", title_key="task.recycle.title", desc_key="task.recycle.desc",
            kind="command", category="deep", default=False,
            command=lambda: self.log(self.tr("recycle_ok") if WindowsOps.clear_recycle_bin() else self.tr("recycle_fail")),
        ))

        self.add_task(self.card_deep, CleanerTask(
            key="registry_leftovers_conservative", title_key="task.registry_leftovers.title", desc_key="task.registry_leftovers.desc",
            kind="command", category="deep", default=False,
            command=self.cleanup_registry_leftovers,
        ))

        self.add_task(self.card_deep, CleanerTask(
            key="reset_winsock", title_key="task.reset_winsock.title", desc_key="task.reset_winsock.desc",
            kind="command", category="deep", default=False, state=state, requires_admin=True,
            command=lambda: self.run_logged_command_args(["netsh.exe", "winsock", "reset"], "winsock_ok", "winsock_fail", timeout=120),
        ))

    def register_gaming_cleanup_tasks(self):
        state = "normal" if self.is_admin else "disabled"
        for key, tkey, dkey, path, requires_admin in PathFinder.get_gaming_cache_targets():
            self.add_task(self.card_gamer, CleanerTask(
                key=key, title_key=tkey, desc_key=dkey, path=path, category="gamer", default=False,
                state=state if requires_admin else "normal", requires_admin=requires_admin, fmt={"path": path},
            ))

        streaming_groups: Dict[str, Dict[str, Any]] = {}
        for key, tkey, dkey, path, fmt in PathFinder.get_streaming_cache_targets():
            app_name = (fmt or {}).get("app") or "Streaming app"
            base = re.sub(r"[^a-zA-Z0-9_]+", "_", f"streaming_{app_name}").strip("_").lower()
            if key.endswith("logs") or "_logs" in key or key.endswith("crashes"):
                base = f"{base}_logs"
            else:
                base = f"{base}_cache"
            group = streaming_groups.setdefault(base, {"title_key": tkey, "desc_key": dkey, "paths": [], "app": app_name})
            group["paths"].append(path)

        for base, group in sorted(streaming_groups.items()):
            paths = PathFinder.unique_existing(group["paths"])
            if not paths:
                continue
            self.add_task(self.card_gamer, CleanerTask(
                key=f"{base}_group", title_key=group["title_key"], desc_key=group["desc_key"],
                path=paths[0], paths=paths, category="gamer", default=False,
                fmt={"app": group["app"], "path": paths[0]},
            ))

    def register_optimizer_tasks(self):
        state = "normal" if self.is_admin else "disabled"
        game_mode_values = [
            RegistryValueSpec(r"HKCU\Software\Microsoft\GameBar", "AllowAutoGameMode", 1, label="HKCU GameBar\\AllowAutoGameMode"),
            RegistryValueSpec(r"HKCU\Software\Microsoft\GameBar", "AutoGameModeEnabled", 1, label="HKCU GameBar\\AutoGameModeEnabled"),
        ]
        self.add_task(self.card_opt, CleanerTask(
            key="enable_game_mode", title_key="task.enable_game_mode.title", desc_key="task.enable_game_mode.desc",
            kind="command", category="optimizer", default=False, command=self.enable_game_mode,
            registry_keys=self.registry_keys_for_specs(game_mode_values),
            registry_values=game_mode_values,
        ))
        game_dvr_values = [
            RegistryValueSpec(r"HKCU\System\GameConfigStore", "GameDVR_Enabled", 0, label="HKCU GameConfigStore\\GameDVR_Enabled"),
            RegistryValueSpec(r"HKCU\System\GameConfigStore", "GameDVR_FSEBehaviorMode", 2, label="HKCU GameConfigStore\\GameDVR_FSEBehaviorMode"),
            RegistryValueSpec(r"HKCU\System\GameConfigStore", "GameDVR_HonorUserFSEBehaviorMode", 0, label="HKCU GameConfigStore\\GameDVR_HonorUserFSEBehaviorMode"),
            RegistryValueSpec(r"HKCU\System\GameConfigStore", "GameDVR_FSEBehavior", 0, label="HKCU GameConfigStore\\GameDVR_FSEBehavior"),
            RegistryValueSpec(r"HKCU\System\GameConfigStore", "GameDVR_DXGIHonorFSEWindowsCompatible", 0, label="HKCU GameConfigStore\\GameDVR_DXGIHonorFSEWindowsCompatible"),
            RegistryValueSpec(r"HKCU\Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled", 0, label="HKCU GameDVR\\AppCaptureEnabled"),
            RegistryValueSpec(r"HKCU\Software\Microsoft\Windows\CurrentVersion\GameDVR", "HistoricalCaptureEnabled", 0, label="HKCU GameDVR\\HistoricalCaptureEnabled"),
            RegistryValueSpec(r"HKCU\Software\Microsoft\Windows\CurrentVersion\GameDVR", "AudioCaptureEnabled", 0, label="HKCU GameDVR\\AudioCaptureEnabled"),
            RegistryValueSpec(r"HKCU\Software\Microsoft\GameBar", "UseNexusForGameBarEnabled", 0, label="HKCU GameBar\\UseNexusForGameBarEnabled"),
            RegistryValueSpec(r"HKCU\Software\Microsoft\GameBar", "ShowStartupPanel", 0, label="HKCU GameBar\\ShowStartupPanel"),
            RegistryValueSpec(r"HKCU\Software\Microsoft\GameBar", "AllowAutoGameMode", 1, label="HKCU GameBar\\AllowAutoGameMode"),
            RegistryValueSpec(r"HKCU\Software\Microsoft\GameBar", "AutoGameModeEnabled", 1, label="HKCU GameBar\\AutoGameModeEnabled"),
            RegistryValueSpec(r"HKLM\SOFTWARE\Policies\Microsoft\Windows\GameDVR", "AllowGameDVR", 0, label="HKLM Policy GameDVR\\AllowGameDVR", requires_admin=True),
        ]
        self.add_task(self.card_opt, CleanerTask(
            key="disable_gamedvr", title_key="task.disable_gamedvr.title", desc_key="task.disable_gamedvr.desc",
            kind="command", category="optimizer", default=False, command=self.disable_game_dvr,
            registry_keys=self.registry_keys_for_specs(game_dvr_values),
            registry_values=game_dvr_values,
            reboot_required=True,
        ))
        mouse_values = [
            RegistryValueSpec(r"HKCU\Control Panel\Mouse", "MouseSpeed", "0", "REG_SZ", label="HKCU Mouse\\MouseSpeed"),
            RegistryValueSpec(r"HKCU\Control Panel\Mouse", "MouseThreshold1", "0", "REG_SZ", label="HKCU Mouse\\MouseThreshold1"),
            RegistryValueSpec(r"HKCU\Control Panel\Mouse", "MouseThreshold2", "0", "REG_SZ", label="HKCU Mouse\\MouseThreshold2"),
        ]
        self.add_task(self.card_opt, CleanerTask(
            key="disable_mouse_acceleration", title_key="task.disable_mouse_acceleration.title", desc_key="task.disable_mouse_acceleration.desc",
            kind="command", category="optimizer", default=False, command=self.disable_mouse_acceleration,
            registry_keys=self.registry_keys_for_specs(mouse_values),
            registry_values=mouse_values,
        ))
        self.add_task(self.card_opt, CleanerTask(
            key="high_perf_plan", title_key="task.high_perf_plan.title", desc_key="task.high_perf_plan.desc",
            kind="command", category="optimizer", default=False, state=state, requires_admin=True,
            command=lambda: self.run_logged_command_args(["powercfg.exe", "/S", "SCHEME_MIN"], "high_perf_ok", "high_perf_fail", timeout=90),
        ))
        self.add_task(self.card_opt, CleanerTask(
            key="safe_gaming_power_profile", title_key="task.safe_gaming_power_profile.title", desc_key="task.safe_gaming_power_profile.desc",
            kind="command", category="optimizer", default=False, state=state, requires_admin=True,
            command=self.apply_safe_gaming_power_profile,
        ))
        self.add_task(self.card_opt, CleanerTask(
            key="purge_standby_ram", title_key="task.purge_standby_ram.title", desc_key="task.purge_standby_ram.desc",
            kind="command", category="optimizer", default=False, state=state, requires_admin=True,
            command=self.purge_standby_ram,
        ))
        self.add_task(self.card_opt, CleanerTask(
            key="cpu_latency_power_profile", title_key="task.cpu_latency_power_profile.title", desc_key="task.cpu_latency_power_profile.desc",
            kind="command", category="optimizer", default=False, state=state, requires_admin=True,
            command=self.apply_cpu_latency_power_profile,
        ))
        self.add_task(self.card_opt, CleanerTask(
            key="restore_balanced_power_profile", title_key="task.restore_balanced_power_profile.title", desc_key="task.restore_balanced_power_profile.desc",
            kind="command", category="optimizer", default=False, state=state, requires_admin=True,
            command=self.restore_balanced_power_profile,
        ))
        ultimate_state = state if WindowsOps.supports_ultimate_performance() else "disabled"
        self.add_task(self.card_opt, CleanerTask(
            key="ultimate_perf_plan", title_key="task.ultimate_perf_plan.title", desc_key="task.ultimate_perf_plan.desc",
            kind="command", category="optimizer", default=False, state=ultimate_state, requires_admin=True, command=self.enable_ultimate_performance,
        ))

    def register_optimizer_registry_tasks(self):
        state = "normal" if self.is_admin else "disabled"
        hags_on_values = [
            RegistryValueSpec(r"HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode", 2, label="HKLM GraphicsDrivers\\HwSchMode", requires_admin=True),
        ]
        self.add_task(self.card_opt_adv, CleanerTask(
            key="enable_hags", title_key="task.enable_hags.title", desc_key="task.enable_hags.desc",
            kind="command", category="optimizer", default=False, state=state if WindowsOps.supports_hags() else "disabled", requires_admin=True,
            command=self.enable_hags,
            registry_keys=self.registry_keys_for_specs(hags_on_values),
            registry_values=hags_on_values,
            reboot_required=True,
        ))
        hags_values = [
            RegistryValueSpec(r"HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode", 1, label="HKLM GraphicsDrivers\\HwSchMode", requires_admin=True),
        ]
        self.add_task(self.card_opt_adv, CleanerTask(
            key="disable_hags", title_key="task.disable_hags.title", desc_key="task.disable_hags.desc",
            kind="command", category="optimizer", default=False, state=state if WindowsOps.supports_hags() else "disabled", requires_admin=True,
            command=self.disable_hags,
            registry_keys=self.registry_keys_for_specs(hags_values),
            registry_values=hags_values,
            reboot_required=True,
        ))
        power_throttling_values = [
            RegistryValueSpec(r"HKLM\SYSTEM\CurrentControlSet\Control\Power\PowerThrottling", "PowerThrottlingOff", 1, label="HKLM PowerThrottling\\PowerThrottlingOff", requires_admin=True),
        ]
        self.add_task(self.card_opt_adv, CleanerTask(
            key="disable_power_throttling", title_key="task.disable_power_throttling.title", desc_key="task.disable_power_throttling.desc",
            kind="command", category="optimizer", default=False, state=state if WindowsOps.supports_power_throttling() else "disabled", requires_admin=True,
            command=self.disable_power_throttling,
            registry_keys=self.registry_keys_for_specs(power_throttling_values),
            registry_values=power_throttling_values,
            reboot_required=True,
        ))
        network_values = [
            RegistryValueSpec(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile", "NetworkThrottlingIndex", "0xffffffff", label="HKLM SystemProfile\\NetworkThrottlingIndex", requires_admin=True),
        ]
        self.add_task(self.card_opt_adv, CleanerTask(
            key="network_throttling_off", title_key="task.network_throttling_off.title", desc_key="task.network_throttling_off.desc",
            kind="command", category="optimizer", default=False, state=state, requires_admin=True,
            command=self.disable_network_throttling,
            registry_keys=self.registry_keys_for_specs(network_values),
            registry_values=network_values,
            reboot_required=True,
        ))
        mmcss_values = [
            RegistryValueSpec(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile", "SystemResponsiveness", 10, label="HKLM SystemProfile\\SystemResponsiveness", requires_admin=True),
            RegistryValueSpec(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games", "GPU Priority", 8, label="HKLM Tasks\\Games\\GPU Priority", requires_admin=True),
            RegistryValueSpec(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games", "Priority", 6, label="HKLM Tasks\\Games\\Priority", requires_admin=True),
            RegistryValueSpec(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games", "Scheduling Category", "High", "REG_SZ", label="HKLM Tasks\\Games\\Scheduling Category", requires_admin=True),
            RegistryValueSpec(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games", "SFIO Priority", "High", "REG_SZ", label="HKLM Tasks\\Games\\SFIO Priority", requires_admin=True),
        ]
        self.add_task(self.card_opt_adv, CleanerTask(
            key="mmcss_gaming_profile", title_key="task.mmcss_gaming_profile.title", desc_key="task.mmcss_gaming_profile.desc",
            kind="command", category="optimizer", default=False, state=state, requires_admin=True,
            command=self.apply_mmcss_gaming_profile,
            registry_keys=self.registry_keys_for_specs(mmcss_values),
            registry_values=mmcss_values,
            reboot_required=True,
        ))
        dyn_tick_state = state if WindowsOps.supports_dynamic_tick_toggle() else "disabled"
        self.add_task(self.card_opt_adv, CleanerTask(
            key="disable_dynamic_tick_latency", title_key="task.disable_dynamic_tick_latency.title", desc_key="task.disable_dynamic_tick_latency.desc",
            kind="command", category="optimizer", default=False, state=dyn_tick_state, requires_admin=True,
            command=self.disable_dynamic_tick_latency,
            reboot_required=True,
        ))
        self.add_task(self.card_opt_adv, CleanerTask(
            key="restore_dynamic_tick_default", title_key="task.restore_dynamic_tick_default.title", desc_key="task.restore_dynamic_tick_default.desc",
            kind="command", category="optimizer", default=False, state=dyn_tick_state, requires_admin=True,
            command=self.restore_dynamic_tick_default,
            reboot_required=True,
        ))

    def register_optimizer_helper_tasks(self):
        self.add_task(self.card_opt_tools, CleanerTask(
            key="streaming_diagnostics", title_key="task.streaming_diagnostics.title", desc_key="task.streaming_diagnostics.desc",
            kind="command", category="optimizer", default=False, instant_action=True, command=self.run_streaming_diagnostics,
        ))
        self.add_task(self.card_opt_tools, CleanerTask(
            key="gaming_compat_report", title_key="task.gaming_compat_report.title", desc_key="task.gaming_compat_report.desc",
            kind="command", category="optimizer", default=False, instant_action=True, command=self.run_gaming_compat_report,
        ))
        self.add_task(self.card_opt_tools, CleanerTask(
            key="refresh_registry_statuses", title_key="task.refresh_registry_statuses.title", desc_key="task.refresh_registry_statuses.desc",
            kind="command", category="optimizer", default=False, instant_action=True, command=self.refresh_registry_statuses,
        ))
        self.add_task(self.card_opt_tools, CleanerTask(
            key="open_game_mode_settings", title_key="task.open_game_mode_settings.title", desc_key="task.open_game_mode_settings.desc",
            kind="command", category="optimizer", default=False, instant_action=True, command=lambda: self.open_settings_uri("ms-settings:gaming-gamemode", "game_mode_page_ok", "game_mode_page_fail"),
        ))
        self.add_task(self.card_opt_tools, CleanerTask(
            key="open_capture_settings", title_key="task.open_capture_settings.title", desc_key="task.open_capture_settings.desc",
            kind="command", category="optimizer", default=False, instant_action=True, command=lambda: self.open_settings_uri("ms-settings:gaming-gamedvr", "captures_page_ok", "captures_page_fail"),
        ))
        self.add_task(self.card_opt_tools, CleanerTask(
            key="disable_notifications", title_key="task.disable_notifications.title", desc_key="task.disable_notifications.desc",
            kind="command", category="optimizer", default=False, instant_action=True, command=lambda: self.open_settings_uri("ms-settings:quiethours", "focus_assist_ok", "focus_assist_fail"),
        ))
        self.add_task(self.card_opt_tools, CleanerTask(
            key="open_visual_effects", title_key="task.open_visual_effects.title", desc_key="task.open_visual_effects.desc",
            kind="command", category="optimizer", default=False, instant_action=True, command=self.open_visual_effects_settings,
        ))
        self.add_task(self.card_opt_tools, CleanerTask(
            key="open_graphics_defaults", title_key="task.open_graphics_defaults.title", desc_key="task.open_graphics_defaults.desc",
            kind="command", category="optimizer", default=False, instant_action=True, command=lambda: self.open_settings_uri("ms-settings:display-advancedgraphics-default", "graphics_defaults_ok", "graphics_defaults_fail"),
        ))
        self.add_task(self.card_opt_tools, CleanerTask(
            key="open_graphics_apps", title_key="task.open_graphics_apps.title", desc_key="task.open_graphics_apps.desc",
            kind="command", category="optimizer", default=False, instant_action=True, command=lambda: self.open_settings_uri("ms-settings:display-advancedgraphics", "graphics_apps_ok", "graphics_apps_fail"),
        ))
        self.add_task(self.card_opt_tools, CleanerTask(
            key="open_power_mode_settings", title_key="task.open_power_mode_settings.title", desc_key="task.open_power_mode_settings.desc",
            kind="command", category="optimizer", default=False, instant_action=True, command=lambda: self.open_settings_uri("ms-settings:powersleep", "power_mode_page_ok", "power_mode_page_fail"),
        ))
        self.add_task(self.card_opt_tools, CleanerTask(
            key="open_core_isolation", title_key="task.open_core_isolation.title", desc_key="task.open_core_isolation.desc",
            kind="command", category="optimizer", default=False, instant_action=True, command=self.open_core_isolation_settings,
        ))

    def register_ultimate_tasks(self):

        state = "normal" if self.is_admin else "disabled"
        self.add_task(self.card_ult, CleanerTask(
            key="dism_clean", title_key="task.dism_clean.title", desc_key="task.dism_clean.desc",
            kind="command", category="ultimate", default=False, state=state, requires_admin=True,
            command=self.run_dism_cleanup, danger="heavy",
        ))

    def schedule_search_filter(self):
        pending = getattr(self, "_search_after_id", None)
        if pending:
            try:
                self.after_cancel(pending)
            except Exception:
                pass
        self._search_after_id = self.after(100, self.apply_search_filter)

    def apply_search_filter(self, force: bool = False):
        self._search_after_id = None
        query = self.search_var.get()
        normalized_query = self._normalize_search_text(query)
        if not force and normalized_query == self._last_search_query:
            return
        self._last_search_query = normalized_query
        for card in self.section_cards:
            visible_rows = card.filter_rows(normalized_query)
            try:
                if visible_rows > 0:
                    card.grid()
                else:
                    card.grid_remove()
            except Exception:
                pass

    def refresh_selection_stats(self):
        if getattr(self, "_selection_refresh_suspended", False):
            return
        count = 0
        for key, var in self.vars.items():
            if not var.get():
                continue
            task = self.tasks.get(key)
            if not task or (task.requires_admin and not self.is_admin):
                continue
            count += 1
        self.card_selected.set(str(count), COLORS["white"] if count else COLORS["muted"])
        if self.analysis_total_bytes > 0:
            self.card_estimate.set(f"{self.analysis_total_bytes / (1024 ** 2):.1f} MB", COLORS["system"])
        else:
            self.card_estimate.set("—", COLORS["muted"])

    def set_profile_name(self, name: str, color: str):
        self.current_profile_name = name
        self.card_profile.set(name, color)

    def log(self, text: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_queue.put(f"[{timestamp}] {text}")

    def flush_log_queue(self):
        messages: List[str] = []
        batch_limit = 80
        while len(messages) < batch_limit:
            try:
                messages.append(self.log_queue.get_nowait())
            except queue.Empty:
                break
        if messages:
            self.console.configure(state="normal")
            self.console.insert("end", "\n".join(messages) + "\n")
            self._log_line_count += len(messages)
            if self._log_line_count > self._max_log_lines:
                overflow = self._log_line_count - self._max_log_lines
                try:
                    self.console.delete("1.0", f"{overflow + 1}.0")
                    self._log_line_count = self._max_log_lines
                except Exception:
                    pass
            self.console.see("end")
            self.console.configure(state="disabled")
        self.after(60 if messages else 160, self.flush_log_queue)

    def copy_log_to_clipboard(self):
        content = self.console.get("1.0", "end")
        self.clipboard_clear()
        self.clipboard_append(content)
        self.log(self.tr("log_copied"))

    def clear_log(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self._log_line_count = 0
        self.console.configure(state="disabled")
        self.log(self.tr("log_cleared"))

    def clear_selection(self):
        self._selection_refresh_suspended = True
        try:
            for key, var in self.vars.items():
                if self.tasks[key].state != "disabled" and var.get():
                    var.set(False)
        finally:
            self._selection_refresh_suspended = False
        self.analysis_total_bytes = 0
        self.total_size_bytes = 0
        self.lbl_analysis.configure(text=self.tr("selected_reset_hint"), text_color=COLORS["text_gray"])
        self.set_profile_name(self.tr("profile_manual"), COLORS["gamer"])
        self.refresh_selection_stats()
        self.log(self.tr("selection_cleared"))

    def _set_task_selected(self, key: str, selected: bool) -> None:
        var = self.vars.get(key)
        if var is not None and var.get() != selected:
            var.set(selected)

    def invoke_instant_task(self, task: CleanerTask):
        if task.state == "disabled":
            self.log(self.tr("admin_required_for_this"))
            return
        if not task.command:
            return
        self.log(self.trf("action_fmt", title=self.task_title(task)))
        try:
            task.command()
        except Exception:
            self.log(self.trf("action_error_fmt", title=self.task_title(task)))

    def _select_tasks_by_rule(self, rule: Callable[[CleanerTask], bool]) -> None:
        self._selection_refresh_suspended = True
        try:
            for key, var in self.vars.items():
                task = self.tasks.get(key)
                if not task or task.state == "disabled":
                    continue
                self._set_task_selected(key, bool(rule(task)))
        finally:
            self._selection_refresh_suspended = False

    def _is_safe_cache_task(self, task: CleanerTask) -> bool:
        if task.kind != "directory" or task.requires_admin:
            return False
        if task.category in {"system", "browsers"}:
            return True
        return task.category == "gamer" and any(token in task.key for token in ("cache", "webcache", "htmlcache", "obs"))

    def _is_gaming_cleanup_task(self, task: CleanerTask) -> bool:
        if task.kind == "command":
            return task.key in {
                "dns_flush", "enable_game_mode", "disable_gamedvr", "disable_mouse_acceleration",
                "disable_notifications", "safe_gaming_power_profile", "purge_standby_ram",
                "disable_power_throttling", "mmcss_gaming_profile",
            }
        if task.kind != "directory":
            return False
        if task.category in {"browsers", "gamer"}:
            return True
        return task.category == "system" and task.key in {
            "thumb_cache", "inet_cache", "web_cache", "crash_dumps_user", "wer_user",
            "jump_lists_auto", "jump_lists_custom", "recent_docs",
        }

    def _is_streaming_cleanup_task(self, task: CleanerTask) -> bool:
        if task.kind == "command":
            return task.key in {
                "dns_flush", "enable_game_mode", "disable_gamedvr", "safe_gaming_power_profile",
                "purge_standby_ram", "network_throttling_off", "mmcss_gaming_profile",
            }
        if task.kind != "directory":
            return False
        if task.category == "gamer":
            return True
        if task.category == "browsers":
            return any(token in task.key for token in ("discord", "obs", "streamlabs", "twitch", "xsplit"))
        if task.category != "system":
            return False
        if task.key.startswith("user_temp_"):
            return True
        return task.key in {
            "thumb_cache", "inet_cache", "web_cache", "crash_dumps_user", "wer_user",
            "windows_caches_user", "uwp_temp_caches",
        }

    def _is_deep_clean_task(self, task: CleanerTask) -> bool:
        if task.kind == "command":
            return task.key in {"dns_flush", "recycle"}
        if task.kind != "directory":
            return False
        if task.key == "windows_old":
            # Windows.old removes rollback files after a Windows upgrade, so keep
            # it manual even in the deep profile.
            return False
        if task.category in {"system", "browsers", "gamer", "deep"}:
            return True
        return False

    def apply_safe_preset(self):
        self.clear_selection()
        self._select_tasks_by_rule(self._is_safe_cache_task)
        if "dns_flush" in self.tasks:
            self._set_task_selected("dns_flush", True)
        self.set_profile_name(self.tr("safe"), COLORS["system"])
        self.refresh_selection_stats()
        self.log(self.tr("safe_profile_on"))

    def apply_gaming_mode(self):
        self.clear_selection()
        self._select_tasks_by_rule(self._is_gaming_cleanup_task)
        if self.is_admin:
            for key in ("battle_net_cache", "battle_net_agent_logs", "nvidia_nv_cache", "gog_cache"):
                if key in self.tasks:
                    self._set_task_selected(key, True)
        self.set_profile_name(self.tr("profile_gaming"), COLORS["gamer"])
        self.refresh_selection_stats()
        self.log(self.tr("gaming_profile_on"))

    def apply_streaming_mode(self):
        self.clear_selection()
        self._select_tasks_by_rule(self._is_streaming_cleanup_task)
        if self.is_admin:
            for key in (
                "safe_gaming_power_profile", "purge_standby_ram", "network_throttling_off",
                "mmcss_gaming_profile", "battle_net_cache", "battle_net_agent_logs", "nvidia_nv_cache",
            ):
                if key in self.tasks:
                    self._set_task_selected(key, True)
        self.set_profile_name(self.tr("profile_streamer"), COLORS["gamer"])
        self.refresh_selection_stats()
        self.log(self.tr("streamer_profile_on"))

    def apply_deep_clean_mode(self):
        self.clear_selection()
        self._select_tasks_by_rule(self._is_deep_clean_task)
        self.set_profile_name(self.tr("profile_deep"), COLORS["success"])
        self.refresh_selection_stats()
        self.log(self.tr("deep_profile_on"))

    def run_as_admin(self):
        self.log(self.tr("relaunching_admin"))
        WindowsOps.run_as_admin()
        self.destroy()

    def cancel_current_run(self):
        if self.is_running:
            self.cancel_event.set()
            self.log(self.tr("stop_requested"))

    def set_running_state(self, running: bool):
        self.is_running = running
        self.btn_start.configure(
            state="disabled" if running else "normal",
            text=self.tr("running") if running else self.tr("analyze_clean"),
            fg_color="#4B5563" if running else COLORS["success"],
        )
        self.btn_analyze.configure(state="disabled" if running else "normal")
        self.btn_cancel.configure(state="normal" if running else "disabled")
        if running:
            self.start_running_animation()
        else:
            self.stop_running_animation()
            self.progress.stop()

    def start_running_animation(self) -> None:
        self.stop_running_animation(reset=False)
        self._running_pulse_phase = 0
        self._animate_running_state()

    def _animate_running_state(self) -> None:
        if not getattr(self, "is_running", False):
            return
        phase = getattr(self, "_running_pulse_phase", 0) % 4
        colors = ["#4B5563", "#526176", "#64748B", "#526176"]
        progress_colors = [COLORS["system"], COLORS["gamer"], COLORS["success"], COLORS["gamer"]]
        try:
            self.btn_start.configure(fg_color=colors[phase])
            self.progress.configure(progress_color=progress_colors[phase])
        except Exception:
            return
        self._running_pulse_phase = phase + 1
        self._running_pulse_after_id = self.after(420, self._animate_running_state)

    def stop_running_animation(self, *, reset: bool = True) -> None:
        pending = getattr(self, "_running_pulse_after_id", None)
        if pending:
            try:
                self.after_cancel(pending)
            except Exception:
                pass
        self._running_pulse_after_id = None
        pending_progress = getattr(self, "_progress_anim_after_id", None)
        if pending_progress:
            try:
                self.after_cancel(pending_progress)
            except Exception:
                pass
        self._progress_anim_after_id = None
        if reset:
            try:
                self.btn_start.configure(fg_color=COLORS["success"])
                self.progress.configure(progress_color=COLORS["success"])
            except Exception:
                pass

    def run_logged_command(self, cmd: str, success_key: str, fail_key: str, timeout: int = 180):
        ok = WindowsOps.run_command(cmd, timeout=timeout)
        self.log(self.tr(success_key) if ok else self.tr(fail_key))

    def run_logged_command_args(self, args: List[str], success_key: str, fail_key: str, timeout: int = 180, noisy: bool = False):
        ok = WindowsOps.run_command_args(args, timeout=timeout, noisy=noisy)
        self.log(self.tr(success_key) if ok else self.tr(fail_key))

    def apply_registry_task_values(self, task_key: str, success_key: str, fail_key: str) -> bool:
        task = self.tasks.get(task_key)
        specs = list(task.registry_values or []) if task else []
        runnable = [spec for spec in specs if not spec.requires_admin or self.is_admin]
        skipped_admin = [spec for spec in specs if spec.requires_admin and not self.is_admin]
        results = WindowsOps.apply_registry_values(runnable)
        ok = bool(results) and all(results)
        self.log(self.tr(success_key) if ok else self.tr(fail_key))
        if ok and skipped_admin:
            self.log(self.tr("registry_admin_values_skipped"))
        self.refresh_registry_status_descriptions()
        return ok

    def open_settings_uri(self, uri: str, success_key: str, fail_key: str):
        ok = False
        if IS_WINDOWS and WindowsOps.supports_ms_settings():
            try:
                os.startfile(uri)  # type: ignore[attr-defined]
                ok = True
            except Exception:
                ok = WindowsOps.run_command_args(["explorer.exe", uri], timeout=20)
        if not ok:
            # If a specific ms-settings URI is unavailable on a Windows 10/11 build,
            # fall back to Control Panel instead of logging a false hard error.
            ok = WindowsOps.run_command_args(["control.exe"], timeout=20)
        self.log(self.tr(success_key) if ok else self.tr(fail_key))

    def open_visual_effects_settings(self):
        ok = WindowsOps.run_command_args(["SystemPropertiesPerformance.exe"], timeout=20)
        self.log(self.tr("visual_effects_ok") if ok else self.tr("visual_effects_fail"))

    def open_core_isolation_settings(self):
        ok = False
        for uri in ("windowsdefender://coreisolation", "windowsdefender://DeviceSecurity", "ms-settings:windowsdefender"):
            if IS_WINDOWS:
                try:
                    os.startfile(uri)  # type: ignore[attr-defined]
                    ok = True
                    break
                except Exception:
                    ok = WindowsOps.run_command_args(["explorer.exe", uri], timeout=20)
                    if ok:
                        break
        self.log(self.tr("core_isolation_page_ok") if ok else self.tr("core_isolation_page_fail"))



    def _diagnostic_encoder_kind(self, encoder: str) -> str:
        name = (encoder or "").casefold()
        if not name or name == "unknown":
            return "unknown"
        if any(token in name for token in ("nvenc", "qsv", "amf", "vce", "vaapi", "videotoolbox", "av1", "hevc", "h264_texture")):
            return "hardware"
        if "x264" in name or "x265" in name:
            return "cpu"
        return "unknown"

    def run_streaming_diagnostics(self):
        self.log(self.tr("streaming_diag_started"))
        try:
            report = WindowsOps.collect_streaming_diagnostics()
        except Exception:
            self.log(self.tr("streaming_diag_failed"))
            return

        profiles = list(report.get("obs_profiles") or [])
        if not profiles:
            self.log(self.tr("obs_profile_missing"))
        for profile in profiles:
            name = str(profile.get("name") or "OBS")
            output_mode = str(profile.get("output_mode") or "unknown")
            stream_encoder = str(profile.get("stream_encoder") or "unknown")
            record_encoder = str(profile.get("record_encoder") or "unknown")
            record_format = str(profile.get("record_format") or "unknown")
            replay_buffer = bool(profile.get("replay_buffer"))
            self.log(self.trf(
                "obs_profile_summary_fmt",
                profile=name,
                mode=output_mode,
                stream=stream_encoder,
                record=record_encoder,
                format=record_format,
                replay=self.tr("yes") if replay_buffer else self.tr("no"),
            ))
            for label_key, encoder in (("obs_stream_encoder", stream_encoder), ("obs_record_encoder", record_encoder)):
                kind = self._diagnostic_encoder_kind(encoder)
                if kind == "hardware":
                    self.log(self.trf("obs_encoder_hw_ok_fmt", label=self.tr(label_key), encoder=encoder))
                elif kind == "cpu":
                    self.log(self.trf("obs_encoder_cpu_warn_fmt", label=self.tr(label_key), encoder=encoder))
                else:
                    self.log(self.trf("obs_encoder_unknown_fmt", label=self.tr(label_key), encoder=encoder))
            if record_format in {"mkv", "hybrid_mp4"}:
                self.log(self.trf("obs_rec_format_ok_fmt", profile=name, format=record_format))
            elif record_format and record_format != "unknown":
                self.log(self.trf("obs_rec_format_warn_fmt", profile=name, format=record_format))
            if replay_buffer:
                self.log(self.tr("obs_replay_combo_warn"))

        activity = dict(report.get("obs_log_activity") or {})
        if activity.get("stream") and activity.get("record") and activity.get("replay"):
            self.log(self.tr("obs_log_triple_activity_warn"))

        issues = list(report.get("obs_log_issues") or [])
        if issues:
            seen = set()
            for issue in issues:
                kind = str(issue.get("kind") or "unknown")
                count = int(issue.get("count") or 0)
                log_name = str(issue.get("log") or "OBS log")
                key = (kind, log_name)
                if key in seen:
                    continue
                seen.add(key)
                issue_text = self.tr(f"obs_log_issue_{kind}")
                self.log(self.trf("obs_log_issue_fmt", issue=issue_text, count=count, log=log_name))
        else:
            self.log(self.tr("obs_logs_clean"))

        cpu = report.get("cpu_load")
        ram = report.get("ram_load")
        gpu = report.get("gpu_load")
        cpu_text = f"{float(cpu):.0f}%" if isinstance(cpu, (int, float)) else "—"
        ram_text = f"{float(ram):.0f}%" if isinstance(ram, (int, float)) else "—"
        gpu_text = f"{float(gpu):.0f}%" if isinstance(gpu, (int, float)) else self.tr("unavailable_short")
        self.log(self.trf("streaming_load_fmt", cpu=cpu_text, ram=ram_text, gpu=gpu_text))
        if isinstance(cpu, (int, float)) and float(cpu) >= 85.0:
            self.log(self.tr("streaming_cpu_high_warn"))
        if isinstance(gpu, (int, float)) and float(gpu) >= 90.0:
            self.log(self.tr("streaming_gpu_high_warn"))

        disk = dict(report.get("disk_write") or {})
        if disk.get("ok"):
            mbps = float(disk.get("mbps") or 0.0)
            folder = str(disk.get("folder") or "")
            self.log(self.trf("disk_write_ok_fmt", mbps=mbps, folder=folder))
            if mbps < 80.0:
                self.log(self.tr("disk_write_low_warn"))
        else:
            self.log(self.trf("disk_write_fail_fmt", folder=str(disk.get("folder") or "")))

        self.log(self.tr("streaming_diag_done"))

    def run_gaming_compat_report(self):
        self.log(self.tr("gaming_report_started"))
        try:
            report = WindowsOps.collect_gaming_compat_report()
        except Exception:
            self.log(self.tr("gaming_report_failed"))
            return

        self.log(self.trf(
            "gaming_report_system_fmt",
            version=report.get("windows_version", "—"),
            admin=self.tr("yes") if self.is_admin else self.tr("no"),
            arch=report.get("process_arch", "—"),
            osarch=report.get("os_arch", "—"),
        ))
        power = str(report.get("active_power_scheme") or "—").strip() or "—"
        self.log(self.trf("gaming_report_power_fmt", plan=power))

        for key, label_key in (
            ("game_mode", "gaming_report_game_mode"),
            ("game_dvr", "gaming_report_game_dvr"),
            ("hags", "gaming_report_hags"),
            ("power_throttling", "gaming_report_power_throttling"),
            ("dynamic_tick", "gaming_report_dynamic_tick"),
        ):
            state = str(report.get(key) or "unknown")
            state_text = self.tr(f"gaming_state_{state}")
            self.log(self.trf("gaming_report_item_fmt", item=self.tr(label_key), state=state_text))

        notes = list(report.get("notes") or [])
        if notes:
            for note in notes:
                self.log(self.tr(str(note)))
        else:
            self.log(self.tr("gaming_report_no_critical_notes"))
        self.log(self.tr("gaming_report_done"))

    def cleanup_registry_leftovers(self):
        include_machine = bool(self.is_admin)
        result = WindowsOps.cleanup_registry_leftovers(include_machine=include_machine)
        found = int(result.get("found", 0) or 0)
        removed = int(result.get("removed", 0) or 0)
        failed = int(result.get("failed", 0) or 0)
        keys_removed = int(result.get("keys_removed", 0) or 0)
        values_removed = int(result.get("values_removed", 0) or 0)
        backup = str(result.get("backup") or "")
        if found <= 0:
            self.log(self.tr("registry_leftovers_none"))
            if not include_machine:
                self.log(self.tr("registry_leftovers_limited_mode"))
            return
        if backup:
            self.log(self.trf("registry_backup_created", path=backup))
        self.log(self.trf(
            "registry_leftovers_done_fmt",
            found=found,
            removed=removed,
            keys=keys_removed,
            values=values_removed,
            failed=failed,
        ))
        if not include_machine:
            self.log(self.tr("registry_leftovers_limited_mode"))

    def disable_game_dvr(self):
        self.apply_registry_task_values("disable_gamedvr", "game_dvr_ok", "game_dvr_fail")

    def enable_game_mode(self):
        self.apply_registry_task_values("enable_game_mode", "game_mode_ok", "game_mode_fail")

    def apply_safe_gaming_power_profile(self):
        ok = WindowsOps.apply_safe_gaming_power_profile()
        self.log(self.tr("safe_gaming_power_ok") if ok else self.tr("safe_gaming_power_fail"))

    def apply_cpu_latency_power_profile(self):
        ok = WindowsOps.apply_cpu_latency_performance_profile()
        self.log(self.tr("cpu_latency_power_ok") if ok else self.tr("cpu_latency_power_fail"))

    def restore_balanced_power_profile(self):
        ok = WindowsOps.restore_balanced_power_profile()
        self.log(self.tr("balanced_power_restore_ok") if ok else self.tr("balanced_power_restore_fail"))

    def purge_standby_ram(self):
        ok = WindowsOps.purge_standby_memory()
        self.log(self.tr("standby_ram_ok") if ok else self.tr("standby_ram_fail"))

    def disable_mouse_acceleration(self):
        self.apply_registry_task_values("disable_mouse_acceleration", "mouse_acceleration_ok", "mouse_acceleration_fail")

    def enable_hags(self):
        if not WindowsOps.supports_hags():
            self.log(self.tr("hags_on_fail"))
            return
        self.apply_registry_task_values("enable_hags", "hags_on_ok", "hags_on_fail")

    def disable_hags(self):
        if not WindowsOps.supports_hags():
            self.log(self.tr("hags_off_fail"))
            return
        self.apply_registry_task_values("disable_hags", "hags_off_ok", "hags_off_fail")

    def disable_power_throttling(self):
        if not WindowsOps.supports_power_throttling():
            self.log(self.tr("power_throttling_fail"))
            return
        self.apply_registry_task_values("disable_power_throttling", "power_throttling_ok", "power_throttling_fail")

    def disable_network_throttling(self):
        self.apply_registry_task_values("network_throttling_off", "network_throttling_ok", "network_throttling_fail")

    def apply_mmcss_gaming_profile(self):
        self.apply_registry_task_values("mmcss_gaming_profile", "mmcss_profile_ok", "mmcss_profile_fail")

    def disable_dynamic_tick_latency(self):
        ok = WindowsOps.set_dynamic_tick_disabled(True)
        self.log(self.tr("dynamic_tick_off_ok") if ok else self.tr("dynamic_tick_off_fail"))

    def restore_dynamic_tick_default(self):
        ok = WindowsOps.restore_dynamic_tick_default()
        self.log(self.tr("dynamic_tick_restore_ok") if ok else self.tr("dynamic_tick_restore_fail"))

    def enable_ultimate_performance(self):
        if not WindowsOps.supports_ultimate_performance():
            self.log(self.tr("ultimate_perf_fail"))
            return
        ok = WindowsOps.try_enable_ultimate_performance()
        self.log(self.tr("ultimate_perf_ok") if ok else self.tr("ultimate_perf_fail"))

    def run_dism_cleanup(self):
        self.dism_running = True
        try:
            self.log(self.tr("dism_started"))
            # Keep DISM cleanup reversible.  /ResetBase saves a bit more space
            # but prevents uninstalling already installed component updates, so
            # it should not be silently bundled into a general cleanup action.
            ok = WindowsOps.run_command_args(["dism.exe", "/Online", "/Cleanup-Image", "/StartComponentCleanup"], timeout=3600, noisy=True)
            self.log(self.tr("dism_ok") if ok else self.tr("dism_fail"))
        finally:
            self.dism_running = False

    def start_analysis_thread(self):
        if self.is_running:
            return
        self.cancel_event.clear()
        self._progress_target_value = 0.0
        self._progress_display_value = 0.0
        self.progress.set(0)
        self.progress.start()
        self.set_running_state(True)
        threading.Thread(target=self.analysis_only_engine, daemon=True).start()

    def start_thread(self):
        if self.is_running:
            return
        self.cancel_event.clear()
        self.cleaned_bytes = 0
        self.total_size_bytes = 0
        self._last_progress_ui_at = 0.0
        self._last_progress_ui_bytes = 0
        self._progress_target_value = 0.0
        self._progress_display_value = 0.0
        self.progress.set(0)
        self.progress.start()
        self.set_running_state(True)
        threading.Thread(target=self.engine, daemon=True).start()

    def selected_tasks(self) -> List[CleanerTask]:
        chosen = []
        for key, var in self.vars.items():
            if not var.get():
                continue
            task = self.tasks.get(key)
            if not task:
                continue
            if task.requires_admin and not self.is_admin:
                continue
            chosen.append(task)
        return self.resolve_selected_task_conflicts(chosen)

    def resolve_selected_task_conflicts(self, chosen: List[CleanerTask]) -> List[CleanerTask]:
        keys = {task.key for task in chosen}
        skip: set[str] = set()
        if "enable_hags" in keys and "disable_hags" in keys:
            # These are exact opposites.  Do not silently let whichever task runs
            # last win, because that makes registry state unpredictable.
            skip.update({"enable_hags", "disable_hags"})
            self.log(self.tr("hags_conflict_skipped"))
        if "disable_dynamic_tick_latency" in keys and "restore_dynamic_tick_default" in keys:
            skip.update({"disable_dynamic_tick_latency", "restore_dynamic_tick_default"})
            self.log(self.tr("dynamic_tick_conflict_skipped"))
        if "cpu_latency_power_profile" in keys and "restore_balanced_power_profile" in keys:
            skip.update({"cpu_latency_power_profile", "restore_balanced_power_profile"})
            self.log(self.tr("power_profile_conflict_skipped"))
        if "cpu_latency_power_profile" in keys:
            redundant = {"safe_gaming_power_profile", "high_perf_plan"} & keys
            if redundant:
                skip.update(redundant)
                self.log(self.tr("cpu_latency_redundant_skipped"))
        if "safe_gaming_power_profile" in keys and "high_perf_plan" in keys:
            # The safe profile already switches to High Performance, so running
            # the basic task too only duplicates work and log noise.
            skip.add("high_perf_plan")
            self.log(self.tr("high_perf_redundant_skipped"))
        if not skip:
            return chosen
        return [task for task in chosen if task.key not in skip]

    def update_progress(self, removed_bytes: int, force: bool = False):
        """Update cleanup counters without flooding Tk with per-file redraws."""
        with self.total_lock:
            self.cleaned_bytes += max(0, removed_bytes)
            now = time.monotonic()
            bytes_delta = self.cleaned_bytes - self._last_progress_ui_bytes
            should_update = (
                force
                or self._last_progress_ui_at <= 0
                or bytes_delta >= 1024 * 1024
                or (now - self._last_progress_ui_at) >= 0.18
            )
            if not should_update:
                return

            self._last_progress_ui_at = now
            self._last_progress_ui_bytes = self.cleaned_bytes
            mb = self.cleaned_bytes / (1024 ** 2)
            progress = min(self.cleaned_bytes / self.total_size_bytes, 1.0) if self.total_size_bytes > 0 else None
            self._pending_progress = (mb, progress)

        self.schedule_progress_paint()

    def schedule_progress_paint(self) -> None:
        if getattr(self, "_progress_after_id", None):
            return
        try:
            self._progress_after_id = self.after(45, self.paint_progress)
        except Exception:
            self._progress_after_id = None

    def paint_progress(self) -> None:
        self._progress_after_id = None
        pending = getattr(self, "_pending_progress", None)
        if not pending:
            return
        mb, progress = pending
        self._pending_progress = None
        self.lbl_stats.configure(text=self.trf("freed_fmt", mb=mb), text_color=COLORS["success"])
        if progress is not None:
            self.animate_progress_to(progress)

    def animate_progress_to(self, target: float) -> None:
        target = max(0.0, min(1.0, float(target)))
        self._progress_target_value = target
        if getattr(self, "_progress_anim_after_id", None):
            return
        self._animate_progress_step()

    def _animate_progress_step(self) -> None:
        self._progress_anim_after_id = None
        target = max(0.0, min(1.0, float(getattr(self, "_progress_target_value", 0.0))))
        current = max(0.0, min(1.0, float(getattr(self, "_progress_display_value", 0.0))))
        delta = target - current
        if abs(delta) < 0.002:
            current = target
        else:
            current += delta * 0.35
        self._progress_display_value = current
        try:
            self.progress.set(current)
        except Exception:
            return
        if abs(target - current) >= 0.002:
            try:
                self._progress_anim_after_id = self.after(24, self._animate_progress_step)
            except Exception:
                self._progress_anim_after_id = None

    def analyze_directory_tasks(self, dir_tasks: List[CleanerTask]) -> Tuple[int, Dict[str, int], List[Tuple[str, int]]]:
        total = 0
        category_totals: Dict[str, int] = {key: 0 for key in ("system", "browsers", "deep", "gamer", "ultimate")}
        detail_rows: List[Tuple[str, int]] = []
        pending_tasks = [task for task in dir_tasks if self._task_paths(task)]
        if not pending_tasks:
            return 0, category_totals, detail_rows

        while pending_tasks and not self.cancel_event.is_set():
            workers = get_adaptive_workers("scan", len(pending_tasks))
            self.log(self.trf("analyzing_targets_fmt", count=len(pending_tasks), workers=workers))
            self.log(self.trf("adaptive_threads_fmt", status=get_adaptive_thread_status("scan")))
            batch = pending_tasks[:workers]
            pending_tasks = pending_tasks[workers:]

            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                future_map = {pool.submit(SafeFS.fast_size_many, self._task_paths(task), self.cancel_event): task for task in batch}
                for future in concurrent.futures.as_completed(future_map):
                    task = future_map[future]
                    if self.cancel_event.is_set():
                        break
                    try:
                        size = future.result()
                    except Exception:
                        size = 0
                    total += size
                    category_totals[task.category] = category_totals.get(task.category, 0) + size
                    detail_rows.append((self.task_title(task), size))
                    self.log(self.trf("analysis_item_fmt", title=self.task_title(task), mb=size / (1024 ** 2)))

        detail_rows.sort(key=lambda item: item[1], reverse=True)
        return total, category_totals, detail_rows

    def log_category_breakdown(self, category_totals: Dict[str, int], top_items: List[Tuple[str, int]], command_count: int):
        self.log(self.tr("analysis_summary_header"))
        for cat_key in ("system", "browsers", "deep", "gamer", "ultimate"):
            size = category_totals.get(cat_key, 0)
            if size > 0:
                label = self.category_label(cat_key)
                self.log(f"{label:<14}: {size / (1024 ** 2):8.2f} MB")
        if command_count:
            self.log(self.trf("queued_actions_fmt", count=command_count))
        if top_items:
            self.log(self.tr("top_consumers"))
            for title, size in top_items[:5]:
                self.log(f" • {title}: {size / (1024 ** 2):.2f} MB")

    def refresh_analysis_label(self, total: int, category_totals: Dict[str, int]):
        best_cat = None
        best_size = 0
        for cat_key, size in category_totals.items():
            if size > best_size:
                best_cat = cat_key
                best_size = size
        if total <= 0:
            text = self.tr("no_noticeable_junk")
            color = COLORS["warning"]
        else:
            label = self.category_label(best_cat) if best_cat else self.tr("mixed")
            text = self.trf("found_biggest_fmt", total_mb=total / (1024 ** 2), label=label, best_mb=best_size / (1024 ** 2))
            color = COLORS["white"]
        def ui_update():
            self.lbl_analysis.configure(text=text, text_color=color)
            self.card_estimate.set(f"{total / (1024 ** 2):.1f} MB" if total > 0 else "0 MB", COLORS["system"] if total > 0 else COLORS["muted"])
        self.after(0, ui_update)

    def clean_targets(self, dir_tasks: List[CleanerTask]):
        pending_tasks = [task for task in dir_tasks if self._task_paths(task)]
        if not pending_tasks:
            return

        cleanup_totals = {
            "removed_bytes": 0,
            "files_removed": 0,
            "dirs_removed": 0,
            "scheduled_reboot": 0,
            "skipped_links": 0,
            "errors": 0,
        }

        while pending_tasks and not self.cancel_event.is_set():
            workers = get_adaptive_workers("clean", len(pending_tasks))
            self.log(self.trf("cleaning_targets_fmt", count=len(pending_tasks), workers=workers))
            self.log(self.trf("adaptive_threads_fmt", status=get_adaptive_thread_status("clean")))
            batch = pending_tasks[:workers]
            pending_tasks = pending_tasks[workers:]

            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                future_map = {
                    pool.submit(SafeFS.clean_many, self._task_paths(task), self.update_progress, self.cancel_event): task
                    for task in batch
                }
                for future in concurrent.futures.as_completed(future_map):
                    task = future_map[future]
                    if self.cancel_event.is_set():
                        break
                    try:
                        result = future.result()
                        self.update_progress(0, force=True)
                    except Exception:
                        self.log(self.trf("cleanup_target_failed_fmt", title=self.task_title(task)))
                        continue

                    removed_mb = float(result.get("removed_bytes", 0)) / (1024 ** 2)
                    files_removed = int(result.get("files_removed", 0))
                    dirs_removed = int(result.get("dirs_removed", 0))
                    scheduled_reboot = int(result.get("scheduled_reboot", 0))
                    remaining_files = int(result.get("remaining_files", 0))
                    remaining_dirs = int(result.get("remaining_dirs", 0))
                    skipped_links = int(result.get("skipped_links", 0))
                    errors = int(result.get("errors", 0))

                    cleanup_totals["removed_bytes"] += int(result.get("removed_bytes", 0) or 0)
                    cleanup_totals["files_removed"] += files_removed
                    cleanup_totals["dirs_removed"] += dirs_removed
                    cleanup_totals["scheduled_reboot"] += scheduled_reboot
                    cleanup_totals["skipped_links"] += skipped_links
                    cleanup_totals["errors"] += errors

                    if errors > 0:
                        self.log(self.trf(
                            "cleanup_target_partial_fmt",
                            title=self.task_title(task),
                            mb=removed_mb,
                            files=files_removed,
                            dirs=dirs_removed,
                            errors=errors,
                        ))
                    else:
                        self.log(self.trf(
                            "cleanup_target_ok_fmt",
                            title=self.task_title(task),
                            mb=removed_mb,
                            files=files_removed,
                            dirs=dirs_removed,
                        ))

                    if scheduled_reboot > 0:
                        self.log(self.trf("cleanup_reboot_scheduled_fmt", title=self.task_title(task), count=scheduled_reboot))
                    if skipped_links > 0:
                        self.log(self.trf("cleanup_skipped_links_fmt", title=self.task_title(task), count=skipped_links))
                    if (remaining_files + remaining_dirs) > skipped_links:
                        self.log(self.trf("cleanup_remaining_fmt", title=self.task_title(task), files=remaining_files, dirs=remaining_dirs))

        if any(int(value or 0) for value in cleanup_totals.values()):
            self.log(self.trf(
                "cleanup_summary_fmt",
                mb=float(cleanup_totals["removed_bytes"]) / (1024 ** 2),
                files=int(cleanup_totals["files_removed"]),
                dirs=int(cleanup_totals["dirs_removed"]),
                scheduled=int(cleanup_totals["scheduled_reboot"]),
                skipped=int(cleanup_totals["skipped_links"]),
                errors=int(cleanup_totals["errors"]),
            ))

    def perform_pre_analysis(self, chosen: List[CleanerTask]) -> Tuple[List[CleanerTask], List[CleanerTask]]:
        dir_tasks = [task for task in chosen if task.kind == "directory" and self._task_paths(task)]
        cmd_tasks = [task for task in chosen if task.kind == "command" and task.command]
        total, category_totals, top_items = self.analyze_directory_tasks(dir_tasks)
        self.analysis_total_bytes = total
        self.last_analysis = category_totals
        self.total_size_bytes = total
        self.log_category_breakdown(category_totals, top_items, len(cmd_tasks))
        self.refresh_analysis_label(total, category_totals)
        self.log(self.trf("analysis_done_estimate_fmt", mb=total / (1024 ** 2)))
        self.after(0, lambda: self.progress.stop())
        self.after(0, lambda: self.progress.set(0))
        return dir_tasks, cmd_tasks

    def prepare_service_deps(self, dir_tasks: List[CleanerTask], start: bool):
        needs_update = any(task.key == "update_cache_files" for task in dir_tasks)
        needs_delivery = any(task.key.startswith("delivery_opt") for task in dir_tasks)
        if not needs_update and not needs_delivery:
            return

        if start:
            self.log(self.tr("stop_update_services"))
            if needs_update:
                WindowsOps.run_command_args(["net.exe", "stop", "wuauserv"], timeout=60)
                WindowsOps.run_command_args(["net.exe", "stop", "bits"], timeout=60)
                WindowsOps.run_command_args(["net.exe", "stop", "cryptsvc"], timeout=60)
            if needs_delivery:
                WindowsOps.run_command_args(["net.exe", "stop", "dosvc"], timeout=60)
        else:
            self.log(self.tr("start_update_services"))
            if needs_update:
                WindowsOps.run_command_args(["net.exe", "start", "cryptsvc"], timeout=60)
                WindowsOps.run_command_args(["net.exe", "start", "wuauserv"], timeout=60)
                WindowsOps.run_command_args(["net.exe", "start", "bits"], timeout=60)
            if needs_delivery:
                WindowsOps.run_command_args(["net.exe", "start", "dosvc"], timeout=60)

    def analysis_only_engine(self):
        try:
            chosen = self.selected_tasks()
            if not chosen:
                self.log(self.tr("nothing_selected"))
                self.after(0, lambda: self.lbl_analysis.configure(text=self.tr("pick_one_module"), text_color=COLORS["warning"]))
                return
            self.perform_pre_analysis(chosen)
            if not self.cancel_event.is_set():
                self.log(self.tr("analysis_done_no_delete"))
        finally:
            self.after(0, lambda: self.set_running_state(False))

    def engine(self):
        try:
            chosen = self.selected_tasks()
            if not chosen:
                self.log(self.tr("nothing_selected"))
                self.after(0, lambda: self.lbl_analysis.configure(text=self.tr("pick_one_module"), text_color=COLORS["warning"]))
                return
            dir_tasks, cmd_tasks = self.perform_pre_analysis(chosen)
            if self.cancel_event.is_set():
                self.log(self.tr("cancelled_before_clean"))
                return
            if not self.backup_registry_for_tasks(cmd_tasks):
                return
            self.prepare_service_deps(dir_tasks, start=True)
            try:
                self.clean_targets(dir_tasks)
            finally:
                self.prepare_service_deps(dir_tasks, start=False)
            if not self.cancel_event.is_set():
                for task in cmd_tasks:
                    if self.cancel_event.is_set():
                        break
                    self.log(self.trf("action_fmt", title=self.task_title(task)))
                    try:
                        task.command()
                        if task.reboot_required:
                            self.log(self.tr("reboot_recommended"))
                    except Exception:
                        self.log(self.trf("action_error_fmt", title=self.task_title(task)))
            if self.cancel_event.is_set():
                self.log(self.tr("user_stopped"))
            else:
                self.after(0, lambda: self.animate_progress_to(1))
                self.log(self.tr("done_clean_sequence"))
        finally:
            self.after(0, lambda: self.set_running_state(False))


    # ----------------------------
    # About (in-app)
    # ----------------------------

    def _read_local_doc(self, filename: str) -> tuple[str | None, str | None]:
        for base_dir in (get_runtime_base_dir(), get_bundle_base_dir()):
            path = os.path.join(base_dir, filename)
            try:
                if os.path.isfile(path):
                    with open(path, "r", encoding="utf-8") as f:
                        return path, f.read()
            except Exception:
                continue
        return None, None

    def _apply_icon_to_toplevel(self, win: ctk.CTkToplevel) -> None:
        """Apply app icon to a toplevel window (title bar + taskbar)."""
        self._apply_icon_to_window(win, default=False)
        try:
            win.after(80, lambda current=win: self._apply_icon_to_window(current, default=False))
        except Exception:
            pass

    def _open_text_viewer(self, title: str, text: str) -> None:
        win = ctk.CTkToplevel(self)
        win.title(title)
        self._apply_icon_to_toplevel(win)
        self.configure_toplevel_geometry(win, preferred=(780, 660), minimum=(560, 420))
        win.configure(fg_color=COLORS["bg_main"])
        try:
            win.transient(self)
            win.grab_set()
        except Exception:
            pass

        wrap = ctk.CTkFrame(win, fg_color=COLORS["bg_card"], corner_radius=16, border_width=1, border_color=COLORS["border"])
        wrap.pack(fill="both", expand=True, padx=18, pady=18)

        head = ctk.CTkFrame(wrap, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(14, 10))
        head.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(head, text=title, font=("Segoe UI", 16, "bold"), text_color=COLORS["white"]).grid(row=0, column=0, sticky="w")

        btn_copy = AnimatedButton(head, text=self.tr("about_copy"), height=34, width=120, fg_color=COLORS["bg_soft"], hover_color="#1F2937", text_color=COLORS["white"])
        btn_copy.grid(row=0, column=2, sticky="e")

        txt = tk.Text(wrap, wrap="word", bg=COLORS["bg_soft"], fg=COLORS["white"], insertbackground=COLORS["white"])
        txt.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        txt.insert("1.0", text or "")
        txt.configure(state="disabled")

        def do_copy():
            try:
                win.clipboard_clear()
                win.clipboard_append(text or "")
                win.update()
                self.log(self.tr("about_copied"))
            except Exception:
                pass

        btn_copy.configure(command=do_copy)

        AnimatedButton(wrap, text=self.tr("about_close"), height=40, fg_color=COLORS["gamer"], hover_color="#059669", command=win.destroy).pack(fill="x", padx=16, pady=(0, 16))

    def open_doc_in_app(self, filename: str, title_key: str) -> None:
        path, text = self._read_local_doc(filename)
        if not path or text is None:
            self.log(self.trf("about_doc_missing", name=filename))
            return
        self._open_text_viewer(self.tr(title_key), text)

    def open_about_dialog(self) -> None:
        try:
            if getattr(self, "_about_win", None) and self._about_win.winfo_exists():  # type: ignore[attr-defined]
                self._about_win.focus()  # type: ignore[attr-defined]
                return
        except Exception:
            pass

        win = ctk.CTkToplevel(self)
        self._about_win = win  # type: ignore[attr-defined]
        win.title(self.tr("about_title"))
        self.configure_toplevel_geometry(win, preferred=(640, 660), minimum=(540, 560))
        win.configure(fg_color=COLORS["bg_main"])
        try:
            win.transient(self)
            win.grab_set()
        except Exception:
            pass

        self._apply_icon_to_toplevel(win)

        wrap = ctk.CTkFrame(win, fg_color=COLORS["bg_card"], corner_radius=18, border_width=1, border_color=COLORS["border"])
        wrap.pack(fill="both", expand=True, padx=18, pady=18)

        head = ctk.CTkFrame(wrap, fg_color="transparent")
        head.pack(fill="x", padx=18, pady=(18, 8))
        head.grid_columnconfigure(1, weight=1)

        icon_rendered = False
        try:
            icon_img = self._about_header_icon_cache
            if icon_img is None:
                from PIL import Image  # type: ignore
                png = find_icon_path("app.png")
                if png and os.path.isfile(png):
                    with Image.open(png) as src:
                        img = src.convert("RGBA")
                    icon_img = ctk.CTkImage(light_image=img, dark_image=img, size=(44, 44))
                    self._about_header_icon_cache = icon_img
            if icon_img is not None:
                ctk.CTkLabel(head, text="", image=icon_img).grid(row=0, column=0, rowspan=2, sticky="w")
                win._about_icon_ref = icon_img  # type: ignore[attr-defined]
                icon_rendered = True
        except Exception:
            icon_rendered = False

        if not icon_rendered:
            ctk.CTkLabel(head, text="FC", font=("Segoe UI Black", 18), text_color=COLORS["white"]).grid(row=0, column=0, rowspan=2, sticky="w")

        ctk.CTkLabel(head, text=self.tr("about_title"), font=("Segoe UI Black", 20), text_color=COLORS["white"]).grid(row=0, column=1, sticky="w", padx=(12, 0))
        ctk.CTkLabel(head, text=f"{self.tr('app_brand')} • {self.tr('about_version')}: {APP_VERSION}", font=("Segoe UI", 12, "bold"), text_color=COLORS["text_gray"]).grid(row=1, column=1, sticky="w", padx=(12, 0), pady=(2, 0))

        ctk.CTkLabel(wrap, text=self.tr("about_desc"), font=("Segoe UI", 12), text_color=COLORS["muted"], justify="left", wraplength=560).pack(anchor="w", padx=18, pady=(10, 0))

        hint = ctk.CTkFrame(wrap, fg_color=COLORS["bg_soft"], corner_radius=14, border_width=1, border_color=COLORS["border"])
        hint.pack(fill="x", padx=18, pady=(16, 10))
        ctk.CTkLabel(hint, text=self.tr("about_hint_title"), font=("Segoe UI", 12, "bold"), text_color=COLORS["white"]).pack(anchor="w", padx=14, pady=(12, 4))
        ctk.CTkLabel(hint, text=self.tr("about_hint_body"), font=("Segoe UI", 11), text_color=COLORS["text_gray"], justify="left", wraplength=540).pack(anchor="w", padx=14, pady=(0, 12))

        sep = ctk.CTkFrame(wrap, fg_color=COLORS["border"], height=1)
        sep.pack(fill="x", padx=18, pady=(10, 14))

        docs = ctk.CTkFrame(wrap, fg_color="transparent")
        docs.pack(fill="x", padx=18, pady=(0, 10))
        ctk.CTkLabel(docs, text=self.tr("about_links"), font=("Segoe UI", 13, "bold"), text_color=COLORS["text_gray"]).pack(anchor="w", pady=(0, 10))

        def doc_row(text_key: str, subtitle_key: str, filename: str, title_key: str):
            row = ctk.CTkFrame(docs, fg_color=COLORS["bg_soft"], corner_radius=14, border_width=1, border_color=COLORS["border"])
            row.pack(fill="x", pady=(0, 10))
            left = ctk.CTkFrame(row, fg_color="transparent")
            left.pack(side="left", fill="both", expand=True, padx=14, pady=12)
            ctk.CTkLabel(left, text=self.tr(text_key), font=("Segoe UI", 13, "bold"), text_color=COLORS["white"]).pack(anchor="w")
            ctk.CTkLabel(left, text=self.tr(subtitle_key), font=("Segoe UI", 11), text_color=COLORS["text_gray"], wraplength=420, justify="left").pack(anchor="w", pady=(3, 0))
            AnimatedButton(row, text=self.tr("about_open"), height=36, width=120, fg_color=COLORS["gamer"], hover_color="#059669", command=lambda: self.open_doc_in_app(filename, title_key)).pack(side="right", padx=12, pady=12)

        doc_row("about_license", "about_license_sub", "LICENSE", "about_license")
        doc_row("about_privacy", "about_privacy_sub", "PRIVACY_POLICY.txt", "about_privacy")

        action_row = ctk.CTkFrame(wrap, fg_color="transparent")
        action_row.pack(fill="x", padx=18, pady=(8, 18))
        self.btn_check_updates = AnimatedButton(action_row, text=self.tr("check_updates"), height=42, fg_color=COLORS["gamer"], hover_color="#059669", text_color=COLORS["white"], command=lambda: self.check_for_updates(silent_if_latest=False, source="about"))
        self.btn_check_updates.pack(side="left", fill="x", expand=True)
        AnimatedButton(action_row, text=self.tr("about_close"), height=42, fg_color=COLORS["bg_soft"], hover_color="#1F2937", text_color=COLORS["white"], command=win.destroy).pack(side="left", fill="x", expand=True, padx=(10, 0))


    def _set_update_check_busy(self, busy: bool) -> None:
        self._update_check_in_progress = bool(busy)
        try:
            if getattr(self, "_about_win", None) and self._about_win.winfo_exists() and hasattr(self, "btn_check_updates"):
                self.btn_check_updates.configure(
                    state="disabled" if busy else "normal",
                    text=self.tr("checking_updates") if busy else self.tr("check_updates"),
                )
        except Exception:
            pass

    def _format_release_notes_for_log(self, body: str, limit: int = 8) -> List[str]:
        lines: List[str] = []
        for raw in (body or "").splitlines():
            clean = re.sub(r"\s+", " ", raw).strip()
            if not clean:
                continue
            if clean.startswith("#"):
                clean = clean.lstrip("#").strip()
            lines.append(clean)
            if len(lines) >= limit:
                break
        return lines

    def check_for_updates(self, *, silent_if_latest: bool = False, source: str = "manual") -> None:
        if self._update_check_in_progress:
            if source != "startup":
                self.log(self.tr("update_check_running"))
            return

        self._set_update_check_busy(True)
        if source != "startup":
            self.log(self.tr("checking_updates"))

        def worker() -> None:
            info = fetch_latest_github_release("CraftRom", "FreeCleaner")
            self.after(0, lambda: self._handle_update_check_result(info, silent_if_latest=silent_if_latest, source=source))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_update_check_result(self, info: Optional[UpdateInfo], *, silent_if_latest: bool, source: str) -> None:
        self._set_update_check_busy(False)
        if info is None:
            if source != "startup":
                self.log(self.tr("update_check_failed"))
                self._open_text_viewer(self.tr("update_dialog_title"), self.tr("update_check_failed"))
            return

        self._last_update_info = info
        current_raw = APP_VERSION_RAW
        cmp = compare_versions(info.version_text, current_raw)

        if cmp > 0 and (source != "startup" or info.tag_name != self._ignored_update_tag):
            self.log(self.trf("update_available_log", current=self._format_version_label(current_raw), latest=self._format_version_label(info.version_text)))
            for line in self._format_release_notes_for_log(info.body):
                self.log(f"• {line}")
            parent = getattr(self, "_about_win", None) if source == "about" else self
            self.open_update_dialog(info, startup=(source == "startup"), parent=parent)
            return

        if source != "startup" or not silent_if_latest:
            self.log(self.trf("update_up_to_date_log", version=self._format_version_label(current_raw)))
            if source != "startup":
                self._open_text_viewer(self.tr("update_dialog_title"), self.trf("update_up_to_date_body", version=self._format_version_label(current_raw)))

    def _format_version_label(self, raw: str) -> str:
        label = (raw or "").strip()
        if not label:
            return "v0.0.0"
        if not label.lower().startswith("v"):
            label = f"v{label}"
        return label

    def _format_release_notes(self, body: str) -> str:
        notes = (body or "").strip()
        if not notes:
            return self.tr("update_no_changelog")
        return notes

    def _human_size(self, value: float) -> str:
        try:
            num = float(value)
        except Exception:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB"]
        idx = 0
        while num >= 1024 and idx < len(units) - 1:
            num /= 1024.0
            idx += 1
        if idx == 0:
            return f"{int(num)} {units[idx]}"
        return f"{num:.1f} {units[idx]}"

    def _configure_markdown_tags(self, text: tk.Text) -> None:
        try:
            text.tag_configure("md_p", spacing1=0, spacing3=7, lmargin1=2, lmargin2=2)
            text.tag_configure("md_h1", font=("Segoe UI Black", 16), foreground=COLORS["white"], spacing1=8, spacing3=7)
            text.tag_configure("md_h2", font=("Segoe UI Black", 14), foreground=COLORS["white"], spacing1=7, spacing3=6)
            text.tag_configure("md_h3", font=("Segoe UI", 13, "bold"), foreground=COLORS["white"], spacing1=6, spacing3=5)
            text.tag_configure("md_h4", font=("Segoe UI", 12, "bold"), foreground=COLORS["white"], spacing1=4, spacing3=4)
            text.tag_configure("md_h5", font=("Segoe UI", 11, "bold"), foreground=COLORS["white"], spacing1=4, spacing3=4)
            text.tag_configure("md_h6", font=("Segoe UI", 10, "bold"), foreground=COLORS["text_gray"], spacing1=4, spacing3=4)
            text.tag_configure("md_bold", font=("Segoe UI", 10, "bold"))
            text.tag_configure("md_italic", font=("Segoe UI", 10, "italic"))
            text.tag_configure("md_code", font=("Consolas", 9), background="#101722", foreground="#A7F3D0")
            text.tag_configure("md_codeblock", font=("Consolas", 9), background="#0B1020", foreground="#D1FAE5", lmargin1=12, lmargin2=12, spacing1=5, spacing3=7)
            text.tag_configure("md_quote", foreground=COLORS["text_gray"], lmargin1=18, lmargin2=18, spacing1=2, spacing3=5)
            text.tag_configure("md_bullet", lmargin1=16, lmargin2=34, spacing1=2, spacing3=2)
            text.tag_configure("md_num", lmargin1=16, lmargin2=34, spacing1=2, spacing3=2)
            text.tag_configure("md_hr", foreground=COLORS["border"], spacing1=6, spacing3=6)
            text.tag_configure("md_link", foreground="#60A5FA", underline=True)
        except Exception:
            pass

    def _insert_markdown_inline(self, text: tk.Text, value: str, base_tags: Tuple[str, ...] = ()) -> None:
        pattern = re.compile(r'(\[([^\]]+)\]\(([^)]+)\)|`([^`]+)`|\*\*([^*]+)\*\*|__([^_]+)__|\*([^*]+)\*|_([^_]+)_|~~([^~]+)~~)')
        pos = 0
        for match in pattern.finditer(value or ""):
            if match.start() > pos:
                text.insert("end", value[pos:match.start()], base_tags or ("md_p",))
            token = match.group(0)
            if match.group(2) is not None and match.group(3) is not None:
                label = match.group(2)
                url = match.group(3).strip()
                tag_name = f"md_link_{text.index('end-1c').replace('.', '_')}_{abs(hash((label, url))) % 100000}"
                text.insert("end", label, tuple(base_tags) + ("md_link", tag_name))
                def _open(_event=None, target=url):
                    try:
                        WindowsOps.open_url(target)
                    except Exception:
                        pass
                    return "break"
                text.tag_bind(tag_name, "<Button-1>", _open)
                text.tag_bind(tag_name, "<Enter>", lambda _e: text.configure(cursor="hand2"))
                text.tag_bind(tag_name, "<Leave>", lambda _e: text.configure(cursor="arrow"))
            elif match.group(4) is not None:
                text.insert("end", match.group(4), tuple(base_tags) + ("md_code",))
            elif match.group(5) is not None or match.group(6) is not None:
                text.insert("end", match.group(5) or match.group(6) or token, tuple(base_tags) + ("md_bold",))
            elif match.group(7) is not None or match.group(8) is not None:
                text.insert("end", match.group(7) or match.group(8) or token, tuple(base_tags) + ("md_italic",))
            elif match.group(9) is not None:
                text.insert("end", match.group(9), base_tags or ("md_p",))
            pos = match.end()
        if pos < len(value or ""):
            text.insert("end", value[pos:], base_tags or ("md_p",))

    def _render_markdown(self, text: tk.Text, body: str) -> None:
        text.configure(state="normal")
        text.delete("1.0", "end")
        self._configure_markdown_tags(text)
        source = (body or "").strip() or self.tr("update_no_changelog")
        in_code = False
        ordered_index = 1
        for raw in source.splitlines():
            line = raw.rstrip("\n")
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code = not in_code
                if not in_code:
                    text.insert("end", "\n")
                continue
            if in_code:
                text.insert("end", line + "\n", ("md_codeblock",))
                continue
            if not stripped:
                text.insert("end", "\n")
                ordered_index = 1
                continue
            if re.match(r'^([-*_])\1{2,}$', stripped):
                text.insert("end", "─" * 72 + "\n", ("md_hr",))
                ordered_index = 1
                continue
            m = re.match(r'^(#{1,6})\s+(.*)$', stripped)
            if m:
                self._insert_markdown_inline(text, m.group(2), (f"md_h{min(len(m.group(1)), 6)}",))
                text.insert("end", "\n\n")
                ordered_index = 1
                continue
            m = re.match(r'^>\s?(.*)$', stripped)
            if m:
                text.insert("end", "▌ ", ("md_quote",))
                self._insert_markdown_inline(text, m.group(1), ("md_quote",))
                text.insert("end", "\n")
                continue
            m = re.match(r'^[-*+]\s+(.*)$', stripped)
            if m:
                text.insert("end", "• ", ("md_bullet",))
                self._insert_markdown_inline(text, m.group(1), ("md_bullet",))
                text.insert("end", "\n")
                ordered_index = 1
                continue
            m = re.match(r'^(\d+)[.)]\s+(.*)$', stripped)
            if m:
                prefix = f"{m.group(1)}. "
                text.insert("end", prefix, ("md_num",))
                self._insert_markdown_inline(text, m.group(2), ("md_num",))
                text.insert("end", "\n")
                ordered_index = int(m.group(1)) + 1
                continue
            self._insert_markdown_inline(text, stripped, ("md_p",))
            text.insert("end", "\n")
        text.configure(state="disabled")

    def cleanup_stale_update_files(self, *, silent: bool = True) -> None:
        try:
            removed = cleanup_old_update_files()
            if removed and not silent:
                self.log(self.trf("update_cleanup_removed", count=removed))
        except Exception as exc:
            if not silent:
                self.log(str(exc))


    def download_update(self, info: UpdateInfo, *, parent=None, progress_bar=None, status_label=None, action_button=None, later_button=None, done_callback=None) -> None:
        if self._update_download_in_progress:
            self.log(self.tr("update_download_busy"))
            return

        parent_win = parent or getattr(self, "_update_win", None) or self
        download_url = info.download_url or info.html_url
        default_name = guess_download_filename(download_url, info.asset_name or f"FreeCleaner-{info.version_text}-setup.exe")
        if info.asset_name:
            default_name = info.asset_name
        save_path = get_update_download_path(default_name, fallback=f"FreeCleaner-{info.version_text}-setup.exe")
        update_dir = get_updates_dir(create=True)

        try:
            removed = cleanup_old_update_files()
            if removed:
                self.log(self.trf("update_cleanup_removed", count=removed))
        except Exception:
            pass

        self._update_download_in_progress = True
        cancel_event = threading.Event()
        self._update_download_cancel = cancel_event

        if action_button is not None:
            try:
                action_button.configure(state="disabled", text=self.tr("update_downloading"))
            except Exception:
                pass
        if later_button is not None:
            try:
                later_button.configure(state="disabled")
            except Exception:
                pass
        if progress_bar is not None:
            try:
                progress_bar.set(0)
            except Exception:
                pass
        if status_label is not None:
            try:
                status_label.configure(text=self.trf("update_download_location", path=update_dir))
            except Exception:
                pass

        self.log(self.trf("update_download_started", version=self._format_version_label(info.version_text)))
        self.log(self.trf("update_download_location", path=update_dir))
        start_time = datetime.now().timestamp()
        last_progress_at = {"value": 0.0}

        def progress(downloaded: int, total: Optional[int]) -> None:
            now = datetime.now().timestamp()
            if now - last_progress_at["value"] < 0.12 and not (total and downloaded >= total):
                return
            last_progress_at["value"] = now

            elapsed = max(now - start_time, 0.001)
            speed = downloaded / elapsed
            percent = 0.0
            progress_text = f"{self._human_size(downloaded)} • {self._human_size(speed)}/s"
            if total and total > 0:
                percent = min(downloaded / total, 1.0)
                progress_text = f"{percent * 100:.0f}% • {self._human_size(downloaded)} / {self._human_size(total)} • {self._human_size(speed)}/s"

            def apply() -> None:
                if progress_bar is not None:
                    try:
                        progress_bar.set(percent if total and total > 0 else 0)
                    except Exception:
                        pass
                if status_label is not None:
                    try:
                        status_label.configure(text=self.trf("update_download_progress", progress=progress_text))
                    except Exception:
                        pass
            self.after(0, apply)

        def set_buttons_idle() -> None:
            if action_button is not None:
                try:
                    action_button.configure(state="normal", text=self.tr("update_download"))
                except Exception:
                    pass
            if later_button is not None:
                try:
                    later_button.configure(state="normal")
                except Exception:
                    pass

        def finish(success: bool, result: str) -> None:
            self._update_download_in_progress = False
            self._update_download_cancel = None

            if not success:
                set_buttons_idle()
                self.log(self.trf("update_download_failed_reason", reason=result))
                if status_label is not None:
                    try:
                        status_label.configure(text=self.trf("update_download_failed_reason", reason=result))
                    except Exception:
                        pass
                try:
                    messagebox.showerror(self.tr("update_dialog_title"), self.trf("update_download_failed_reason", reason=result), parent=parent_win)
                except Exception:
                    pass
                return

            self.log(self.trf("update_download_saved", path=result))
            if progress_bar is not None:
                try:
                    progress_bar.set(1)
                except Exception:
                    pass
            if status_label is not None:
                try:
                    status_label.configure(text=self.trf("update_install_starting", path=result))
                except Exception:
                    pass

            if not is_installable_update_file(result):
                set_buttons_idle()
                try:
                    launch_update_installer(result)
                except Exception:
                    pass
                if status_label is not None:
                    try:
                        status_label.configure(text=self.trf("update_download_complete", path=result))
                    except Exception:
                        pass
                try:
                    messagebox.showinfo(self.tr("update_dialog_title"), self.trf("update_download_complete", path=result), parent=parent_win)
                except Exception:
                    pass
                if callable(done_callback):
                    try:
                        done_callback(result)
                    except Exception:
                        pass
                return

            ok, message, installer_pid = launch_update_installer(result)
            if not ok:
                set_buttons_idle()
                self.log(self.trf("update_install_failed_reason", reason=message))
                if status_label is not None:
                    try:
                        status_label.configure(text=self.trf("update_install_failed_reason", reason=message))
                    except Exception:
                        pass
                try:
                    messagebox.showerror(self.tr("update_dialog_title"), self.trf("update_install_failed_reason", reason=message), parent=parent_win)
                except Exception:
                    pass
                return

            cleanup_scheduled = schedule_update_cleanup_after_install(installer_pid, update_dir)
            self.log(self.trf("update_install_started", path=result))
            if cleanup_scheduled:
                self.log(self.tr("update_install_cleanup_scheduled"))
            if status_label is not None:
                try:
                    status_label.configure(text=self.tr("update_install_closing_app"))
                except Exception:
                    pass
            if action_button is not None:
                try:
                    action_button.configure(state="disabled", text=self.tr("update_install_started_button"))
                except Exception:
                    pass

            if callable(done_callback):
                try:
                    done_callback(result)
                except Exception:
                    pass

            try:
                if parent_win is not self and getattr(parent_win, "winfo_exists", lambda: False)():
                    parent_win.grab_release()
            except Exception:
                pass
            self.after(1800, self.destroy)

        def worker() -> None:
            ok, result = download_url_to_file(download_url, save_path, progress_cb=progress, cancel_event=cancel_event)
            self.after(0, lambda: finish(ok, result))

        threading.Thread(target=worker, daemon=True).start()

    def open_update_dialog(self, info: UpdateInfo, *, startup: bool = False, parent=None) -> None:
        try:
            if getattr(self, "_update_win", None) and self._update_win.winfo_exists():  # type: ignore[attr-defined]
                self._update_win.deiconify()  # type: ignore[attr-defined]
                self._update_win.lift()  # type: ignore[attr-defined]
                self._update_win.focus_force()  # type: ignore[attr-defined]
                return
        except Exception:
            pass

        owner = parent if parent is not None and getattr(parent, "winfo_exists", lambda: False)() else self

        try:
            if owner is not self and getattr(owner, "grab_current", None) and owner.grab_current() == owner:
                owner.grab_release()
        except Exception:
            pass

        win = ctk.CTkToplevel(owner)
        self._update_win = win  # type: ignore[attr-defined]
        win.title(self.tr("update_dialog_title"))
        self.configure_toplevel_geometry(win, preferred=(900, 760), minimum=(720, 620))
        win.configure(fg_color=COLORS["bg_main"])
        try:
            win.transient(owner)
            win.lift()
            win.attributes("-topmost", True)
            win.after(250, lambda: win.attributes("-topmost", False))
            win.grab_set()
        except Exception:
            pass
        self._apply_icon_to_toplevel(win)

        wrap = ctk.CTkFrame(
            win,
            fg_color=COLORS["bg_card"],
            corner_radius=22,
            border_width=1,
            border_color=mix_colors(COLORS["border"], COLORS["bg_card"], 0.45),
        )
        wrap.pack(fill="both", expand=True, padx=14, pady=14)
        wrap.grid_columnconfigure(0, weight=1)
        wrap.grid_rowconfigure(3, weight=1)

        screen_w = max(720, int(self.winfo_screenwidth() or 900))
        usable_wrap = max(420, min(760, screen_w - 220))
        wraplength = usable_wrap - 70

        hero = ctk.CTkFrame(
            wrap,
            fg_color=mix_colors(COLORS["gamer"], COLORS["bg_card"], 0.14),
            corner_radius=20,
            border_width=1,
            border_color=mix_colors(COLORS["gamer"], COLORS["border"], 0.50),
        )
        hero.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 10))
        head = ctk.CTkFrame(hero, fg_color="transparent")
        head.pack(fill="x", padx=16, pady=(14, 12))
        ctk.CTkLabel(head, text=self.tr("update_dialog_title"), font=("Segoe UI Black", 20), text_color=COLORS["white"]).pack(anchor="w")
        ctk.CTkLabel(
            head,
            text=self.trf(
                "update_available_body",
                current=self._format_version_label(APP_VERSION_RAW),
                latest=self._format_version_label(info.version_text),
            ),
            font=("Segoe UI", 11),
            text_color=COLORS["text_gray"],
            justify="left",
            wraplength=wraplength,
        ).pack(anchor="w", pady=(4, 0))

        meta = ctk.CTkFrame(wrap, fg_color=COLORS["bg_soft"], corner_radius=16, border_width=1, border_color=COLORS["border"])
        meta.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 10))
        ctk.CTkLabel(
            meta,
            text=f"{self.tr('about_version')}: {self._format_version_label(APP_VERSION_RAW)} → {self._format_version_label(info.version_text)}",
            font=("Segoe UI", 11, "bold"),
            text_color=COLORS["white"],
        ).pack(anchor="w", padx=14, pady=(11, 3))
        if info.published_at:
            ctk.CTkLabel(
                meta,
                text=self.trf("update_published_at", date=info.published_at.replace('T', ' ').replace('Z', ' UTC')),
                font=("Segoe UI", 9),
                text_color=COLORS["text_gray"],
            ).pack(anchor="w", padx=14, pady=(0, 3))
        ctk.CTkLabel(
            meta,
            text=info.name or info.tag_name,
            font=("Segoe UI", 9),
            text_color=COLORS["muted"],
            wraplength=wraplength,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 11))

        changelog_head = ctk.CTkFrame(wrap, fg_color="transparent")
        changelog_head.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 6))
        ctk.CTkLabel(changelog_head, text=self.tr("update_changelog"), font=("Segoe UI", 12, "bold"), text_color=COLORS["text_gray"]).pack(anchor="w")

        notes_wrap = ctk.CTkFrame(
            wrap,
            fg_color="#070B12",
            corner_radius=16,
            border_width=1,
            border_color=mix_colors(COLORS["border"], "#070B12", 0.35),
            height=280,
        )
        notes_wrap.grid(row=3, column=0, sticky="nsew", padx=14, pady=(0, 10))
        notes_wrap.grid_columnconfigure(0, weight=1)
        notes_wrap.grid_rowconfigure(0, weight=1)
        notes_wrap.grid_propagate(False)

        notes = tk.Text(
            notes_wrap,
            wrap="word",
            bg="#070B12",
            fg=COLORS["white"],
            insertbackground=COLORS["white"],
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=12,
            pady=10,
            font=("Segoe UI", 9),
            cursor="arrow",
            spacing1=0,
            spacing3=0,
        )
        notes.grid(row=0, column=0, sticky="nsew")
        notes_scroll = ctk.CTkScrollbar(notes_wrap, command=notes.yview, width=12)
        notes_scroll.grid(row=0, column=1, sticky="ns", padx=(0, 5), pady=5)
        notes.configure(yscrollcommand=notes_scroll.set)
        self._render_markdown(notes, self._format_release_notes(info.body))

        download_box = ctk.CTkFrame(wrap, fg_color=COLORS["bg_soft"], corner_radius=16, border_width=1, border_color=COLORS["border"])
        download_box.grid(row=4, column=0, sticky="ew", padx=14, pady=(0, 10))
        ctk.CTkLabel(download_box, text=self.tr("update_download_section"), font=("Segoe UI", 11, "bold"), text_color=COLORS["white"]).pack(anchor="w", padx=14, pady=(10, 3))
        download_status = ctk.CTkLabel(
            download_box,
            text=self.tr("update_download_idle"),
            font=("Segoe UI", 9),
            text_color=COLORS["text_gray"],
            justify="left",
            wraplength=wraplength,
        )
        download_status.pack(anchor="w", padx=14, pady=(0, 6))
        progress = ctk.CTkProgressBar(download_box, height=12, corner_radius=999, progress_color=COLORS["gamer"])
        progress.pack(fill="x", padx=14, pady=(0, 10))
        progress.set(0)

        footer = ctk.CTkFrame(
            wrap,
            fg_color=mix_colors(COLORS["bg_soft"], COLORS["bg_card"], 0.35),
            corner_radius=18,
            border_width=1,
            border_color=COLORS["border"],
        )
        footer.grid(row=5, column=0, sticky="ew", padx=14, pady=(0, 14))
        btns = ctk.CTkFrame(footer, fg_color="transparent")
        btns.pack(fill="x", padx=12, pady=12)
        btns.grid_columnconfigure(0, weight=1)
        btns.grid_columnconfigure(1, weight=1)

        def dismiss() -> None:
            if self._update_download_in_progress:
                return
            self._ignored_update_tag = info.tag_name
            try:
                win.grab_release()
            except Exception:
                pass
            win.destroy()
            try:
                self._update_win = None  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                if owner is not self and getattr(owner, "winfo_exists", lambda: False)():
                    owner.lift()
                    owner.focus_force()
                    owner.grab_set()
            except Exception:
                pass

        download_btn = AnimatedButton(
            btns,
            text=self.tr("update_download"),
            height=44,
            corner_radius=14,
            fg_color=COLORS["gamer"],
            hover_color="#059669",
            text_color=COLORS["white"],
            font=("Segoe UI", 12, "bold"),
        )
        download_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        later_btn = AnimatedButton(
            btns,
            text=self.tr("update_later"),
            height=44,
            corner_radius=14,
            fg_color="#111827",
            hover_color="#1F2937",
            border_width=1,
            border_color=COLORS["border"],
            text_color=COLORS["white"],
            font=("Segoe UI", 12, "bold"),
            command=dismiss,
        )
        later_btn.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        def update_wrap_metrics(event=None) -> None:
            try:
                current_w = max(520, int(win.winfo_width() or 0))
                current_h = max(560, int(win.winfo_height() or 0))
            except Exception:
                return
            local_wrap = max(380, current_w - 120)
            notes_h = max(220, min(360, current_h - 420))
            try:
                notes_wrap.configure(height=notes_h)
            except Exception:
                pass
            for lbl in (head.winfo_children()[1],):
                try:
                    lbl.configure(wraplength=local_wrap)
                except Exception:
                    pass
            try:
                download_status.configure(wraplength=local_wrap)
            except Exception:
                pass

        download_btn.configure(
            command=lambda: self.download_update(
                info,
                parent=win,
                progress_bar=progress,
                status_label=download_status,
                action_button=download_btn,
                later_button=later_btn,
            )
        )
        win.bind("<Configure>", update_wrap_metrics, add="+")
        win.after(120, update_wrap_metrics)
        win.protocol("WM_DELETE_WINDOW", dismiss)

    def on_close(self):
        if self.dism_running:
            self.log(self.tr("dism_busy_close_blocked"))
            return
        if self.is_running:
            self.cancel_event.set()
        self.destroy()


if __name__ == "__main__":
    Cleaner().mainloop()
