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
import writing_profile

APP_TITLE = "Google Doc Typer"
HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(HERE, "settings.json")
PROFILE_PATH = os.path.join(HERE, "writing_profile.json")

HOTKEY_START = 1
HOTKEY_PAUSE = 2

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

    def __init__(self, events, cfg, outbox, own_title, watcher=None,
                 source_offset=0):
        super().__init__(daemon=True)
        self.events = events
        self.cfg = cfg
        self.outbox = outbox
        self.own_title = own_title
        self.watcher = watcher
        self.source_offset = source_offset   # where in the text this run began
        self.stop_flag = threading.Event()
        self.pause_flag = threading.Event()
        self.interrupted = False
        self.source_done = source_offset     # how far through the text we got

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
            self.arm()
            clock = time.perf_counter()

            for delay, kind, value, source_at in self.events:
                self.source_done = self.source_offset + source_at

                # a break: step away, and let the user have their machine back
                if kind == "break":
                    if not self.take_break(delay):
                        self.finish("cancelled", done, total)
                        return
                    clock = time.perf_counter()
                    continue

                if self.pause_flag.is_set():
                    if not self.hold():
                        self.finish("cancelled", done, total)
                        return
                    clock = time.perf_counter()

                clock += delay
                now = time.perf_counter()
                if clock < now - 0.25:               # never burst to catch up
                    clock = now
                if not winkeys.sleep_until(clock, self.stopped):
                    self.finish("interrupted" if self.interrupted else "cancelled",
                                done, total)
                    return

                ready, _ = self.target_ready()
                if not ready:
                    self.disarm()
                    if not self.wait_for_target():
                        self.finish("cancelled", done, total)
                        return
                    self.arm()
                    clock = time.perf_counter()

                try:
                    if kind == "char":
                        winkeys.type_char(value)
                    elif kind == "back":
                        winkeys.backspace()
                    elif kind == "left":
                        winkeys.arrow_left()
                    elif kind == "right":
                        winkeys.arrow_right()
                except OSError as exc:
                    self.finish("error", done, total, detail=str(exc))
                    return

                done += 1
                if time.perf_counter() - last_report > 0.15:
                    last_report = time.perf_counter()
                    self.post("progress", typed=done, total=total)

        self.post("progress", typed=done, total=total)
        self.finish("finished", done, total)

    # -- arming, pausing, breaks -----------------------------------------
    def arm(self):
        """Watch for real keystrokes only while we are actually typing."""
        if self.watcher:
            self.watcher.arm()

    def disarm(self):
        if self.watcher:
            self.watcher.disarm()

    def finish(self, reason, done, total, **extra):
        self.disarm()
        self.post("done", reason=reason, typed=done, total=total,
                  source_done=self.source_done, **extra)

    def hold(self):
        """Sit still while paused. False if we were stopped instead."""
        self.disarm()
        self.post("status", text="Paused. Resume when you are ready.")
        while self.pause_flag.is_set():
            if self.stopped():
                return False
            time.sleep(0.1)
        if not self.wait_for_target():
            return False
        self.post("status", text="Resuming...")
        self.arm()
        return True

    def take_break(self, seconds):
        """A deliberate gap between writing sessions - the machine is yours."""
        self.disarm()
        ends = time.perf_counter() + seconds
        while True:
            left = ends - time.perf_counter()
            if left <= 0:
                break
            if self.stopped():
                return False
            mins, secs = divmod(int(left), 60)
            self.post("status",
                      text=f"On a break - back in {mins}m {secs:02d}s. "
                           f"Use your computer normally (Esc cancels).")
            time.sleep(min(1.0, left))
        if not self.wait_for_target():
            return False
        self.post("status", text="Break over - picking up where it left off.")
        self.arm()
        return True


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
        self.resume_at = 0            # where an interrupted run stopped

        # one message-loop thread hosts both the input hooks and the hotkeys
        self.watcher = winkeys.InputWatcher(
            on_user_input=self._on_user_input, on_hotkey=self._on_hotkey)
        self.watcher.start(hotkeys={
            HOTKEY_START: (winkeys.MOD_CONTROL | winkeys.MOD_ALT, ord("T")),
            HOTKEY_PAUSE: (winkeys.MOD_CONTROL | winkeys.MOD_ALT, ord("P")),
        })

        self._build()
        self.load_settings()
        self.load_profile_if_saved()
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
        self.pause_btn = ttk.Button(bar, text="Pause", command=self.toggle_pause,
                                    state="disabled")
        self.pause_btn.pack(side="left", padx=(0, 6))
        self.resume_btn = ttk.Button(bar, text="Resume where it stopped",
                                     command=self.resume_run, state="disabled")
        self.resume_btn.pack(side="left", padx=(0, 6))
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

        ttk.Button(right, text="Learn from my Google Doc history...",
                   command=self.learn_profile).pack(fill="x", pady=(0, 6))
        self.profile_label = ttk.Label(right, text="No writing profile loaded.",
                                       style="Muted.TLabel", wraplength=250)
        self.profile_label.pack(fill="x", pady=(0, 6))

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
                       ("notice_min", "notice_max"),
                       ("revise_every_min", "revise_every_max"),
                       ("reread_min", "reread_max"),
                       ("spot_min", "spot_max")):
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

    def learn_profile(self):
        """Read a saved Docs revisions/load response and copy what it shows."""
        path = filedialog.askopenfilename(
            title="Open a saved Google Docs revision changelog",
            filetypes=[("Changelog", "*.json *.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            profile = writing_profile.analyse(path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror(
                APP_TITLE, "Could not read that file.\n\n" + str(exc))
            return

        cfg = self.get_config()
        applied = writing_profile.apply_to_config(profile, cfg)
        self.set_config(cfg)
        self._install_misspellings(profile)
        try:
            with open(PROFILE_PATH, "w", encoding="utf-8") as fh:
                json.dump(profile, fh, indent=2)
        except OSError:
            pass
        self.preset.set("")
        self.save_settings()      # so the learned numbers survive a restart too
        self.set_status(f"Learned from your writing: {writing_profile.summary(profile)} "
                        f"({len(applied)} settings updated).")

    def _install_misspellings(self, profile):
        words = profile.get("misspellings") or {}
        if words:
            total = engine.use_misspellings(words)
            self.profile_label.configure(
                text=f"Profile: {len(words)} of your own misspellings "
                     f"({total} words total).")
        else:
            self.profile_label.configure(
                text="Profile loaded, but no misspellings found in it.")

    def load_profile_if_saved(self):
        if not os.path.exists(PROFILE_PATH):
            return
        try:
            with open(PROFILE_PATH, encoding="utf-8") as fh:
                self._install_misspellings(json.load(fh))
        except (OSError, ValueError):
            pass

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

    def _plan(self, offset=0):
        text = engine.normalise(self.source_text())[offset:]
        if not text.strip():
            messagebox.showinfo(APP_TITLE, "There is no text left to type.")
            return None
        return engine.build_plan(text, self.get_config())

    def estimate(self):
        result = self._plan()
        if not result:
            return
        _events, st = result
        breaks = ""
        if st.breaks:
            typing = sum(e[0] for e in _events if e[1] != "break")
            breaks = (f" That includes {st.breaks} breaks - "
                      f"{engine.format_duration(typing)} of actual typing.")
        self.set_status(
            f"About {engine.format_duration(st.duration)} to type "
            f"{st.chars} characters - {st.keystrokes} keystrokes, "
            f"{st.mistakes} mistakes, {st.revisions} revision passes, "
            f"{st.backspaces} backspaces, {st.arrows} arrow presses." + breaks)

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
            f"Dry run: {st.mistakes} mistakes, {st.corrections} corrections "
            f"over {st.revisions} revision passes, {st.backspaces} backspaces, "
            f"{st.arrows} arrow presses, ~{engine.format_duration(st.duration)}. "
            + ("Final text matches your input." if exact
               else "Some mistakes were left in on purpose."))

    def start(self, offset=0):
        if self.typist and self.typist.is_alive():
            return
        result = self._plan(offset)
        if not result:
            return
        events, st = result
        self.progress.configure(maximum=len(events), value=0)
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.pause_btn.configure(state="normal", text="Pause")
        self.resume_btn.configure(state="disabled")
        note = f" from character {offset}" if offset else ""
        breaks = f", {st.breaks} breaks" if st.breaks else ""
        self.set_status(f"Preparing {st.keystrokes} keystrokes{note} "
                        f"(~{engine.format_duration(st.duration)}{breaks})...")
        self.typist = Typist(events, self.get_config(), self.outbox,
                             self.root.title(), watcher=self.watcher,
                             source_offset=offset)
        self.typist.start()

    def resume_run(self):
        self.start(offset=self.resume_at)

    def toggle_pause(self):
        if not (self.typist and self.typist.is_alive()):
            return
        if self.typist.pause_flag.is_set():
            self.typist.pause_flag.clear()
            self.pause_btn.configure(text="Pause")
        else:
            self.typist.pause_flag.set()
            self.pause_btn.configure(text="Resume")

    # -- callbacks from the watcher thread (keep these cheap) -------------
    def _on_user_input(self, source):
        typist = self.typist
        if typist and typist.is_alive() and not typist.pause_flag.is_set():
            typist.interrupted = True
            typist.stop_flag.set()

    def _on_hotkey(self, hotkey_id):
        self.outbox.put({"kind": "hotkey", "id": hotkey_id})

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
                elif kind == "hotkey":
                    self._handle_hotkey(msg["id"])
                elif kind == "done":
                    self._finish(msg)
        except queue.Empty:
            pass
        self.root.after(80, self._drain)

    def _handle_hotkey(self, hotkey_id):
        if hotkey_id == HOTKEY_START:
            if self.typist and self.typist.is_alive():
                self.stop()
            else:
                self.start()
        elif hotkey_id == HOTKEY_PAUSE:
            self.toggle_pause()

    def _finish(self, msg):
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.pause_btn.configure(state="disabled", text="Pause")
        reason = msg.get("reason")
        self.resume_at = int(msg.get("source_done", 0) or 0)
        full = len(engine.normalise(self.source_text()))
        can_resume = (reason in ("interrupted", "cancelled")
                      and 0 < self.resume_at < full)
        self.resume_btn.configure(state="normal" if can_resume else "disabled")

        if reason == "finished":
            self.set_status("Done - the document has your text.")
        elif reason == "interrupted":
            self.set_status(
                "Stopped - you touched the keyboard or mouse, so it bailed out "
                "rather than risk scrambling the document."
                + (" Click Resume to carry on." if can_resume else ""))
        elif reason == "cancelled":
            self.set_status("Stopped. Whatever was typed is left in the document."
                            + (" Resume is available." if can_resume else ""))
        else:
            self.set_status("Stopped: " + str(msg.get("detail", "unknown error")))

    def on_close(self):
        if self.typist and self.typist.is_alive():
            self.typist.stop_flag.set()
            self.typist.join(timeout=1.0)
        try:
            self.watcher.stop()
        except Exception:
            pass
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
    icon = os.path.join(HERE, "typer.ico")
    if os.path.exists(icon):
        try:
            root.iconbitmap(default=icon)
        except tk.TclError:
            pass
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
