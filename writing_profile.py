"""Learn a typing profile from a Google Docs revision changelog.

Google Docs keeps an operational-transform log of every edit ever made to a
document. It is not in the public Drive API, but the editor's own endpoint
returns it:

    https://docs.google.com/document/d/<ID>/revisions/load?start=1&end=<N>&id=<ID>

Open that in a browser where you are signed in, save the response, and feed
it to `analyse()`. The response begins with a `)]}'` guard prefix, which is
stripped here.

What comes back is a list of entries shaped like

    [op, timestamp_ms, user_id, revision, session_id, seq, ...]

where `op` is one of
    {"ty": "is",   "ibi": index, "s": "text"}   insert
    {"ty": "ds",   "si": start,  "ei": end}     delete (inclusive)
    {"ty": "mlti", "mts": [...]}                several of the above
    {"ty": "as",   ...}                         styling, ignored here
    {"ty": "rplc", "snapshot": [...]}           the document's starting state

Replaying those gives back not just the text but *how it was written*: how
fast, where the pauses fell, which words came out wrong, and whether they
were fixed on the spot or later.

A caveat worth keeping in mind: Docs batches mutations into roughly 200-400ms
groups, so this recovers average speed and pause structure, not true
per-keystroke timing.
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter

WORD = re.compile(r"^[A-Za-z][A-Za-z']*$")

# an insert longer than this was almost certainly a paste, not typing
PASTE_CHARS = 12
# a gap longer than this means they walked away; not typing time
IDLE_SECONDS = 5.0
# how far the caret must move for a fix to count as "went back to it"
AWAY_CHARS = 3


# --------------------------------------------------------------------------
# reading the changelog
# --------------------------------------------------------------------------

def _flatten(op):
    """Yield the primitive insert/delete ops inside a mutation."""
    if not isinstance(op, dict):
        return
    kind = op.get("ty")
    if kind == "mlti":
        for sub in op.get("mts", []):
            yield from _flatten(sub)
    elif kind in ("is", "ds"):
        yield op
    elif kind == "rplc":
        for sub in op.get("snapshot", []):
            yield from _flatten(sub)


def load_events(path):
    """Replay a changelog file into [timestamp, kind, position, text] rows.

    Deletes record the text they removed, which the log itself does not
    store - it only gives indices, so the document has to be rebuilt as we
    go to find out what was actually deleted.
    """
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    start = raw.find("{")
    if start < 0:
        raise ValueError("No JSON object found - is this a saved changelog?")
    data = json.loads(raw[start:])
    if "changelog" not in data:
        raise ValueError("No 'changelog' key - this is not a revisions/load response.")

    doc, events = [], []
    for entry in data["changelog"]:
        if not entry:
            continue
        op, timestamp = entry[0], (entry[1] if len(entry) > 1 else 0)
        initial = isinstance(op, dict) and op.get("ty") == "rplc"
        for prim in _flatten(op):
            if prim["ty"] == "is":
                at = max(0, prim["ibi"] - 1)
                text = prim.get("s", "")
                doc[at:at] = list(text)
                if not initial:
                    events.append([timestamp, "ins", at, text])
            else:
                si, ei = max(0, prim["si"] - 1), max(0, prim["ei"] - 1)
                removed = "".join(doc[si:ei + 1])
                del doc[si:ei + 1]
                if not initial:
                    events.append([timestamp, "del", si, removed])
    return events


def _fix_runs(events):
    """Group consecutive deletes into one backspacing run, with its retype."""
    runs, i = [], 0
    while i < len(events):
        if events[i][1] != "del":
            i += 1
            continue
        first = i
        deleted = ""
        while i < len(events) and events[i][1] == "del":
            deleted = events[i][3] + deleted      # backspacing runs right to left
            i += 1
        position = events[i - 1][2]

        typed = ""
        j = i
        while (j < len(events) and events[j][1] == "ins"
               and abs(events[j][2] - position) <= len(typed) + 2
               and len(typed) < 40):
            typed += events[j][3]
            j += 1

        prev = next((e for e in reversed(events[:first]) if e[1] == "ins"), None)
        runs.append({
            "deleted": deleted,
            "typed": typed,
            "keystrokes": i - first,
            "jump": abs(position - (prev[2] + len(prev[3]))) if prev else 0,
            "wait": (events[first][0] - prev[0]) / 1000.0 if prev else None,
        })
    return runs


def _levenshtein(a, b):
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


# --------------------------------------------------------------------------
# turning events into a profile
# --------------------------------------------------------------------------

def analyse(path):
    """Read a changelog and return a profile dict."""
    events = load_events(path)
    inserts = [e for e in events if e[1] == "ins"]
    if len(inserts) < 20:
        raise ValueError("Not enough typing in this document to learn from "
                         f"(only {len(inserts)} edits). Try a longer one you "
                         "typed out yourself.")

    profile = {"source": path, "edits": len(events), "inserts": len(inserts)}

    # ---- speed, ignoring pastes and time spent away ----
    typed = [e for e in inserts if len(e[3]) <= PASTE_CHARS]
    chars = sum(len(e[3]) for e in typed)
    active = 0.0
    for a, b in zip(typed, typed[1:]):
        gap = (b[0] - a[0]) / 1000.0
        if 0 < gap < IDLE_SECONDS:
            active += gap
    profile["typed_chars"] = chars
    profile["active_minutes"] = round(active / 60.0, 2)
    if active > 30:
        profile["wpm"] = round(chars / 5.0 / (active / 60.0), 1)

    # ---- pauses, split by what was typed just before ----
    after_sentence, after_comma, ordinary = [], [], []
    for a, b in zip(typed, typed[1:]):
        gap = (b[0] - a[0]) / 1000.0
        if not 0 < gap < 30:
            continue
        tail = a[3].rstrip()[-1:] if a[3].strip() else ""
        if tail in ".!?":
            after_sentence.append(gap)
        elif tail in ",;:":
            after_comma.append(gap)
        elif gap < IDLE_SECONDS:
            ordinary.append(gap)
    for name, series in (("sentence_pause", after_sentence),
                         ("comma_pause", after_comma)):
        if len(series) >= 3:
            profile[name + "_min"] = round(min(statistics.median(series), 10.0), 2)
            profile[name + "_max"] = round(
                min(statistics.quantiles(series, n=10)[-1], 20.0), 2)

    # ---- corrections ----
    runs = _fix_runs(events)
    profile["fixes"] = len(runs)
    if runs:
        away = [r for r in runs if r["jump"] > AWAY_CHARS]
        profile["revise_pct"] = round(100.0 * len(away) / len(runs), 1)
        if away:
            profile["median_jump_chars"] = int(statistics.median(
                r["jump"] for r in away))

        waits = [r["wait"] for r in runs if r["wait"] and 0 < r["wait"] < 60]
        if len(waits) >= 3:
            quick = sorted(waits)[:max(1, len(waits) // 2)]
            profile["notice_min"] = round(min(quick), 2)
            profile["notice_max"] = round(statistics.median(waits), 2)
            profile["reread_min"] = round(statistics.median(waits), 2)
            profile["reread_max"] = round(
                min(statistics.quantiles(waits, n=10)[-1], 25.0), 2)

        if chars:
            profile["typo_pct"] = round(min(100.0 * len(runs) / chars, 25.0), 2)

    # ---- the personal misspelling list ----
    pairs = Counter()
    for run in runs:
        wrong, right = run["deleted"].strip(), run["typed"].strip()
        if not (WORD.match(wrong) and WORD.match(right)):
            continue
        if len(right) < 4 or wrong.lower() == right.lower():
            continue
        distance = _levenshtein(wrong.lower(), right.lower())
        # close enough to be a slip, not a change of mind
        if 0 < distance <= max(2, len(right) // 3):
            pairs[(right.lower(), wrong)] += 1

    misspellings = {}
    for (right, wrong), _count in pairs.most_common():
        misspellings.setdefault(right, [])
        if wrong not in misspellings[right]:
            misspellings[right].append(wrong)
    profile["misspellings"] = misspellings

    # capitalisation slips: one-character fixes that only changed case
    case_fixes = sum(1 for r in runs
                     if r["deleted"] and r["typed"]
                     and r["deleted"].strip().lower() == r["typed"].strip().lower()
                     and r["deleted"].strip() != r["typed"].strip())
    if case_fixes and runs:
        profile["cap_error_pct"] = round(
            min(100.0 * case_fixes / len(runs) * 2, 100.0), 1)

    return profile


def apply_to_config(profile, cfg):
    """Copy what was learned onto a Config. Returns the field names set."""
    applied = []
    direct = ("wpm", "typo_pct", "cap_error_pct", "revise_pct",
              "sentence_pause_min", "sentence_pause_max",
              "comma_pause_min", "comma_pause_max",
              "notice_min", "notice_max", "reread_min", "reread_max")
    for name in direct:
        if name in profile and hasattr(cfg, name):
            setattr(cfg, name, float(profile[name]))
            applied.append(name)
    return applied


def summary(profile):
    bits = []
    if "wpm" in profile:
        bits.append(f"{profile['wpm']:.0f} wpm")
    if "typo_pct" in profile:
        bits.append(f"{profile['typo_pct']:.1f}% typo rate")
    if "revise_pct" in profile:
        jump = profile.get("median_jump_chars")
        bits.append(f"{profile['revise_pct']:.0f}% fixed later"
                    + (f" (~{jump} chars back)" if jump else ""))
    if "notice_max" in profile:
        bits.append(f"{profile['notice_max']:.1f}s before fixing")
    words = len(profile.get("misspellings", {}))
    if words:
        bits.append(f"{words} personal misspellings")
    return ", ".join(bits) or "nothing usable found"
