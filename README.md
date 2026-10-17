# Google Doc Typer

Types text into a Google Doc the way a person does: at a believable pace, with
pauses between sentences and paragraphs, and with mistakes it goes back and
fixes — capitalisation slips, stray inserted letters, transpositions, doubled
letters and common misspellings.

It sends **real Windows keystrokes** (`SendInput`), so Google Docs sees ordinary
typing. No browser extension, no automation framework, no `pip install` —
Python 3 with tkinter is all it needs.

## Running it

**Add it to the Start Menu** so you can just search for it:

```
powershell -ExecutionPolicy Bypass -File install_shortcut.ps1
```

Then press Start and type "Google Doc Typer". It launches without a console
window. Pass `-Uninstall` to the same script to remove the entry.

Otherwise, double-click **`Start Typer.bat`**, or:

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

## Revision passes

By default most mistakes are **not** fixed where you made them. The typist
writes one to three sentences, pauses as if re-reading, then arrows the caret
back to the earliest typo, fixes it, works forward through the rest, and
arrows back to the end to carry on. That is how most people actually write,
and it reads far more human than fixing everything at the caret.

Controlled on the **Revision** tab:

- **Left for a later revision pass (%)** — 0 fixes everything inline the
  moment you make it, 100 saves every mistake for a pass. Default 60.
- **Go back after this many sentences** — min/max, default 1 to 3.
- **Arrow-key speed**, and the pauses before going back and at each mistake.

Navigation is arrow keys only — never Ctrl+arrow word jumps, and never the
mouse. Arrow keys move exactly one character in every editor, so the planner
always knows where the caret is. Word jumping has editor-specific boundary
rules and would eventually land in the wrong place and scramble the document.

This assumes **you are typing at the end of your document** and do not touch
the keyboard or mouse mid-run. The caret is tracked by arithmetic, not read
back from the document, so moving the cursor yourself will corrupt the text.
Press Esc if you need to intervene.

Each mistake that is fixed *inline* gets noticed on its own schedule —
immediately, at the end of the word, or a few words later — then backspaced
out and retyped, with a short hesitation first. A small share can be left in
uncorrected, which is what real typing looks like.

## While it is running

**It stops the moment you touch anything.** Windows tags every synthetic
keystroke as injected; yours are not. A low-level hook watches for real key
presses and mouse clicks and aborts immediately, because the caret position
is tracked by arithmetic — one stray keypress and everything after it
lands in the wrong place. Better to stop than to scramble the document.

**Pause and resume.** Pause holds the run where it is. If a run stops early,
for any reason, **Resume where it stopped** re-plans the remaining text and
carries on, so a fifty-minute job survives an interruption.

**Hotkeys**, so you do not have to race the countdown:

| Key | Does |
| --- | --- |
| `Ctrl+Alt+T` | Start, or stop if already running |
| `Ctrl+Alt+P` | Pause / resume |
| `Esc` | Stop |

**Sessions.** Nobody writes two thousand words in one unbroken sitting, and
Docs timestamps every revision, so a single long burst looks like exactly
what it is. On the **Sessions** tab, set how long to type before stepping
away and how long to stay away. During a break the input watcher stands
down and your machine is yours; when it is over, click back into the
document and it picks up where it left off.

Breaks are only ever taken at a sentence boundary, never mid-word or
mid-revision-pass.

## While it is running

**It stops the moment you touch anything.** Windows tags every synthetic
keystroke as injected; yours are not. A low-level hook watches for real key
presses and mouse clicks and aborts immediately, because the caret position
is tracked by arithmetic — one stray keypress and everything after it
lands in the wrong place. Better to stop than to scramble the document.

**Pause and resume.** Pause holds the run where it is. If a run stops early,
for any reason, **Resume where it stopped** re-plans the remaining text and
carries on, so a fifty-minute job survives an interruption.

**Hotkeys**, so you do not have to race the countdown:

| Key | Does |
| --- | --- |
| `Ctrl+Alt+T` | Start, or stop if already running |
| `Ctrl+Alt+P` | Pause / resume |
| `Esc` | Stop |

**Sessions.** Nobody writes two thousand words in one unbroken sitting, and
Docs timestamps every revision, so a single long burst looks like exactly
what it is. On the **Sessions** tab, set how long to type before stepping
away and how long to stay away. During a break the input watcher stands
down and your machine is yours; when it is over, click back into the
document and it picks up where it left off.

Breaks are only ever taken at a sentence boundary, never mid-word or
mid-revision-pass.

## Learn how you actually write

Instead of guessing at the sliders, the app can measure them from a document
you really typed. Google Docs keeps an operational-transform log of every
edit ever made to a file. It is not in the public Drive API, but the editor's
own endpoint returns it:

```
https://docs.google.com/document/d/DOC_ID/revisions/load?start=1&end=5000&id=DOC_ID
```

