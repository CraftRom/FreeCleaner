"""Application layer: UI (CustomTkinter) for FreeCleaner.

This module contains UI code only and imports core logic from freecleaner.logic.
"""

from __future__ import annotations

import customtkinter as ctk
import os
import ctypes
import threading
import concurrent.futures
import subprocess
import re
import queue
import json
import locale
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Sequence, Any

try:
    import winreg  # type: ignore
except Exception:  # pragma: no cover
    winreg = None  # type: ignore

from .design import COLORS, SummaryCard, SectionCard, init_ui_theme
from .logic import (
    IS_WINDOWS,
    ICONS_DIRNAME,
    LANG_PACKS,
    LANG_PACK_SOURCES,
    APP_VERSION,
    CONFIG_PATH,
    CleanerTask,
    PathFinder,
    WindowsOps,
    SafeFS,
    SCAN_WORKERS,
    CLEAN_WORKERS,
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
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


    def save_config(self):
        try:
            data = dict(getattr(self, "config", {}) or {})
            data["language"] = getattr(self, "lang_preference", "auto")
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.config = data
        except Exception:
            pass


    def normalize_language_preference(self, value: Optional[str]) -> str:
        code = (value or "auto").strip().lower()
        if code == "auto":
            return "auto"
        return code if code in LANG_PACKS else "auto"


    def __init__(self):
        super().__init__()
        self.config = self.load_config()
        self.lang_preference = self.normalize_language_preference(self.config.get("language", "auto"))
        self.lang = self.detect_initial_language()
        self.title(self.app_title())
        self.configure(fg_color=COLORS["bg_main"])
        self.configure_window_geometry()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._responsive_after_id = None
        self._layout_state: Dict[str, Any] = {}
        self._search_after_id = None
        self._last_search_query = ""
        self._about_header_icon_cache = None
        self.apply_window_icon()

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
        self.log(self.trf("threads_info", scan=SCAN_WORKERS, clean=CLEAN_WORKERS))
        self.log(self.tr("mode_admin") if self.is_admin else self.tr("mode_limited"))
        self.refresh_selection_stats()
        self.apply_language()


    def configure_window_geometry(self):
        screen_w = max(1024, int(self.winfo_screenwidth() or 1540))
        screen_h = max(720, int(self.winfo_screenheight() or 980))

        target_w = min(1540, max(980, int(screen_w * 0.92)))
        target_h = min(980, max(680, int(screen_h * 0.90)))
        min_w = min(target_w, max(920, int(screen_w * 0.70)))
        min_h = min(target_h, max(620, int(screen_h * 0.74)))

        pos_x = max(0, (screen_w - target_w) // 2)
        pos_y = max(0, (screen_h - target_h) // 2)

        self.geometry(f"{target_w}x{target_h}+{pos_x}+{pos_y}")
        self.minsize(min_w, min_h)

    def configure_toplevel_geometry(self, win: ctk.CTkToplevel, preferred: Sequence[int], minimum: Sequence[int]) -> None:
        screen_w = max(640, int(self.winfo_screenwidth() or preferred[0]))
        screen_h = max(520, int(self.winfo_screenheight() or preferred[1]))

        pref_w, pref_h = int(preferred[0]), int(preferred[1])
        min_w = min(pref_w, max(420, int(minimum[0])))
        min_h = min(pref_h, max(360, int(minimum[1])))
        width = min(pref_w, max(min_w, int(screen_w * 0.78)))
        height = min(pref_h, max(min_h, int(screen_h * 0.78)))
        pos_x = max(0, (screen_w - width) // 2)
        pos_y = max(0, (screen_h - height) // 2)

        win.geometry(f"{width}x{height}+{pos_x}+{pos_y}")
        win.minsize(min_w, min_h)

    def schedule_responsive_layout(self):
        pending = getattr(self, "_responsive_after_id", None)
        if pending:
            try:
                self.after_cancel(pending)
            except Exception:
                pass
        self._responsive_after_id = self.after(90, self.refresh_responsive_layout)

    def on_window_configure(self, event=None):
        if event is not None and getattr(event, "widget", None) is not self:
            return
        self.schedule_responsive_layout()

    def layout_summary_cards(self, columns: int):
        cards = [
            self.card_selected,
            self.card_profile,
            self.card_estimate,
            self.card_admin,
        ]
        columns = 4 if columns >= 4 else 2 if columns >= 2 else 1
        if self._layout_state.get("summary_columns") == columns:
            return
        self._layout_state["summary_columns"] = columns

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

        if stacked:
            for button in buttons:
                button.pack(fill="x", pady=(0, 8))
        else:
            self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 8))
            self.btn_analyze.pack(side="left", padx=(0, 8))
            self.btn_reset_all.pack(side="left")

    def refresh_responsive_layout(self):
        try:
            self._responsive_after_id = None
            width = max(int(self.winfo_width() or 0), int(self.winfo_reqwidth() or 0), 980)
            height = max(int(self.winfo_height() or 0), int(self.winfo_reqheight() or 0), 680)

            sidebar_width = 390 if width >= 1560 else 350 if width >= 1360 else 315 if width >= 1180 else 280
            footer_height = 198 if height >= 900 else 180 if height >= 780 else 164
            content_width = max(320, width - sidebar_width - 90)
            wraplength = max(340, min(980, content_width - 130))

            if self._layout_state.get("sidebar_width") != sidebar_width:
                self._layout_state["sidebar_width"] = sidebar_width
                self.sidebar.configure(width=sidebar_width)
            if self._layout_state.get("footer_height") != footer_height:
                self._layout_state["footer_height"] = footer_height
                self.footer.configure(height=footer_height)

            summary_columns = 4 if content_width >= 1060 else 2 if content_width >= 560 else 1
            self.layout_summary_cards(summary_columns)
            self.layout_toolbar(content_width < 760)
            self.layout_action_buttons(content_width < 900)

            if self._layout_state.get("desc_wraplength") != wraplength:
                self._layout_state["desc_wraplength"] = wraplength
                for card in self.section_cards:
                    card.update_layout(wraplength)
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
        return self.trf(task.desc_key, **(task.fmt or {}))

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
        self.btn_streamer.configure(text=self.tr("streamer"))
        self.btn_low_end.configure(text=self.tr("low_end"))
        self.btn_reset_selection.configure(text=self.tr("reset_selection"))
        if hasattr(self, "btn_about"):
            self.btn_about.configure(text=self.tr("about"))
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
        self.scroll.configure(label_text=self.tr("modules"))
        self.card_sys.set_header(self.tr("sec_system_title"), self.tr("sec_system_sub"))
        self.card_net.set_header(self.tr("sec_net_title"), self.tr("sec_net_sub"))
        self.card_deep.set_header(self.tr("sec_deep_title"), self.tr("sec_deep_sub"))
        self.card_gamer.set_header(self.tr("sec_gamer_title"), self.tr("sec_gamer_sub"))
        self.card_ult.set_header(self.tr("sec_ult_title"), self.tr("sec_ult_sub"))
        for card in self.section_cards:
            card.refresh_rows_language()
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
            self.btn_admin = ctk.CTkButton(
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
        self.btn_safe = ctk.CTkButton(quick, text=self.tr("safe"), height=34, command=self.apply_safe_preset, fg_color="#1E293B", hover_color="#334155")
        self.btn_safe.pack(fill="x", padx=14, pady=(0, 8))
        self.btn_streamer = ctk.CTkButton(quick, text=self.tr("streamer"), height=34, command=self.apply_streamer_mode, fg_color="#0F766E", hover_color="#115E59")
        self.btn_streamer.pack(fill="x", padx=14, pady=(0, 8))
        self.btn_low_end = ctk.CTkButton(quick, text=self.tr("low_end"), height=34, command=self.apply_low_end_mode, fg_color="#166534", hover_color="#14532D")
        self.btn_low_end.pack(fill="x", padx=14, pady=(0, 8))
        self.btn_reset_selection = ctk.CTkButton(quick, text=self.tr("reset_selection"), height=34, command=self.clear_selection, fg_color="#374151", hover_color="#4B5563")
        self.btn_reset_selection.pack(fill="x", padx=14, pady=(0, 14))
        # About
        self.btn_about = ctk.CTkButton(
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
        self.btn_copy_log = ctk.CTkButton(btn_frame, text=self.tr("copy_log"), fg_color="#334155", hover_color="#475569", width=118, command=self.copy_log_to_clipboard)
        self.btn_copy_log.pack(side="left")
        self.btn_clear_log = ctk.CTkButton(btn_frame, text=self.tr("clear_log"), fg_color="#334155", hover_color="#475569", width=110, command=self.clear_log)
        self.btn_clear_log.pack(side="left", padx=8)
        self.btn_cancel = ctk.CTkButton(btn_frame, text=self.tr("stop"), fg_color="#4B5563", hover_color="#6B7280", width=110, state="disabled", command=self.cancel_current_run)
        self.btn_cancel.pack(side="right")

    def build_main_area(self):
        self.main_wrap = ctk.CTkFrame(self, fg_color="transparent")
        self.main_wrap.grid(row=0, column=1, sticky="nsew", padx=18, pady=18)
        self.main_wrap.grid_columnconfigure(0, weight=1)
        self.main_wrap.grid_rowconfigure(2, weight=1)

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
        self.toolbar.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        self.toolbar.grid_columnconfigure(1, weight=1)

        self.search_label = ctk.CTkLabel(self.toolbar, text=self.tr("search_modules"), font=("Segoe UI", 12, "bold"), text_color=COLORS["white"])
        self.search_label.grid(row=0, column=0, padx=14, pady=12)
        self.search_var = ctk.StringVar(value="")
        self.search_var.trace_add("write", lambda *_: self.schedule_search_filter())
        self.search_entry = ctk.CTkEntry(self.toolbar, textvariable=self.search_var, placeholder_text=self.tr("search_placeholder"), height=38, border_color=COLORS["border"], fg_color=COLORS["bg_soft"])
        self.search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=10)
        self.btn_clear_search = ctk.CTkButton(self.toolbar, text=self.tr("clear_search"), width=130, command=lambda: self.search_var.set(""), fg_color="#334155", hover_color="#475569")
        self.btn_clear_search.grid(row=0, column=2, padx=(0, 12))

        self.scroll = ctk.CTkScrollableFrame(self.main_wrap, fg_color="transparent", label_text=self.tr("modules"))
        self.scroll.grid(row=2, column=0, sticky="nsew")
        self.scroll.grid_columnconfigure(0, weight=1)

        self.card_sys = SectionCard(self, self.scroll, self.tr("sec_system_title"), self.tr("sec_system_sub"), COLORS["system"])
        self.card_sys.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        self.section_cards.append(self.card_sys)
        self.register_system_tasks()

        self.card_net = SectionCard(self, self.scroll, self.tr("sec_net_title"), self.tr("sec_net_sub"), COLORS["browsers"])
        self.card_net.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        self.section_cards.append(self.card_net)
        self.register_browser_tasks()

        self.card_deep = SectionCard(self, self.scroll, self.tr("sec_deep_title"), self.tr("sec_deep_sub"), COLORS["deep"])
        self.card_deep.grid(row=2, column=0, sticky="ew", pady=(0, 16))
        self.section_cards.append(self.card_deep)
        self.register_deep_tasks()

        self.card_gamer = SectionCard(self, self.scroll, self.tr("sec_gamer_title"), self.tr("sec_gamer_sub"), COLORS["gamer"])
        self.card_gamer.grid(row=3, column=0, sticky="ew", pady=(0, 16))
        self.section_cards.append(self.card_gamer)
        self.register_gamer_tasks()

        self.card_ult = SectionCard(self, self.scroll, self.tr("sec_ult_title"), self.tr("sec_ult_sub"), COLORS["ultimate"])
        self.card_ult.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        self.section_cards.append(self.card_ult)
        self.register_ultimate_tasks()

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
        self.btn_start = ctk.CTkButton(self.footer_actions, text=self.tr("analyze_clean"), font=("Segoe UI", 16, "bold"), height=48, corner_radius=10, fg_color=COLORS["success"], hover_color="#16A34A", command=self.start_thread)
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.btn_analyze = ctk.CTkButton(self.footer_actions, text=self.tr("analyze_only"), font=("Segoe UI", 14, "bold"), width=160, height=48, fg_color=COLORS["system"], hover_color="#2563EB", command=self.start_analysis_thread)
        self.btn_analyze.pack(side="left", padx=(0, 8))

        self.btn_reset_all = ctk.CTkButton(self.footer_actions, text=self.tr("reset_all"), font=("Segoe UI", 14, "bold"), width=150, height=48, fg_color="#374151", hover_color="#4B5563", command=self.clear_selection)
        self.btn_reset_all.pack(side="left")

    def add_task(self, parent_card: SectionCard, task: CleanerTask):
        self.tasks[task.key] = task
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

        local = os.environ.get("LOCALAPPDATA", "")
        for key, tkey, dkey, path in [
            ("recent_docs", "task.recent_docs.title", "task.recent_docs.desc", os.path.join(local, r"Microsoft\Windows\Recent")),
            ("thumb_cache", "task.thumb_cache.title", "task.thumb_cache.desc", os.path.join(local, r"Microsoft\Windows\Explorer")),
        ]:
            if os.path.exists(path):
                self.add_task(self.card_sys, CleanerTask(key=key, title_key=tkey, desc_key=dkey, path=path, category="system", default=False))

    def register_browser_tasks(self):
        local = os.environ.get("LOCALAPPDATA", "")
        roaming = os.environ.get("APPDATA", "")
        browser_paths = [
            ("browser_chrome", "task.browser_chrome.title", "task.browser_chrome.desc", os.path.join(local, r"Google\Chrome\User Data\Default\Cache")),
            ("browser_edge", "task.browser_edge.title", "task.browser_edge.desc", os.path.join(local, r"Microsoft\Edge\User Data\Default\Cache")),
            ("browser_brave", "task.browser_brave.title", "task.browser_brave.desc", os.path.join(local, r"BraveSoftware\Brave-Browser\User Data\Default\Cache")),
            ("browser_opera", "task.browser_opera.title", "task.browser_opera.desc", os.path.join(roaming, r"Opera Software\Opera Stable\Cache")),
            ("discord_cache", "task.discord_cache.title", "task.discord_cache.desc", os.path.join(roaming, r"discord\Cache")),
            ("discord_gpu_cache", "task.discord_gpu_cache.title", "task.discord_gpu_cache.desc", os.path.join(roaming, r"discord\GPUCache")),
        ]
        for key, tkey, dkey, path in browser_paths:
            if os.path.exists(path):
                self.add_task(self.card_net, CleanerTask(key=key, title_key=tkey, desc_key=dkey, path=path, category="browsers", default=False))

        firefox_profiles = os.path.join(local, r"Mozilla\Firefox\Profiles")
        if os.path.exists(firefox_profiles):
            for profile in os.listdir(firefox_profiles):
                profile_path = os.path.join(firefox_profiles, profile)
                if not os.path.isdir(profile_path):
                    continue
                for suffix, title_key in (("cache2", "task.firefox_cache2.title"), ("startupCache", "task.firefox_startupCache.title")):
                    target = os.path.join(profile_path, suffix)
                    if os.path.exists(target):
                        key = f"firefox_{profile}_{suffix}".replace(".", "_")
                        self.add_task(self.card_net, CleanerTask(
                            key=key, title_key=title_key, desc_key=f"task.firefox_{suffix}.desc", path=target, category="browsers", default=False, fmt={"profile": profile},
                        ))

        self.add_task(self.card_net, CleanerTask(
            key="dns_flush", title_key="task.dns_flush.title", desc_key="task.dns_flush.desc",
            kind="command", category="browsers", default=True,
            command=lambda: self.run_logged_command("ipconfig /flushdns", "dns_ok", "dns_fail"),
        ))

    def register_deep_tasks(self):
        state = "normal" if self.is_admin else "disabled"
        local = os.environ.get("LOCALAPPDATA", "")
        deep_dirs = [
            ("prefetch", "task.prefetch.title", "task.prefetch.desc", r"C:\Windows\Prefetch"),
            ("error_logs", "task.error_logs.title", "task.error_logs.desc", r"C:\ProgramData\Microsoft\Windows\WER"),
            ("update_cache_files", "task.update_cache_files.title", "task.update_cache_files.desc", r"C:\Windows\SoftwareDistribution\Download"),
            ("delivery_opt", "task.delivery_opt.title", "task.delivery_opt.desc", os.path.join(local, r"Microsoft\Windows\DeliveryOptimization\Cache")),
        ]
        for key, tkey, dkey, path in deep_dirs:
            if os.path.exists(path):
                self.add_task(self.card_deep, CleanerTask(
                    key=key, title_key=tkey, desc_key=dkey, path=path, category="deep", default=False,
                    state=state if key != "delivery_opt" else "normal", requires_admin=(key != "delivery_opt"),
                ))

        self.add_task(self.card_deep, CleanerTask(
            key="recycle", title_key="task.recycle.title", desc_key="task.recycle.desc",
            kind="command", category="deep", default=False,
            command=lambda: self.run_logged_command('powershell -NoProfile -Command "Clear-RecycleBin -Force"', "recycle_ok", "recycle_fail", timeout=120),
        ))

        self.add_task(self.card_deep, CleanerTask(
            key="reset_winsock", title_key="task.reset_winsock.title", desc_key="task.reset_winsock.desc",
            kind="command", category="deep", default=False, state=state, requires_admin=True,
            command=lambda: self.run_logged_command("netsh winsock reset", "winsock_ok", "winsock_fail", timeout=120),
        ))

    def register_gamer_tasks(self):
        local = os.environ.get("LOCALAPPDATA", "")
        appdata = os.environ.get("APPDATA", "")
        programdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        state = "normal" if self.is_admin else "disabled"
        gamer_dirs = [
            ("dx_shader_cache", "task.dx_shader_cache.title", "task.dx_shader_cache.desc", os.path.join(local, r"D3DSCache"), False, False),
            ("nvidia_dx", "task.nvidia_dx.title", "task.nvidia_dx.desc", os.path.join(local, r"NVIDIA\DXCache"), False, False),
            ("nvidia_gl", "task.nvidia_gl.title", "task.nvidia_gl.desc", os.path.join(local, r"NVIDIA\GLCache"), False, False),
            ("nvidia_nv_cache", "task.nvidia_nv_cache.title", "task.nvidia_nv_cache.desc", os.path.join(programdata, r"NVIDIA Corporation\NV_Cache"), False, True),
            ("amd_dx", "task.amd_dx.title", "task.amd_dx.desc", os.path.join(local, r"AMD\DxCache"), False, False),
            ("amd_gl", "task.amd_gl.title", "task.amd_gl.desc", os.path.join(local, r"AMD\GLCache"), False, False),
            ("steam_htmlcache", "task.steam_htmlcache.title", "task.steam_htmlcache.desc", os.path.join(local, r"Steam\htmlcache"), False, False),
            ("battle_net_cache", "task.battle_net_cache.title", "task.battle_net_cache.desc", os.path.join(programdata, r"Battle.net\Agent"), False, True),
            ("epic_webcache", "task.epic_webcache.title", "task.epic_webcache.desc", os.path.join(local, r"EpicGamesLauncher\Saved\webcache"), False, False),
            ("temp_capture_cache", "task.temp_capture_cache.title", "task.temp_capture_cache.desc", os.path.join(appdata, r"obs-studio\plugin_config\obs-browser\Cache"), False, False),
        ]
        for key, tkey, dkey, path, default, requires_admin in gamer_dirs:
            if os.path.exists(path):
                self.add_task(self.card_gamer, CleanerTask(
                    key=key, title_key=tkey, desc_key=dkey, path=path, category="gamer", default=default,
                    state=state if requires_admin else "normal", requires_admin=requires_admin,
                ))

        self.add_task(self.card_gamer, CleanerTask(
            key="disable_gamedvr", title_key="task.disable_gamedvr.title", desc_key="task.disable_gamedvr.desc",
            kind="command", category="gamer", default=False, command=self.disable_game_dvr,
        ))
        self.add_task(self.card_gamer, CleanerTask(
            key="high_perf_plan", title_key="task.high_perf_plan.title", desc_key="task.high_perf_plan.desc",
            kind="command", category="gamer", default=False, state=state, requires_admin=True,
            command=lambda: self.run_logged_command("powercfg /S SCHEME_MIN", "high_perf_ok", "high_perf_fail", timeout=90),
        ))
        self.add_task(self.card_gamer, CleanerTask(
            key="ultimate_perf_plan", title_key="task.ultimate_perf_plan.title", desc_key="task.ultimate_perf_plan.desc",
            kind="command", category="gamer", default=False, state=state, requires_admin=True, command=self.enable_ultimate_performance,
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

    def apply_search_filter(self):
        self._search_after_id = None
        query = self.search_var.get()
        normalized_query = query.strip().lower()
        if normalized_query == self._last_search_query:
            return
        self._last_search_query = normalized_query
        for card in self.section_cards:
            card.filter_rows(normalized_query)

    def refresh_selection_stats(self):
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
        while True:
            try:
                messages.append(self.log_queue.get_nowait())
            except queue.Empty:
                break
        if messages:
            self.console.configure(state="normal")
            self.console.insert("end", "\n".join(messages) + "\n")
            self.console.see("end")
            self.console.configure(state="disabled")
        self.after(140, self.flush_log_queue)

    def copy_log_to_clipboard(self):
        content = self.console.get("1.0", "end")
        self.clipboard_clear()
        self.clipboard_append(content)
        self.log(self.tr("log_copied"))

    def clear_log(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")
        self.log(self.tr("log_cleared"))

    def clear_selection(self):
        for key, var in self.vars.items():
            if self.tasks[key].state != "disabled":
                var.set(False)
        self.analysis_total_bytes = 0
        self.total_size_bytes = 0
        self.lbl_analysis.configure(text=self.tr("selected_reset_hint"), text_color=COLORS["text_gray"])
        self.set_profile_name(self.tr("profile_manual"), COLORS["gamer"])
        self.refresh_selection_stats()
        self.log(self.tr("selection_cleared"))

    def apply_safe_preset(self):
        self.clear_selection()
        safe_keywords = ("temp", "cache", "dns")
        for key, var in self.vars.items():
            task = self.tasks.get(key)
            if not task or task.state == "disabled":
                continue
            if any(word in key for word in safe_keywords):
                if task.kind == "directory" and not task.requires_admin:
                    var.set(True)
            if task.key == "dns_flush":
                var.set(True)
        self.set_profile_name(self.tr("safe"), COLORS["system"])
        self.refresh_selection_stats()
        self.log(self.tr("safe_profile_on"))

    def apply_streamer_mode(self):
        self.clear_selection()
        preferred = {
            "dns_flush", "browser_chrome", "browser_edge", "browser_brave", "browser_opera",
            "discord_cache", "discord_gpu_cache", "steam_htmlcache", "epic_webcache",
            "battle_net_cache", "temp_capture_cache", "disable_gamedvr"
        }
        for key, var in self.vars.items():
            task = self.tasks.get(key)
            if not task or task.state == "disabled":
                continue
            if key in preferred:
                var.set(True)
            elif task.category == "gamer" and "shader" not in key and "perf_plan" not in key and task.kind == "directory":
                var.set(True)
        self.set_profile_name(self.tr("profile_streamer"), COLORS["gamer"])
        self.refresh_selection_stats()
        self.log(self.tr("streamer_profile_on"))

    def apply_low_end_mode(self):
        self.clear_selection()
        preferred = {
            "dns_flush", "dx_shader_cache", "nvidia_dx", "nvidia_gl", "nvidia_nv_cache",
            "amd_dx", "amd_gl", "steam_htmlcache", "epic_webcache", "battle_net_cache",
            "discord_cache", "discord_gpu_cache", "thumb_cache", "recent_docs",
            "disable_gamedvr", "high_perf_plan"
        }
        if self.is_admin:
            preferred.add("ultimate_perf_plan")
        for key, var in self.vars.items():
            task = self.tasks.get(key)
            if not task or task.state == "disabled":
                continue
            if key in preferred:
                var.set(True)
        self.set_profile_name(self.tr("profile_low_end"), COLORS["success"])
        self.refresh_selection_stats()
        self.log(self.tr("low_end_profile_on"))

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
        if not running:
            self.progress.stop()

    def run_logged_command(self, cmd: str, success_key: str, fail_key: str, timeout: int = 180):
        ok = WindowsOps.run_command(cmd, timeout=timeout)
        self.log(self.tr(success_key) if ok else self.tr(fail_key))

    def disable_game_dvr(self):
        ok1 = WindowsOps.reg_add(r"HKCU\System\GameConfigStore", "GameDVR_Enabled", 0)
        ok2 = WindowsOps.reg_add(r"HKCU\Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled", 0)
        self.log(self.tr("game_dvr_ok") if (ok1 and ok2) else self.tr("game_dvr_fail"))

    def enable_ultimate_performance(self):
        ok = WindowsOps.try_enable_ultimate_performance()
        self.log(self.tr("ultimate_perf_ok") if ok else self.tr("ultimate_perf_fail"))

    def run_dism_cleanup(self):
        self.dism_running = True
        try:
            self.log(self.tr("dism_started"))
            ok = WindowsOps.run_command("dism.exe /Online /Cleanup-Image /StartComponentCleanup /ResetBase", timeout=3600, noisy=True)
            self.log(self.tr("dism_ok") if ok else self.tr("dism_fail"))
        finally:
            self.dism_running = False

    def start_analysis_thread(self):
        if self.is_running:
            return
        self.cancel_event.clear()
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
        return chosen

    def update_progress(self, removed_bytes: int):
        with self.total_lock:
            self.cleaned_bytes += max(0, removed_bytes)
            mb = self.cleaned_bytes / (1024 ** 2)
            self.after(0, lambda: self.lbl_stats.configure(text=self.trf("freed_fmt", mb=mb), text_color=COLORS["success"]))
            if self.total_size_bytes > 0:
                progress = min(self.cleaned_bytes / self.total_size_bytes, 1.0)
                self.after(0, lambda value=progress: self.progress.set(value))

    def analyze_directory_tasks(self, dir_tasks: List[CleanerTask]) -> Tuple[int, Dict[str, int], List[Tuple[str, int]]]:
        total = 0
        category_totals: Dict[str, int] = {key: 0 for key in ("system", "browsers", "deep", "gamer", "ultimate")}
        detail_rows: List[Tuple[str, int]] = []
        if not dir_tasks:
            return 0, category_totals, detail_rows

        self.log(self.trf("analyzing_targets_fmt", count=len(dir_tasks), workers=SCAN_WORKERS))
        with concurrent.futures.ThreadPoolExecutor(max_workers=SCAN_WORKERS) as pool:
            future_map = {pool.submit(SafeFS.fast_size, task.path): task for task in dir_tasks if task.path}
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
        if not dir_tasks:
            return
        self.log(self.trf("cleaning_targets_fmt", count=len(dir_tasks), workers=CLEAN_WORKERS))
        with concurrent.futures.ThreadPoolExecutor(max_workers=CLEAN_WORKERS) as pool:
            futures = [pool.submit(SafeFS.clean_directory, task.path, self.update_progress, self.cancel_event) for task in dir_tasks if task.path]
            for future in concurrent.futures.as_completed(futures):
                if self.cancel_event.is_set():
                    break
                try:
                    future.result()
                except Exception:
                    continue

    def perform_pre_analysis(self, chosen: List[CleanerTask]) -> Tuple[List[CleanerTask], List[CleanerTask]]:
        dir_tasks = [task for task in chosen if task.kind == "directory" and task.path and os.path.exists(task.path)]
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
        if not any(task.key == "update_cache_files" for task in dir_tasks):
            return
        if start:
            self.log(self.tr("stop_update_services"))
            WindowsOps.run_command("net stop wuauserv", timeout=60)
            WindowsOps.run_command("net stop bits", timeout=60)
        else:
            self.log(self.tr("start_update_services"))
            WindowsOps.run_command("net start wuauserv", timeout=60)
            WindowsOps.run_command("net start bits", timeout=60)

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
                    except Exception:
                        self.log(self.trf("action_error_fmt", title=self.task_title(task)))
            if self.cancel_event.is_set():
                self.log(self.tr("user_stopped"))
            else:
                self.after(0, lambda: self.progress.set(1))
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

        btn_copy = ctk.CTkButton(head, text=self.tr("about_copy"), height=34, width=120, fg_color=COLORS["bg_soft"], hover_color="#1F2937", text_color=COLORS["white"])
        btn_copy.grid(row=0, column=2, sticky="e")

        import tkinter as tk
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

        ctk.CTkButton(wrap, text=self.tr("about_close"), height=40, fg_color=COLORS["gamer"], hover_color="#059669", command=win.destroy).pack(fill="x", padx=16, pady=(0, 16))

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
            ctk.CTkButton(row, text=self.tr("about_open"), height=36, width=120, fg_color=COLORS["gamer"], hover_color="#059669", command=lambda: self.open_doc_in_app(filename, title_key)).pack(side="right", padx=12, pady=12)

        doc_row("about_license", "about_license_sub", "LICENSE", "about_license")
        doc_row("about_privacy", "about_privacy_sub", "PRIVACY_POLICY.txt", "about_privacy")

        ctk.CTkButton(wrap, text=self.tr("about_close"), height=42, fg_color=COLORS["bg_soft"], hover_color="#1F2937", text_color=COLORS["white"], command=win.destroy).pack(fill="x", padx=18, pady=(8, 18))


    def on_close(self):
        if self.dism_running:
            self.log(self.tr("dism_busy_close_blocked"))
            return
        if self.is_running:
            self.cancel_event.set()
        self.destroy()


if __name__ == "__main__":
    Cleaner().mainloop()
