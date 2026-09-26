"""Dark theme for the typer window.

ttk on Windows defaults to the 'vista' theme, which ignores most colour
options. We switch to 'clam' - the one built-in theme that honours them -
and restyle every widget the app uses, then ask DWM for a dark title bar.
"""

from __future__ import annotations

import ctypes
import tkinter as tk
from tkinter import ttk

BG = "#1b1d23"        # window background
SURFACE = "#242731"   # panels, buttons, tabs
SURFACE_HI = "#2f333f"  # hover
FIELD = "#15171c"     # text areas and entry boxes
BORDER = "#363b47"
FG = "#e6e8ee"
FG_MUTED = "#98a0b0"
FG_DIM = "#5f6673"
ACCENT = "#5b8def"
ACCENT_HI = "#7aa5f5"
SELECT = "#2f4a7a"


def dark_titlebar(root):
    """Ask Windows for a dark title bar (Windows 10 2004+ / Windows 11)."""
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        flag = ctypes.c_int(1)
        for attribute in (20, 19):        # DWMWA_USE_IMMERSIVE_DARK_MODE, older build
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(flag), ctypes.sizeof(flag))
    except Exception:
        pass                               # cosmetic only - never break startup


def style_text(widget, muted=False):
    """Apply the dark palette to a tk.Text (ttk has no text widget)."""
    widget.configure(
        background=SURFACE if muted else FIELD,
        foreground=FG_MUTED if muted else FG,
        insertbackground=ACCENT,
        selectbackground=SELECT,
        selectforeground=FG,
        relief="flat",
        borderwidth=0,
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=BORDER if muted else ACCENT,
        padx=8,
        pady=6,
    )


def apply(root):
    root.configure(background=BG)
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", background=BG, foreground=FG, fieldbackground=FIELD,
                    bordercolor=BORDER, lightcolor=BG, darkcolor=BG,
                    troughcolor=FIELD, insertcolor=FG, focuscolor=ACCENT)

    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=FG)
    style.configure("Heading.TLabel", background=BG, foreground=FG,
                    font=("Segoe UI", 10, "bold"))
    style.configure("Muted.TLabel", background=BG, foreground=FG_MUTED)

    style.configure("TLabelframe", background=BG, bordercolor=BORDER,
                    relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", background=BG, foreground=FG_MUTED)

    style.configure("TButton", background=SURFACE, foreground=FG,
                    bordercolor=BORDER, relief="flat", padding=(10, 5),
                    focusthickness=0)
    style.map("TButton",
              background=[("disabled", BG), ("pressed", ACCENT),
                          ("active", SURFACE_HI)],
              foreground=[("disabled", FG_DIM)],
              bordercolor=[("active", ACCENT)])

    style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                    bordercolor=ACCENT)
    style.map("Accent.TButton",
              background=[("disabled", SURFACE), ("pressed", SELECT),
                          ("active", ACCENT_HI)],
              foreground=[("disabled", FG_DIM)],
              bordercolor=[("disabled", BORDER), ("active", ACCENT_HI)])

    style.configure("TEntry", fieldbackground=FIELD, foreground=FG,
                    bordercolor=BORDER, insertcolor=FG, relief="flat",
                    padding=4)
    style.map("TEntry", bordercolor=[("focus", ACCENT)])

    style.configure("TSpinbox", fieldbackground=FIELD, foreground=FG,
                    bordercolor=BORDER, arrowcolor=FG_MUTED, insertcolor=FG,
                    relief="flat", padding=3, arrowsize=12)
    style.map("TSpinbox",
              bordercolor=[("focus", ACCENT)],
              arrowcolor=[("active", ACCENT), ("disabled", FG_DIM)])

    style.configure("TCombobox", fieldbackground=FIELD, background=SURFACE,
                    foreground=FG, arrowcolor=FG_MUTED, bordercolor=BORDER,
                    relief="flat", padding=3)
    style.map("TCombobox",
              fieldbackground=[("readonly", FIELD)],
              foreground=[("readonly", FG)],
              bordercolor=[("focus", ACCENT)],
              arrowcolor=[("active", ACCENT)])
    # the dropdown is a plain tk listbox and needs option-database colours
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*TCombobox*Listbox.borderWidth", 0)

    style.configure("TNotebook", background=BG, bordercolor=BORDER,
                    tabmargins=(2, 4, 2, 0))
    style.configure("TNotebook.Tab", background=SURFACE, foreground=FG_MUTED,
                    bordercolor=BORDER, padding=(12, 6))
    style.map("TNotebook.Tab",
              background=[("selected", BG), ("active", SURFACE_HI)],
              foreground=[("selected", FG)],
              expand=[("selected", (0, 0, 0, 0))])

    style.configure("TProgressbar", background=ACCENT, troughcolor=FIELD,
                    bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT,
                    thickness=8)

    for orient in ("Vertical", "Horizontal"):
        style.configure(f"{orient}.TScrollbar", background=SURFACE,
                        troughcolor=BG, bordercolor=BG, arrowcolor=FG_MUTED,
                        relief="flat")
        style.map(f"{orient}.TScrollbar",
                  background=[("active", SURFACE_HI), ("pressed", ACCENT)],
                  arrowcolor=[("active", FG)])

    dark_titlebar(root)
    return style
