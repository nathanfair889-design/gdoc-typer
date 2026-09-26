# Google Doc Typer

Types text into a Google Doc the way a person does: at a believable pace, with
pauses between sentences and paragraphs, and with mistakes it goes back and
fixes — capitalisation slips, stray inserted letters, transpositions, doubled
letters and common misspellings.

It sends **real Windows keystrokes** (`SendInput`), so Google Docs sees ordinary
typing. No browser extension, no automation framework, no `pip install` —
Python 3 with tkinter is all it needs.

## Running it

Double-click **`Start Typer.bat`**, or:

```bash
python typer_app.py
```

1. Paste your text in the left pane (or **Open file...**).
2. Pick a preset and adjust anything on the right.
3. Click **Start typing**, then click into your Google Doc before the
   countdown ends.
4. Press **Esc** at any time to stop.

Settings are saved to `settings.json` next to the script and reloaded next run.

## Turn off Google Docs autocorrect first

This matters. Under **Tools → Preferences**, uncheck:

- **Automatically capitalise words** — otherwise Docs silently repairs the
  capitalisation mistakes before you can.
- **Automatically correct spelling** — otherwise Docs fixes `teh` for you.

Leave them on and the typos still get typed, they just get repaired by Docs
instead of by the simulated typist.

## The mistakes it makes

| Kind | Example |
| --- | --- |
| Missed shift | `the` for `The` |
| Sticky shift | `THis` for `This` |
| Stray capital | `Report` mid-sentence |
| Adjacent-key substitution | `documemt` |
| Inserted letter | `docuiment` |
| Doubled letter | `Pllease` |
| Transposition | `hte` |
| Dropped letter | `documnt` |
| Common misspelling | `recieve`, `definately`, `seperate`, `thier` (~90 words) |

Each mistake gets noticed on its own schedule — immediately, at the end of the
word, or a few words later — then backspaced out and retyped, with a short
hesitation before the correction starts. A small share can be left in
uncorrected, which is what real typing looks like.

## Settings

**Speed** — words per minute, per-keystroke randomness, drift (speed wanders
between words), retype and backspace speed multipliers, and the countdown
before typing starts.

**Pauses** — min/max for sentence, paragraph and comma pauses, plus a
"thinking pause" that fires on a percentage of words.

**Mistakes** — typos per 100 characters, share of capitals mistyped, stray
capitals, and how often a misspell-prone word comes out wrong.

**Corrections** — the weights for noticed-immediately / at-end-of-word /
a-few-words-later, the share left uncorrected, and the hesitation before
fixing.

Presets: Careful writer, Average typist, Fast and sloppy, Hunt and peck,
Clean (no mistakes).

## Buttons worth knowing

- **Dry run** — simulates without typing and shows what would end up in the
  doc, plus mistake and backspace counts. Use it to tune rates before you
  touch a real document.
- **Estimate** — how long the run will take.
- **Random seed** — set it to any value to make a run exactly reproducible;
  leave blank for fresh randomness each time.

## Safety

- **Only type into windows titled** (default `Google Docs`): typing pauses
  whenever the focused window title does not contain that text, and resumes
  when you click back. Clear the field to allow any window.
- The tool never types into its own window.
- **Esc** stops a run immediately.

## Files

| File | Purpose |
| --- | --- |
| `typer_app.py` | GUI and the thread that replays keystrokes |
| `engine.py` | Timing, mistakes and correction planning |
| `theme.py` | Dark palette and ttk styling |
| `winkeys.py` | Windows `SendInput` keystroke injection |
| `settings.json` | Saved settings (created on first save) |

## Notes

- Windows only — `winkeys.py` uses the Win32 input API.
- Blank lines become real paragraph breaks (Enter). If a line begins with
  `- ` or `1. `, Docs will turn it into a list; that is Docs, not the typer.
- Very high WPM with a busy document can outrun the browser. If characters go
  missing, lower the speed.
