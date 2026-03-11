"""UI design layer: theme, colors, and reusable widgets.

This module contains UI styling constants and widget classes only.
No filesystem operations, Windows registry, or cleanup logic here.
"""

from __future__ import annotations

import customtkinter as ctk
from typing import Optional, List, Tuple

# ---- Theme / colors ----

def init_ui_theme() -> None:
    """Initialize CustomTkinter global theme settings.

    Safe to call multiple times.
    """
    try:
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
    except Exception:
        # If CTk is not available or already initialized, ignore.
        pass


COLORS = {
    "system": "#3B82F6",
    "browsers": "#8B5CF6",
    "deep": "#F59E0B",
    "ultimate": "#EF4444",
    "gamer": "#10B981",
    "success": "#22C55E",
    "warning": "#FACC15",
    "muted": "#94A3B8",
    "bg_card": "#161B22",
    "bg_main": "#0B0F14",
    "bg_soft": "#111827",
    "bg_panel": "#0F172A",
    "border": "#253042",
    "text_gray": "#9CA3AF",
    "white": "#F8FAFC",
}

# ---- Reusable UI components ----

from .logic import CleanerTask  # type: ignore  # (runtime import is safe)


class SummaryCard(ctk.CTkFrame):
    def __init__(self, master, title: str, value: str, color: str):
        super().__init__(master, fg_color=COLORS["bg_card"], corner_radius=14, border_width=1, border_color=COLORS["border"])
        self.grid_columnconfigure(0, weight=1)
        self.title_label = ctk.CTkLabel(self, text=title, text_color=COLORS["text_gray"], font=("Segoe UI", 11, "bold"))
        self.title_label.grid(row=0, column=0, sticky="w", padx=14, pady=(12, 2))
        self.value_label = ctk.CTkLabel(self, text=value, text_color=color, font=("Segoe UI Semibold", 22, "bold"))
        self.value_label.grid(row=1, column=0, sticky="w", padx=14, pady=(0, 12))

    def set(self, text: str, color: Optional[str] = None):
        self.value_label.configure(text=text)
        if color:
            self.value_label.configure(text_color=color)

    def set_title(self, text: str):
        self.title_label.configure(text=text)


class SectionCard(ctk.CTkFrame):
    def __init__(self, owner, master, title, subtitle, color, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_card"], corner_radius=14, border_width=1, border_color=COLORS["border"], **kwargs)
        self.owner = owner
        self.grid_columnconfigure(0, weight=1)
        self.rows: List[Tuple[ctk.CTkCheckBox, ctk.CTkLabel, CleanerTask]] = []
        self.desc_wraplength = 780

        self.accent = ctk.CTkFrame(self, height=4, fg_color=color, corner_radius=3)
        self.accent.grid(row=0, column=0, sticky="ew", padx=1, pady=(1, 8))

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))
        header.grid_columnconfigure(0, weight=1)

        self.header_title = ctk.CTkLabel(header, text=title, text_color=color, font=("Segoe UI", 16, "bold"))
        self.header_title.grid(row=0, column=0, sticky="w")
        self.header_subtitle = ctk.CTkLabel(header, text=subtitle, text_color=COLORS["text_gray"], font=("Segoe UI", 11))
        self.header_subtitle.grid(row=1, column=0, sticky="w")
        self.row_counter = 2

    def add_option(self, variable, task: CleanerTask):
        row_wrap = ctk.CTkFrame(self, fg_color="transparent")
        row_wrap.grid(row=self.row_counter, column=0, sticky="ew", padx=14, pady=(4, 2))
        row_wrap.grid_columnconfigure(0, weight=1)

        chk = ctk.CTkCheckBox(
            row_wrap,
            text=self.owner.task_title(task),
            variable=variable,
            font=("Segoe UI", 13, "bold"),
            state=task.state,
            fg_color=COLORS["success"],
            hover_color="#16A34A",
            border_color="#475569",
            text_color=COLORS["white"] if task.state == "normal" else "gray",
        )
        chk.grid(row=0, column=0, sticky="w")

        if task.state == "disabled":
            badge = ctk.CTkLabel(row_wrap, text=self.owner.tr("badge_admin_needed"), text_color=COLORS["ultimate"], font=("Segoe UI", 10, "bold"))
            badge.grid(row=0, column=1, sticky="e")

        desc_lbl = ctk.CTkLabel(
            self,
            text=self.owner.task_desc(task),
            text_color=COLORS["text_gray"],
            font=("Segoe UI", 11),
            wraplength=self.desc_wraplength,
            justify="left",
            anchor="w",
        )
        desc_lbl.grid(row=self.row_counter + 1, column=0, sticky="ew", padx=42, pady=(0, 12))
        self.rows.append((chk, desc_lbl, task))
        self.row_counter += 2

    def refresh_rows_language(self):
        query = self.owner.search_var.get().strip().lower() if hasattr(self.owner, "search_var") else ""
        for chk, desc_lbl, task in self.rows:
            chk.configure(text=self.owner.task_title(task))
            desc_lbl.configure(text=self.owner.task_desc(task))
            if task.state == "disabled":
                for child in chk.master.winfo_children():
                    if isinstance(child, ctk.CTkLabel):
                        child.configure(text=self.owner.tr("badge_admin_needed"))
            haystack = (self.owner.task_title(task) + " " + self.owner.task_desc(task)).lower()
            visible = not query or query in haystack
            if visible:
                chk.master.grid()
                desc_lbl.grid()
            else:
                chk.master.grid_remove()
                desc_lbl.grid_remove()

    def update_layout(self, wraplength: int):
        wraplength = max(260, wraplength)
        if wraplength == self.desc_wraplength:
            return
        self.desc_wraplength = wraplength
        for _, desc_lbl, _ in self.rows:
            desc_lbl.configure(wraplength=self.desc_wraplength)

    def set_header(self, title: str, subtitle: str):
        self.header_title.configure(text=title)
        self.header_subtitle.configure(text=subtitle)

    def filter_rows(self, query: str):
        query = query.strip().lower()
        for chk, desc_lbl, task in self.rows:
            haystack = (self.owner.task_title(task) + " " + self.owner.task_desc(task)).lower()
            visible = not query or query in haystack
            if visible:
                chk.master.grid()
                desc_lbl.grid()
            else:
                chk.master.grid_remove()
                desc_lbl.grid_remove()


