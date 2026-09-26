"""Google Doc Typer - types text into a document like a person would.

Sends real Windows keystrokes, so it works in Google Docs in any browser
(and anywhere else you can type). Nothing to install: stdlib only.
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import engine
import theme
import winkeys

APP_TITLE = "Google Doc Typer"
HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(HERE, "settings.json")

SAMPLE = (
    "The quarterly review is due tomorrow. I want to separate the budget "
    "section from the summary, because their feedback was pretty clear.\n\n"
    "Paste your own text here, pick a speed, then click Start and click "
    "into your Google Doc before the countdown finishes."
)


# --------------------------------------------------------------------------
# the worker that actually types
# --------------------------------------------------------------------------

class Typist(threading.Thread):
    """Replays a keystroke plan into whatever window has focus."""

    def __init__(self, events, cfg, outbox, own_title):
        super().__init__(daemon=True)
        self.events = events
        self.cfg = cfg
        self.outbox = outbox
        self.own_title = own_title
        self.stop_flag = threading.Event()

    # -- helpers ----------------------------------------------------------
    def post(self, kind, **data):
        self.outbox.put(dict(kind=kind, **data))

    def stopped(self):
        return self.stop_flag.is_set() or winkeys.is_escape_down()

    def target_ready(self):
        """True when the focused window is a sane place to type."""
        title = winkeys.foreground_title()
        if title == self.own_title:
            return False, title
        wanted = self.cfg.window_filter.strip().lower()
        if wanted and wanted not in title.lower():
            return False, title
        return True, title

    def wait_for_target(self):
        """Hold fire while focus is elsewhere. Returns False if stopped."""
        announced = False
        while True:
            ready, title = self.target_ready()
            if ready:
                if announced:
                    self.post("status", text="Focus is back - resuming...")
                return True
            if self.stopped():
                return False
            if not announced:
                wanted = self.cfg.window_filter.strip() or "your document"
                self.post("status",
                          text=f"Paused - click into {wanted} (Esc to cancel)")
                announced = True
            time.sleep(0.15)

    # -- main loop --------------------------------------------------------
    def run(self):
        try:
            self._run()
        except Exception as exc:                      # pragma: no cover
            self.post("done", reason="error", detail=str(exc))

    def _run(self):
        # countdown so the user can click into the document
        remaining = float(self.cfg.start_delay)
        while remaining > 0:
            if self.stopped():
                self.post("done", reason="cancelled")
                return
            self.post("status", text=f"Starting in {remaining:.0f}s - "
                                     f"click into your document now (Esc cancels)")
            time.sleep(min(1.0, remaining))
            remaining -= 1.0

        total = len(self.events)
        done = 0
        last_report = 0.0

        with winkeys.HighResClock():
            if not self.wait_for_target():
                self.post("done", reason="cancelled")
                return
            self.post("status", text="Typing...")
            clock = time.perf_counter()

            for delay, kind, value in self.events:
                clock += delay
                now = time.perf_counter()
                if clock < now - 0.25:               # never burst to catch up
                    clock = now
                if not winkeys.sleep_until(clock, self.stopped):
                    self.post("done", reason="cancelled", typed=done, total=total)
                    return

                ready, _ = self.target_ready()
                if not ready:
                    if not self.wait_for_target():
                        self.post("done", reason="cancelled", typed=done, total=total)
                        return
                    clock = time.perf_counter()

                try:
                    if kind == "char":
                        winkeys.type_char(value)
                    else:
                        winkeys.backspace()
                except OSError as exc:
                    self.post("done", reason="error", detail=str(exc))
                    return

                done += 1
                if time.perf_counter() - last_report > 0.15:
                    last_report = time.perf_counter()
                    self.post("progress", typed=done, total=total)

        self.post("progress", typed=done, total=total)
        self.post("done", reason="finished", typed=done, total=total)


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------

class App(ttk.Frame):
    def __init__(self, root):
        super().__init__(root, padding=10)
        self.root = root
        self.pack(fill="both", expand=True)

        self.vars = {}
        self.typist = None
        self.outbox = queue.Queue()
        self.plan = None

        self._build()
        self.load_settings()
        self.root.after(80, self._drain)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # -- layout -----------------------------------------------------------
    def _build(self):
        left = ttk.Frame(self)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))

        header = ttk.Frame(left)
        header.pack(fill="x")
        ttk.Label(header, text="Text to type",
                  style="Heading.TLabel").pack(side="left")
        ttk.Button(header, text="Open file...",
                   command=self.open_file).pack(side="right")
        ttk.Button(header, text="Clear",
                   command=lambda: self.text.delete("1.0", "end")).pack(side="right", padx=4)

        wrap = ttk.Frame(left)
        wrap.pack(fill="both", expand=True, pady=(4, 6))
        self.text = tk.Text(wrap, wrap="word", undo=True, font=("Consolas", 10),
                            height=18, width=64)
        theme.style_text(self.text)
        scroll = ttk.Scrollbar(wrap, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.text.insert("1.0", SAMPLE)
        self.text.bind("<<Modified>>", self._on_text_change)

        self.preview = tk.Text(left, height=7, wrap="word", font=("Consolas", 9),
                               state="disabled")
        theme.style_text(self.preview, muted=True)
        ttk.Label(left, text="Dry run (what would land in the doc)",
                  style="Muted.TLabel").pack(anchor="w")
        self.preview.pack(fill="x", pady=(2, 6))

        bar = ttk.Frame(left)
        bar.pack(fill="x")
        self.start_btn = ttk.Button(bar, text="Start typing", command=self.start,
                                    style="Accent.TButton")
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(bar, text="Stop (Esc)", command=self.stop,
                                   state="disabled")
        self.stop_btn.pack(side="left", padx=6)
        ttk.Button(bar, text="Dry run", command=self.dry_run).pack(side="left")
        ttk.Button(bar, text="Estimate", command=self.estimate).pack(side="left", padx=6)

        self.progress = ttk.Progressbar(left, mode="determinate")
        self.progress.pack(fill="x", pady=(8, 2))
        self.status = ttk.Label(left, text="Ready.", anchor="w",
                                style="Muted.TLabel")
        self.status.pack(fill="x")

        # ---- settings side ----
        right = ttk.Frame(self)
        right.pack(side="right", fill="y")

        preset_row = ttk.Frame(right)
        preset_row.pack(fill="x", pady=(0, 6))
        ttk.Label(preset_row, text="Preset").pack(side="left")
        self.preset = ttk.Combobox(preset_row, values=list(engine.PRESETS),
                                   state="readonly", width=20)
        self.preset.set("Average typist")
        self.preset.pack(side="left", padx=6)
        self.preset.bind("<<ComboboxSelected>>", self.apply_preset)

        book = ttk.Notebook(right)
        book.pack(fill="both", expand=True)
        for tab_name, rows in engine.NUMERIC_SPEC:
            tab = ttk.Frame(book, padding=8)
            book.add(tab, text=tab_name)
            for r, (attr, label, lo, hi, step) in enumerate(rows):
                ttk.Label(tab, text=label, wraplength=210).grid(
                    row=r, column=0, sticky="w", pady=3)
                var = tk.DoubleVar()
                self.vars[attr] = var
                ttk.Spinbox(tab, from_=lo, to=hi, increment=step, width=8,
                            textvariable=var).grid(row=r, column=1, sticky="e", padx=(8, 0))
            tab.columnconfigure(0, weight=1)

        safety = ttk.LabelFrame(right, text="Safety and repeatability", padding=8)
        safety.pack(fill="x", pady=8)
        ttk.Label(safety, text="Only type into windows titled").grid(
            row=0, column=0, sticky="w")
        self.window_filter = tk.StringVar()
        ttk.Entry(safety, textvariable=self.window_filter, width=24).grid(
            row=1, column=0, sticky="ew", pady=(2, 6))
        ttk.Label(safety, text="Random seed (blank = new every run)").grid(
            row=2, column=0, sticky="w")
        self.seed = tk.StringVar()
        ttk.Entry(safety, textvariable=self.seed, width=24).grid(
            row=3, column=0, sticky="ew", pady=2)
        safety.columnconfigure(0, weight=1)

        btns = ttk.Frame(right)
        btns.pack(fill="x")
        ttk.Button(btns, text="Save settings", command=self.save_settings).pack(side="left")
        ttk.Button(btns, text="Reset defaults",
                   command=lambda: self.set_config(engine.Config())).pack(side="left", padx=6)

    # -- config plumbing --------------------------------------------------
    def get_config(self):
        cfg = engine.Config()
        for attr, var in self.vars.items():
            try:
                setattr(cfg, attr, float(var.get()))
            except (tk.TclError, ValueError):
                pass
        cfg.window_filter = self.window_filter.get()
        cfg.seed = self.seed.get()
        # keep min/max pairs sane no matter what was typed in
        for lo, hi in (("sentence_pause_min", "sentence_pause_max"),
                       ("paragraph_pause_min", "paragraph_pause_max"),
                       ("comma_pause_min", "comma_pause_max"),
                       ("think_min", "think_max"),
                       ("notice_min", "notice_max")):
            if getattr(cfg, lo) > getattr(cfg, hi):
                setattr(cfg, hi, getattr(cfg, lo))
        return cfg

    def set_config(self, cfg):
        for attr, var in self.vars.items():
            var.set(round(getattr(cfg, attr), 4))
        self.window_filter.set(cfg.window_filter)
        self.seed.set(cfg.seed)

    def apply_preset(self, _event=None):
        cfg = engine.Config()
        for key, value in engine.PRESETS[self.preset.get()].items():
            setattr(cfg, key, value)
        cfg.window_filter = self.window_filter.get()
        cfg.seed = self.seed.get()
        self.set_config(cfg)
        self.set_status(f"Preset applied: {self.preset.get()}")

    def load_settings(self):
        cfg = engine.Config()
        if os.path.exists(SETTINGS_PATH):
            try:
                with open(SETTINGS_PATH, encoding="utf-8") as fh:
                    cfg = engine.config_from_dict(json.load(fh))
            except (OSError, ValueError):
                pass
        self.set_config(cfg)

    def save_settings(self):
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
                json.dump(engine.config_to_dict(self.get_config()), fh, indent=2)
            self.set_status(f"Settings saved to {os.path.basename(SETTINGS_PATH)}")
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"Could not save settings:\n{exc}")

    # -- actions ----------------------------------------------------------
    def source_text(self):
        return self.text.get("1.0", "end-1c")

    def _on_text_change(self, _event=None):
        self.text.edit_modified(False)
        chars = len(self.source_text())
        self.set_status(f"{chars} characters ready.")

    def open_file(self):
        path = filedialog.askopenfilename(
            title="Open text file",
            filetypes=[("Text files", "*.txt *.md"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)

    def _plan(self):
        text = self.source_text()
        if not text.strip():
            messagebox.showinfo(APP_TITLE, "There is no text to type.")
            return None
        return engine.build_plan(text, self.get_config())

    def estimate(self):
        result = self._plan()
        if not result:
            return
        _events, st = result
        self.set_status(
            f"About {engine.format_duration(st.duration)} to type "
            f"{st.chars} characters - {st.keystrokes} keystrokes, "
            f"{st.mistakes} mistakes, {st.corrections} corrections, "
            f"{st.backspaces} backspaces.")

    def dry_run(self):
        result = self._plan()
        if not result:
            return
        _events, st = result
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", st.result_text)
        self.preview.configure(state="disabled")
        exact = st.result_text == engine.normalise(self.source_text())
        self.set_status(
            f"Dry run: {st.mistakes} mistakes, {st.corrections} corrections, "
            f"{st.backspaces} backspaces, ~{engine.format_duration(st.duration)}. "
            + ("Final text matches your input." if exact
               else "Some mistakes were left in on purpose."))

    def start(self):
        if self.typist and self.typist.is_alive():
            return
        result = self._plan()
        if not result:
            return
        events, st = result
        self.progress.configure(maximum=len(events), value=0)
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.set_status(f"Preparing {st.keystrokes} keystrokes "
                        f"(~{engine.format_duration(st.duration)})...")
        self.typist = Typist(events, self.get_config(), self.outbox,
                             self.root.title())
        self.typist.start()

    def stop(self):
        if self.typist:
            self.typist.stop_flag.set()
        self.set_status("Stopping...")

    def set_status(self, text):
        self.status.configure(text=text)

    def _drain(self):
        try:
            while True:
                msg = self.outbox.get_nowait()
                kind = msg["kind"]
                if kind == "status":
                    self.set_status(msg["text"])
                elif kind == "progress":
                    self.progress.configure(value=msg["typed"])
                    pct = 100.0 * msg["typed"] / max(msg["total"], 1)
                    self.set_status(f"Typing... {pct:.0f}% "
                                    f"({msg['typed']}/{msg['total']} keystrokes)")
                elif kind == "done":
                    self._finish(msg)
        except queue.Empty:
            pass
        self.root.after(80, self._drain)

    def _finish(self, msg):
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        reason = msg.get("reason")
        if reason == "finished":
            self.set_status("Done - the document has your text.")
        elif reason == "cancelled":
            self.set_status("Stopped. Whatever was typed is left in the document.")
        else:
            self.set_status(f"Stopped: {msg.get('detail', 'unknown error')}")

    def on_close(self):
        if self.typist and self.typist.is_alive():
            self.typist.stop_flag.set()
            self.typist.join(timeout=1.0)
        try:
            self.save_settings()
        except Exception:
            pass
        self.root.destroy()


def main():
    if not sys.platform.startswith("win"):
        print("This tool uses the Windows SendInput API and only runs on Windows.")
        return 1
    root = tk.Tk()
    root.title(APP_TITLE)
    root.minsize(900, 560)
    theme.apply(root)
    try:
        root.call("tk", "scaling", 1.3)
    except tk.TclError:
        pass
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
