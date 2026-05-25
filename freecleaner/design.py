"""UI design layer: theme, colors, and reusable widgets.

This module contains UI styling constants and widget classes only.
No filesystem operations, Windows registry, or cleanup logic here.
"""

from __future__ import annotations

import customtkinter as ctk
from typing import Optional, List, Tuple, Callable, Any

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


def _hex_to_rgb(color: str) -> Tuple[int, int, int]:
    color = color.lstrip('#')
    if len(color) != 6:
        return (15, 23, 42)
    return tuple(int(color[i:i+2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    return '#{:02X}{:02X}{:02X}'.format(*[max(0, min(255, int(v))) for v in rgb])


def mix_colors(color_a: str, color_b: str, weight: float = 0.5) -> str:
    weight = max(0.0, min(1.0, float(weight)))
    a = _hex_to_rgb(color_a)
    b = _hex_to_rgb(color_b)
    return _rgb_to_hex(tuple(round(a[i] * (1.0 - weight) + b[i] * weight) for i in range(3)))

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


class AnimatedButton(ctk.CTkButton):
    """Small CTkButton enhancement with press/hover feedback.

    CustomTkinter already has hover colors.  This wrapper adds a tiny border
    pulse on press/focus without changing layout size, so it is cheap even on
    slower laptops and avoids expensive per-frame widget recreation.
    """

    def __init__(self, *args, accent: str = COLORS["system"], **kwargs):
        self._accent = accent
        self._normal_border = kwargs.get("border_color", "transparent")
        self._normal_border_width = int(kwargs.get("border_width", 0) or 0)
        kwargs.setdefault("corner_radius", 12)
        super().__init__(*args, **kwargs)
        self._pulse_after_id = None
        self.bind("<ButtonPress-1>", self._on_press, add="+")
        self.bind("<ButtonRelease-1>", self._on_release, add="+")
        self.bind("<Leave>", self._on_release, add="+")
        self.bind("<FocusIn>", self._on_focus_in, add="+")
        self.bind("<FocusOut>", self._on_release, add="+")

    def _state_is_disabled(self) -> bool:
        try:
            return str(self.cget("state")) == "disabled"
        except Exception:
            return False

    def _on_press(self, _event=None):
        if self._state_is_disabled():
            return
        try:
            self.configure(border_width=max(1, self._normal_border_width + 1), border_color=self._accent)
        except Exception:
            pass
        if self._pulse_after_id:
            try:
                self.after_cancel(self._pulse_after_id)
            except Exception:
                pass
        try:
            self._pulse_after_id = self.after(130, self._on_release)
        except Exception:
            self._pulse_after_id = None

    def _on_focus_in(self, _event=None):
        if self._state_is_disabled():
            return
        try:
            self.configure(border_width=max(1, self._normal_border_width), border_color=mix_colors(self._accent, COLORS["border"], 0.35))
        except Exception:
            pass

    def _on_release(self, _event=None):
        if self._pulse_after_id:
            try:
                self.after_cancel(self._pulse_after_id)
            except Exception:
                pass
        self._pulse_after_id = None
        try:
            self.configure(border_width=self._normal_border_width, border_color=self._normal_border)
        except Exception:
            pass

# ---- Reusable UI components ----

from .logic import CleanerTask  # type: ignore  # (runtime import is safe)


class SummaryCard(ctk.CTkFrame):
    def __init__(self, master, title: str, value: str, color: str):
        super().__init__(master, fg_color=COLORS["bg_card"], corner_radius=14, border_width=1, border_color=COLORS["border"])
        self.grid_columnconfigure(0, weight=1)
        self._title_text = title
        self._value_text = value
        self._value_color = color
        self._compact = False
        self.title_label = ctk.CTkLabel(self, text=title, text_color=COLORS["text_gray"], font=("Segoe UI", 11, "bold"))
        self.title_label.grid(row=0, column=0, sticky="w", padx=14, pady=(12, 2))
        self.value_label = ctk.CTkLabel(self, text=value, text_color=color, font=("Segoe UI Semibold", 22, "bold"))
        self.value_label.grid(row=1, column=0, sticky="w", padx=14, pady=(0, 12))

    def set(self, text: str, color: Optional[str] = None):
        target_color = color or self._value_color
        if text != self._value_text:
            self._value_text = text
            self.value_label.configure(text=text)
        if target_color != self._value_color:
            self._value_color = target_color
            self.value_label.configure(text_color=target_color)

    def set_title(self, text: str):
        if text == self._title_text:
            return
        self._title_text = text
        self.title_label.configure(text=text)

    def set_compact(self, compact: bool):
        compact = bool(compact)
        if compact == self._compact:
            return
        self._compact = compact
        self.configure(corner_radius=12 if compact else 14)
        self.title_label.configure(font=("Segoe UI", 10 if compact else 11, "bold"))
        self.value_label.configure(font=("Segoe UI Semibold", 18 if compact else 22, "bold"))
        self.title_label.grid_configure(padx=12 if compact else 14, pady=(9 if compact else 12, 1 if compact else 2))
        self.value_label.grid_configure(padx=12 if compact else 14, pady=(0, 9 if compact else 12))


class SectionCard(ctk.CTkFrame):
    def __init__(self, owner, master, title, subtitle, color, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_card"], corner_radius=14, border_width=1, border_color=COLORS["border"], **kwargs)
        self.owner = owner
        self.grid_columnconfigure(0, weight=1)
        self.rows: List[Tuple[Any, ctk.CTkLabel, CleanerTask, ctk.CTkFrame, bool]] = []
        self.desc_wraplength = 780
        self._compact = False

        self.accent = ctk.CTkFrame(self, height=4, fg_color=color, corner_radius=3)
        self.accent.grid(row=0, column=0, sticky="ew", padx=1, pady=(1, 8))

        self.header = ctk.CTkFrame(self, fg_color="transparent")
        self.header.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))
        self.header.grid_columnconfigure(0, weight=1)

        self.header_title = ctk.CTkLabel(self.header, text=title, text_color=color, font=("Segoe UI", 16, "bold"))
        self.header_title.grid(row=0, column=0, sticky="w")
        self.header_subtitle = ctk.CTkLabel(self.header, text=subtitle, text_color=COLORS["text_gray"], font=("Segoe UI", 11))
        self.header_subtitle.grid(row=1, column=0, sticky="w")
        self.row_counter = 2

    def add_option(self, variable, task: CleanerTask):
        row_wrap = ctk.CTkFrame(self, fg_color="transparent")
        row_wrap.grid(row=self.row_counter, column=0, sticky="ew", padx=14, pady=(4, 2))
        row_wrap.grid_columnconfigure(0, weight=1)

        if task.instant_action and task.kind == "command":
            widget = AnimatedButton(
                row_wrap,
                accent=COLORS["gamer"],
                text=self.owner.task_title(task),
                font=("Segoe UI", 13, "bold"),
                height=42,
                corner_radius=12,
                anchor="w",
                state=task.state,
                fg_color=mix_colors(COLORS["gamer"], COLORS["bg_soft"], 0.28),
                hover_color=mix_colors(COLORS["gamer"], COLORS["bg_soft"], 0.42),
                text_color=COLORS["white"] if task.state == "normal" else "gray",
                border_width=1,
                border_color=mix_colors(COLORS["gamer"], COLORS["border"], 0.55),
                command=(lambda t=task: self.owner.invoke_instant_task(t)) if task.state == "normal" else None,
            )
            widget.grid(row=0, column=0, sticky="ew")
        else:
            widget = ctk.CTkCheckBox(
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
            widget.grid(row=0, column=0, sticky="w")

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
        desc_padding = 22 if task.instant_action and task.kind == "command" else 42
        desc_lbl._base_padx = desc_padding  # type: ignore[attr-defined]
        desc_lbl.grid(row=self.row_counter + 1, column=0, sticky="ew", padx=desc_padding, pady=(0, 12))
        if task.instant_action and task.kind == "command" and task.state == "normal":
            desc_lbl.bind("<Button-1>", lambda _e, t=task: self.owner.invoke_instant_task(t))
            desc_lbl.bind("<Enter>", lambda _e: desc_lbl.configure(text_color=COLORS["white"]))
            desc_lbl.bind("<Leave>", lambda _e: desc_lbl.configure(text_color=COLORS["text_gray"]))
        self.rows.append((widget, desc_lbl, task, row_wrap, True))
        self.row_counter += 2

    def _set_row_visible(self, index: int, visible: bool) -> None:
        widget, desc_lbl, task, row_wrap, current = self.rows[index]
        if visible == current:
            return
        if visible:
            row_wrap.grid()
            desc_lbl.grid()
        else:
            row_wrap.grid_remove()
            desc_lbl.grid_remove()
        self.rows[index] = (widget, desc_lbl, task, row_wrap, visible)

    def refresh_rows_language(self) -> int:
        normalizer = getattr(self.owner, "_normalize_search_text", lambda value: str(value or "").casefold().strip())
        query = normalizer(self.owner.search_var.get()) if hasattr(self.owner, "search_var") else ""
        visible_count = 0
        for index, (widget, desc_lbl, task, row_wrap, _visible) in enumerate(self.rows):
            title = self.owner.task_title(task)
            desc = self.owner.task_desc(task)
            if hasattr(widget, "configure"):
                widget.configure(text=title)
            desc_lbl.configure(text=desc)
            if task.state == "disabled":
                for child in row_wrap.winfo_children():
                    if isinstance(child, ctk.CTkLabel):
                        child.configure(text=self.owner.tr("badge_admin_needed"))
            haystack = normalizer(title + " " + desc)
            visible = not query or query in haystack
            if visible:
                visible_count += 1
            self._set_row_visible(index, visible)
        return visible_count

    def update_layout(self, wraplength: int):
        wraplength = max(260, wraplength)
        if wraplength == self.desc_wraplength:
            return
        self.desc_wraplength = wraplength
        for _, desc_lbl, _, _, _ in self.rows:
            desc_lbl.configure(wraplength=self.desc_wraplength)

    def set_header(self, title: str, subtitle: str):
        if self.header_title.cget("text") != title:
            self.header_title.configure(text=title)
        if self.header_subtitle.cget("text") != subtitle:
            self.header_subtitle.configure(text=subtitle)

    def filter_rows(self, query: str) -> int:
        normalizer = getattr(self.owner, "_normalize_search_text", lambda value: str(value or "").casefold().strip())
        query = normalizer(query)
        visible_count = 0
        for index, (widget, desc_lbl, task, _row_wrap, _visible) in enumerate(self.rows):
            haystack = normalizer(self.owner.task_title(task) + " " + self.owner.task_desc(task))
            visible = not query or query in haystack
            if visible:
                visible_count += 1
            self._set_row_visible(index, visible)
        return visible_count

    def set_compact(self, compact: bool) -> None:
        compact = bool(compact)
        if compact == self._compact:
            return
        self._compact = compact
        self.configure(corner_radius=12 if compact else 14)
        self.accent.configure(height=3 if compact else 4)
        self.header_title.configure(font=("Segoe UI", 14 if compact else 16, "bold"))
        self.header_subtitle.configure(font=("Segoe UI", 10 if compact else 11))
        self.header.grid_configure(padx=14 if compact else 16, pady=(0, 9 if compact else 12))
        self.accent.grid_configure(pady=(1, 6 if compact else 8))
        for widget, desc_lbl, task, row_wrap, _visible in self.rows:
            if isinstance(widget, ctk.CTkButton):
                widget.configure(font=("Segoe UI", 12 if compact else 13, "bold"), height=36 if compact else 42, corner_radius=10 if compact else 12)
            else:
                widget.configure(font=("Segoe UI", 12 if compact else 13, "bold"))
            row_wrap.grid_configure(padx=12 if compact else 14, pady=(3 if compact else 4, 1 if compact else 2))
            base_padx = int(getattr(desc_lbl, "_base_padx", 42))
            desc_lbl.configure(font=("Segoe UI", 10 if compact else 11))
            desc_lbl.grid_configure(padx=max(18, base_padx - (8 if compact else 0)), pady=(0, 8 if compact else 12))


class ModernTabButton(ctk.CTkFrame):
    def __init__(self, master, title: str, subtitle: str, accent: str, command: Callable[[], None]):
        self.accent = accent
        self.command = command
        self._active = False
        self._hovered = False
        self._compact = False
        self._last_active_state: Optional[bool] = None
        super().__init__(
            master,
            fg_color=COLORS["bg_card"],
            corner_radius=18,
            border_width=1,
            border_color=COLORS["border"],
            cursor="hand2",
        )
        self.grid_columnconfigure(0, weight=1)

        self.highlight = ctk.CTkFrame(self, height=4, corner_radius=999, fg_color=mix_colors(accent, COLORS["bg_card"], 0.18))
        self.highlight.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))

        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 12))
        self.content.grid_columnconfigure(1, weight=1)

        self.dot = ctk.CTkFrame(self.content, width=11, height=11, corner_radius=999, fg_color=accent)
        self.dot.grid(row=0, column=0, sticky="nw", padx=(0, 10), pady=(5, 0))

        self.labels = ctk.CTkFrame(self.content, fg_color="transparent")
        self.labels.grid(row=0, column=1, sticky="ew")
        self.labels.grid_columnconfigure(0, weight=1)

        self.title_label = ctk.CTkLabel(self.labels, text=title, font=("Segoe UI Semibold", 15, "bold"), text_color=COLORS["white"], anchor="w")
        self.title_label.grid(row=0, column=0, sticky="w")

        self.subtitle_label = ctk.CTkLabel(
            self.labels,
            text=subtitle,
            font=("Segoe UI", 11),
            text_color=COLORS["text_gray"],
            anchor="w",
            justify="left",
            wraplength=360,
        )
        self._subtitle_wrap = 360
        self.subtitle_label.grid(row=1, column=0, sticky="w", pady=(3, 0))

        self.chevron = ctk.CTkLabel(self.content, text="›", font=("Segoe UI", 20, "bold"), text_color=COLORS["text_gray"])
        self.chevron.grid(row=0, column=2, rowspan=2, sticky="e", padx=(12, 2))

        for widget in (self, self.content, self.dot, self.labels, self.title_label, self.subtitle_label, self.chevron, self.highlight):
            widget.bind("<Button-1>", self._on_click)
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)

        self.set_active(False)

    def _on_click(self, _event=None):
        try:
            self.configure(border_color=self.accent)
            self.after(110, lambda: self.set_active(self._active))
        except Exception:
            pass
        try:
            self.command()
        except Exception:
            pass

    def _on_enter(self, _event=None):
        if self._hovered:
            return
        self._hovered = True
        if not self._active:
            self.configure(fg_color=mix_colors(COLORS["bg_card"], self.accent, 0.08), border_color=mix_colors(COLORS["border"], self.accent, 0.35))
            self.highlight.configure(fg_color=mix_colors(COLORS["bg_card"], self.accent, 0.38))
            self.chevron.configure(text_color=mix_colors(COLORS["text_gray"], self.accent, 0.55))

    def _on_leave(self, _event=None):
        self._hovered = False
        if not self._active:
            self._last_active_state = None
            self.set_active(False)

    def set_active(self, active: bool) -> None:
        active = bool(active)
        if self._last_active_state is active and not self._hovered:
            return
        self._last_active_state = active
        self._active = active
        if self._active:
            self.configure(
                fg_color=mix_colors(COLORS["bg_soft"], self.accent, 0.18),
                border_color=mix_colors(COLORS["border"], self.accent, 0.72),
            )
            self.highlight.configure(fg_color=self.accent)
            self.title_label.configure(text_color=COLORS["white"])
            self.subtitle_label.configure(text_color=mix_colors(COLORS["white"], COLORS["text_gray"], 0.30))
            self.chevron.configure(text_color=self.accent)
            self.dot.configure(fg_color=self.accent)
        else:
            self.configure(fg_color=COLORS["bg_card"], border_color=COLORS["border"])
            self.highlight.configure(fg_color=mix_colors(COLORS["bg_card"], self.accent, 0.18))
            self.title_label.configure(text_color=mix_colors(COLORS["white"], COLORS["text_gray"], 0.12))
            self.subtitle_label.configure(text_color=COLORS["text_gray"])
            self.chevron.configure(text_color=COLORS["text_gray"])
            self.dot.configure(fg_color=mix_colors(self.accent, COLORS["text_gray"], 0.30))

    def set_text(self, title: str, subtitle: str) -> None:
        if self.title_label.cget("text") != title:
            self.title_label.configure(text=title)
        if self.subtitle_label.cget("text") != subtitle:
            self.subtitle_label.configure(text=subtitle)

    def set_subtitle_wrap(self, wraplength: int) -> None:
        wraplength = max(180, int(wraplength))
        if wraplength == self._subtitle_wrap:
            return
        self._subtitle_wrap = wraplength
        self.subtitle_label.configure(wraplength=wraplength)

    def set_compact(self, compact: bool) -> None:
        compact = bool(compact)
        if compact == self._compact:
            return
        self._compact = compact
        self.configure(corner_radius=14 if compact else 18)
        self.chevron.configure(font=("Segoe UI", 18 if compact else 20, "bold"))
        self.title_label.configure(font=("Segoe UI Semibold", 14 if compact else 15, "bold"))
        self.subtitle_label.configure(font=("Segoe UI", 10 if compact else 11))
        self.content.grid_configure(padx=12 if compact else 14, pady=(0, 9 if compact else 12))
        self.highlight.grid_configure(padx=9 if compact else 10, pady=(8 if compact else 10, 5 if compact else 6))