1. Open that URL in a browser where you are signed in, with your doc's ID in
   both slots. Pick a long document you typed yourself; one that was mostly
   pasted in has no typing to learn from.
2. Save the response to a file. It begins with a `)]}'` guard prefix, which
   the parser strips.
3. In the app, click **Learn from my Google Doc history...** and pick it.

Replaying that log recovers not just the text but how it was written. From it
the app sets your speed, your sentence and comma pauses, your typo rate, how
much you fix on the spot versus going back later, and how long you hesitate
before fixing. It also extracts the words **you personally** get wrong and
merges them into the misspelling list, so the typist makes your mistakes
rather than generic ones.

The learned profile is written to `writing_profile.json` and reloaded on
startup. It is gitignored, being personal data.

**What this cannot recover:** Docs batches edits into roughly 200-400ms
groups, so average speed and pause structure are solid, but true
per-keystroke jitter is not in the data. If the endpoint rejects your range,
`end` is higher than your revision count — lower it, or read the exact
request off the Network tab while opening File > Version history.

## Settings

**Speed** — words per minute, per-keystroke randomness, drift (speed wanders
between words), retype and backspace speed multipliers, and the countdown
before typing starts.

**Pauses** — min/max for sentence, paragraph and comma pauses, plus a
"thinking pause" that fires on a percentage of words.

**Mistakes** — typos per 100 characters, share of capitals mistyped, stray
capitals, and how often a misspell-prone word comes out wrong.

**Revision** — how much is saved for a later pass, how often to go back,
and the arrow-key and pause timings for it.

**Sessions** — how long to type before a break, and how long breaks last.
0 disables them.

**Sessions** — how long to type before a break, and how long breaks last.
0 disables them.

**Inline fixes** — for mistakes *not* saved for a pass: the weights for
noticed-immediately / at-end-of-word / a-few-words-later, and the hesitation
before fixing.

Presets: Write then revise, Careful writer, Average typist, Fast and sloppy,
Hunt and peck, Fix everything inline, Clean (no mistakes).

## Buttons worth knowing

- **Dry run** — simulates without typing and shows what would end up in the
  doc, plus mistake and backspace counts. Use it to tune rates before you
  touch a real document.
- **Estimate** — how long the run will take.
- **Watch it type** — replays the plan into the app's own preview pane at
  1x, 4x, 16x or 64x. Same event stream the real run uses, so you see the
  actual rhythm — hesitations, backtracking, revision passes — without
  touching a document. Breaks are capped at two seconds so you can skip
  through them.
- **Random seed** — set it to any value to make a run exactly reproducible;
  leave blank for fresh randomness each time.

## Safety

- **Only type into windows titled** (default `Google Docs`): typing pauses
  whenever the focused window title does not contain that text, and resumes
  when you click back. Clear the field to allow any window.
- The tool never types into its own window.
- **Esc** stops a run immediately.

## API keys

If an API-backed feature is ever enabled, **the key never goes in this
repository.** It is read from, in order:

1. the `ANTHROPIC_API_KEY` environment variable
2. `%APPDATA%\GoogleDocTyper\api_key`

Both sit outside the project folder, so there is no file in here that could
be committed by mistake. That is deliberate: the protection is structural,
not a matter of remembering to ignore a file.

As a second layer, enable the pre-commit hook once per clone:

```
python install_hooks.py
```

It refuses any commit containing something shaped like an Anthropic,
OpenAI, AWS or GitHub credential. Verified both ways — it blocks a key and
lets ordinary code through. Undo with `git config --unset core.hooksPath`.

**If a key is ever exposed, revoke it in the Console first.** Rewriting git
history does not help once something has been pushed to a public repo; it is
scraped within minutes, and the only real fix is making the key useless.

## Files

| File | Purpose |
| --- | --- |
| `typer_app.py` | GUI and the thread that replays keystrokes |
| `engine.py` | Timing, mistakes and correction planning |
| `writing_profile.py` | Learns a profile from a Docs revision changelog |
| `theme.py` | Dark palette and ttk styling |
| `winkeys.py` | Windows `SendInput` keystroke injection |
| `apikey.py` | Reads the API key from outside the repo |
| `.githooks/pre-commit` | Refuses commits containing credentials |
| `install_hooks.py` | Enables that hook |
| `install_shortcut.ps1` | Adds a searchable Start Menu entry |
| `typer.ico` | App icon |
| `settings.json` | Saved settings (created on first save) |
| `writing_profile.json` | Your learned profile (gitignored) |

## Notes

- Windows only — `winkeys.py` uses the Win32 input API.
- Blank lines become real paragraph breaks (Enter). If a line begins with
  `- ` or `1. `, Docs will turn it into a list; that is Docs, not the typer.
- Very high WPM with a busy document can outrun the browser. If characters go
  missing, lower the speed.
