"""Human typing simulator.

Turns a block of text into a stream of timed keystrokes: characters,
backspaces, arrow keys and the pauses between them, complete with typos,
capitalisation slips and the corrections that follow.

The planner keeps three pieces of state:
  * `text`  - what should end up in the document
  * `doc`   - what has actually been typed so far
  * `caret` - where the cursor sits inside `doc`
A mistake makes `doc` diverge from `text`. It can be fixed two ways:

  inline     backspace from the caret to the mistake and retype, all
             within a few characters of making it.
  revision   leave it in, keep writing, then after a sentence or three
             arrow the caret back to each mistake, fix it, and arrow back
             to the end to carry on. This is how most people actually
             write, and it is what makes the output read as human.

Caret movement is arrow keys only, never word jumps or the mouse. Arrow
keys move exactly one character in every editor, so the planner always
knows precisely where the cursor is; Ctrl+arrow word-jumping has
editor-specific boundary rules and would eventually land in the wrong
place and corrupt the document.
"""

from __future__ import annotations

import random
import re
from dataclasses import asdict, dataclass, field, fields

# --------------------------------------------------------------------------
# keyboard geometry - used to pick a plausible "wrong" key
# --------------------------------------------------------------------------

_ROWS = [
    ("`1234567890-=", 0.0),
    ("qwertyuiop[]\\", 0.6),
    ("asdfghjkl;'", 0.9),
    ("zxcvbnm,./", 1.3),
]


def _build_neighbours():
    pos = {}
    for r, (row, offset) in enumerate(_ROWS):
        for c, ch in enumerate(row):
            pos[ch] = (r, c + offset)
    table = {}
    for ch, (row, x) in pos.items():
        near = [other for other, (r2, x2) in pos.items()
                if other != ch and abs(r2 - row) <= 1 and abs(x2 - x) <= 1.05]
        table[ch] = near
    return table


NEIGHBOURS = _build_neighbours()

# Words people reliably fumble, and how they fumble them.
MISSPELLINGS = {
    "the": ["teh", "hte"], "and": ["adn", "nad"], "that": ["taht"],
    "this": ["tihs"], "with": ["wiht"], "from": ["form"], "just": ["jsut"],
    "they": ["tehy"], "them": ["tehm"], "then": ["hten"], "you": ["yuo"],
    "your": ["yoru"], "know": ["knwo"], "time": ["tiem"], "what": ["waht"],
    "when": ["wehn"], "work": ["wrok"], "want": ["watn"], "about": ["abuot"],
    "would": ["woudl"], "could": ["coudl"], "should": ["shoudl"],
    "because": ["becuase", "becasue"], "people": ["peopel"],
    "really": ["realy"], "through": ["thorugh", "throught"],
    "receive": ["recieve"], "definitely": ["definately", "definatly"],
    "separate": ["seperate"], "their": ["thier"], "believe": ["beleive"],
    "necessary": ["neccessary", "necesary"], "occurred": ["occured"],
    "accommodate": ["accomodate"], "business": ["buisness"],
    "government": ["goverment"], "environment": ["enviroment"],
    "beginning": ["begining"], "calendar": ["calender"],
    "committee": ["commitee"], "embarrass": ["embarass"],
    "existence": ["existance"], "grammar": ["grammer"],
    "immediately": ["immediatly"], "independent": ["independant"],
    "maintenance": ["maintenence"], "occasion": ["occassion"],
    "privilege": ["priviledge"], "recommend": ["recomend"],
    "restaurant": ["restaraunt"], "rhythm": ["rythm"],
    "schedule": ["schedual"], "successful": ["succesful"],
    "tomorrow": ["tommorow"], "until": ["untill"], "writing": ["writting"],
    "argument": ["arguement"], "column": ["colum"], "familiar": ["familier"],
    "february": ["febuary"], "foreign": ["foriegn"], "height": ["hieght"],
    "knowledge": ["knowlege"], "library": ["libary"], "original": ["orignal"],
    "parallel": ["paralel"], "personnel": ["personel"],
    "possession": ["posession"], "questionnaire": ["questionaire"],
    "sincerely": ["sincerly"], "surprise": ["suprise"],
    "themselves": ["themselfs"], "thorough": ["thourough"],
    "truly": ["truely"], "vacuum": ["vaccum"],
}


# Swapped for your own list once a writing profile is learned. Your real
# slips beat any generic list, but the built-ins still cover words your
# sample never happened to contain.
ACTIVE_MISSPELLINGS = dict(MISSPELLINGS)


def use_misspellings(personal, replace=False):
    """Merge a learned misspelling list in (or replace the built-ins)."""
    global ACTIVE_MISSPELLINGS
    ACTIVE_MISSPELLINGS = dict(personal) if replace else {**MISSPELLINGS, **personal}
    return len(ACTIVE_MISSPELLINGS)


def reset_misspellings():
    global ACTIVE_MISSPELLINGS
    ACTIVE_MISSPELLINGS = dict(MISSPELLINGS)

# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------

@dataclass
class Config:
    # speed
    wpm: float = 62.0
    jitter: float = 0.30
    drift: float = 0.06
    retype_factor: float = 0.85
    backspace_speed: float = 0.45
    start_delay: float = 5.0

    # pauses (seconds)
    sentence_pause_min: float = 0.55
    sentence_pause_max: float = 1.80
    paragraph_pause_min: float = 1.00
    paragraph_pause_max: float = 3.00
    comma_pause_min: float = 0.15
    comma_pause_max: float = 0.55
    think_pct: float = 3.0
    think_min: float = 0.70
    think_max: float = 2.50

    # mistakes (percentages)
    typo_pct: float = 2.2
    cap_error_pct: float = 6.0
    stuck_shift_pct: float = 0.6
    word_typo_pct: float = 6.0

    # inline corrections
    notice_min: float = 0.12
    notice_max: float = 0.50
    fix_immediate_pct: float = 45.0
    fix_word_end_pct: float = 35.0
    fix_delayed_pct: float = 20.0
    uncorrected_pct: float = 1.0

    # revision passes - go back later and clean up
    revise_pct: float = 60.0
    revise_every_min: float = 1.0
    revise_every_max: float = 3.0
    arrow_speed: float = 0.30
    reread_min: float = 0.60
    reread_max: float = 2.20
    spot_min: float = 0.20
    spot_max: float = 0.80

    # sessions - write in bursts with real gaps, the way people actually do
    session_minutes: float = 0.0        # 0 disables breaks entirely
    break_minutes_min: float = 5.0
    break_minutes_max: float = 25.0

    # safety
    window_filter: str = "Google Docs"
    seed: str = ""


TEXT_FIELDS = ("window_filter", "seed")

NUMERIC_SPEC = [
    ("Speed", [
        ("wpm", "Typing speed (words per minute)", 5, 250, 1),
        ("jitter", "Per-keystroke randomness (0-1.5)", 0, 1.5, 0.01),
        ("drift", "Speed drift between words (0-0.3)", 0, 0.3, 0.01),
        ("retype_factor", "Retype speed (x normal)", 0.2, 2.0, 0.05),
        ("backspace_speed", "Backspace speed (x normal)", 0.05, 2.0, 0.05),
        ("start_delay", "Countdown before typing (s)", 0, 60, 1),
    ]),
    ("Pauses", [
        ("sentence_pause_min", "After a sentence, min (s)", 0, 20, 0.05),
        ("sentence_pause_max", "After a sentence, max (s)", 0, 30, 0.05),
        ("paragraph_pause_min", "After a paragraph, min (s)", 0, 30, 0.05),
        ("paragraph_pause_max", "After a paragraph, max (s)", 0, 60, 0.05),
        ("comma_pause_min", "After a comma, min (s)", 0, 10, 0.05),
        ("comma_pause_max", "After a comma, max (s)", 0, 10, 0.05),
        ("think_pct", "Thinking pause chance per word (%)", 0, 100, 0.5),
        ("think_min", "Thinking pause, min (s)", 0, 30, 0.05),
        ("think_max", "Thinking pause, max (s)", 0, 60, 0.05),
    ]),
    ("Mistakes", [
        ("typo_pct", "Typos per 100 characters (%)", 0, 25, 0.1),
        ("cap_error_pct", "Capital letters mistyped (%)", 0, 100, 0.5),
        ("stuck_shift_pct", "Stray capitals on lowercase words (%)", 0, 20, 0.1),
        ("word_typo_pct", "Misspell-prone words got wrong (%)", 0, 100, 0.5),
        ("uncorrected_pct", "Never fixed at all (%)", 0, 100, 0.5),
    ]),
    ("Revision", [
        ("revise_pct", "Left for a later revision pass (%)", 0, 100, 1),
        ("revise_every_min", "Go back after this many sentences, min", 1, 30, 1),
        ("revise_every_max", "Go back after this many sentences, max", 1, 30, 1),
        ("arrow_speed", "Arrow-key speed (x normal)", 0.02, 2.0, 0.01),
        ("reread_min", "Pause before going back, min (s)", 0, 20, 0.05),
        ("reread_max", "Pause before going back, max (s)", 0, 30, 0.05),
        ("spot_min", "Pause at each mistake, min (s)", 0, 10, 0.05),
        ("spot_max", "Pause at each mistake, max (s)", 0, 10, 0.05),
    ]),
    ("Sessions", [
        ("session_minutes", "Type this long before a break (min, 0 = never)", 0, 240, 1),
        ("break_minutes_min", "Break length, min (minutes)", 0, 600, 1),
        ("break_minutes_max", "Break length, max (minutes)", 0, 600, 1),
    ]),
    ("Inline fixes", [
        ("fix_immediate_pct", "Noticed immediately (weight)", 0, 100, 1),
        ("fix_word_end_pct", "Noticed at end of word (weight)", 0, 100, 1),
        ("fix_delayed_pct", "Noticed a few words later (weight)", 0, 100, 1),
        ("notice_min", "Pause before fixing, min (s)", 0, 10, 0.01),
        ("notice_max", "Pause before fixing, max (s)", 0, 10, 0.01),
    ]),
]

PRESETS = {
    "Write then revise": dict(revise_pct=85, revise_every_min=1,
                               revise_every_max=3, typo_pct=3.0,
                               cap_error_pct=8.0, word_typo_pct=10.0,
                               uncorrected_pct=1.0),
    "Careful writer": dict(wpm=48, jitter=0.26, typo_pct=1.0, cap_error_pct=3.0,
                            word_typo_pct=2.0, think_pct=5.0, revise_pct=25,
                            sentence_pause_min=0.8, sentence_pause_max=2.4,
                            fix_immediate_pct=70, fix_word_end_pct=25,
                            fix_delayed_pct=5, uncorrected_pct=0.0),
    "Average typist": dict(),
    "Fast and sloppy": dict(wpm=95, jitter=0.38, typo_pct=5.0, cap_error_pct=10.0,
                             stuck_shift_pct=1.5, word_typo_pct=14.0,
                             think_pct=1.5, revise_pct=75,
                             revise_every_min=2, revise_every_max=5,
                             sentence_pause_min=0.25, sentence_pause_max=0.9,
                             paragraph_pause_min=0.5, paragraph_pause_max=1.6,
                             uncorrected_pct=4.0),
    "Hunt and peck": dict(wpm=26, jitter=0.55, drift=0.12, typo_pct=3.5,
                           cap_error_pct=14.0, word_typo_pct=8.0, think_pct=8.0,
                           think_min=1.0, think_max=4.0, revise_pct=20,
                           backspace_speed=0.8, retype_factor=1.0,
                           arrow_speed=0.6),
    "Fix everything inline": dict(revise_pct=0.0),
    "Clean, no mistakes": dict(typo_pct=0.0, cap_error_pct=0.0,
                                stuck_shift_pct=0.0, word_typo_pct=0.0),
}


def config_to_dict(cfg):
    return asdict(cfg)


def config_from_dict(data):
    cfg = Config()
    known = {f.name for f in fields(Config)}
    for key, value in (data or {}).items():
        if key not in known:
            continue
        try:
            setattr(cfg, key, str(value) if key in TEXT_FIELDS else float(value))
        except (TypeError, ValueError):
            pass
    return cfg


# --------------------------------------------------------------------------
# planning
# --------------------------------------------------------------------------

WORD_RE = re.compile(r"[A-Za-z][A-Za-z']*")


@dataclass
class Stats:
    chars: int = 0
    keystrokes: int = 0
    backspaces: int = 0
    arrows: int = 0
    mistakes: int = 0
    corrections: int = 0
    revisions: int = 0
    breaks: int = 0
    duration: float = 0.0
    result_text: str = ""


def _match_case(template, word):
    if template.isupper() and len(template) > 1:
        return word.upper()
    if template[:1].isupper():
        return word[:1].upper() + word[1:]
    return word


def _wrong_key(ch, rng):
    options = NEIGHBOURS.get(ch.lower())
    if not options:
        return None
    if ch.isalpha():
        options = [o for o in options if o.isalpha()] or options
    pick = rng.choice(options)
    return pick.upper() if ch.isupper() else pick


def normalise(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _pick_mistake(text, i, cfg, rng, at_sentence_start, at_word_start):
    """Decide whether a mistake happens here, and what it looks like.

    Returns None, or a dict describing it:
      wrong    - the characters actually typed
      consumed - how many characters of `text` they stand in for
      correct  - what should have been there (text[i:i + consumed])
    """
    ch = text[i]
    nxt = text[i + 1] if i + 1 < len(text) else ""

    # whole-word misspelling
    if at_word_start and cfg.word_typo_pct > 0:
        m = WORD_RE.match(text, i)
        if (m and m.group(0).lower() in ACTIVE_MISSPELLINGS
                and rng.random() * 100.0 < cfg.word_typo_pct):
            word = m.group(0)
            wrong = _match_case(word,
                                rng.choice(ACTIVE_MISSPELLINGS[word.lower()]))
            return {"wrong": wrong, "consumed": len(word), "correct": word,
                    "kind": "misspelling"}

    # capitalisation slips
    if ch.isalpha() and ch.isupper() and rng.random() * 100.0 < cfg.cap_error_pct:
        if at_sentence_start and nxt.isalpha() and nxt.islower() and rng.random() < 0.4:
            return {"wrong": ch + nxt.upper(), "consumed": 2,
                    "correct": ch + nxt, "kind": "sticky-shift"}
        return {"wrong": ch.lower(), "consumed": 1, "correct": ch,
                "kind": "missed-shift"}

    if at_word_start and ch.islower() and rng.random() * 100.0 < cfg.stuck_shift_pct:
        return {"wrong": ch.upper(), "consumed": 1, "correct": ch,
                "kind": "stray-caps"}

    # mechanical typos
    if ch.strip() and rng.random() * 100.0 < cfg.typo_pct:
        kinds = ["substitute", "insert", "double", "omit"]
        weights = [34, 30, 18, 8]
        if ch.isalnum() and nxt.isalnum():
            kinds.append("transpose")
            weights.append(18)
        kind = rng.choices(kinds, weights=weights)[0]
        if kind == "substitute":
            return {"wrong": _wrong_key(ch, rng) or ch, "consumed": 1,
                    "correct": ch, "kind": kind}
        if kind == "insert":
            # a stray letter that stands in for nothing at all
            return {"wrong": _wrong_key(ch, rng) or ch, "consumed": 0,
                    "correct": "", "kind": kind}
        if kind == "double":
            return {"wrong": ch + ch, "consumed": 1, "correct": ch, "kind": kind}
        if kind == "omit":
            return {"wrong": "", "consumed": 1, "correct": ch, "kind": kind}
        return {"wrong": nxt + ch, "consumed": 2, "correct": ch + nxt,
                "kind": kind}

    return None


def build_plan(text, cfg):
    """Return (events, stats). Each event is (delay_seconds, kind, value)."""
    rng = random.Random(cfg.seed.strip() or None)
    text = normalise(text)
    n = len(text)

    events = []
    doc = []           # characters in the document
    caret = 0          # where the cursor sits inside doc
    stats = Stats()

    base = 60.0 / (max(cfg.wpm, 1.0) * 5.0)
    speed = 1.0
    extra = 0.0        # pause folded into the next keystroke
    pending = None     # an inline mistake, typed but not yet fixed
    deferred = []      # mistakes waiting for a revision pass
    i = 0

    sentences_since_pass = 0
    ended_sentence = False
    session_end = (cfg.session_minutes * 60.0) if cfg.session_minutes > 0 else None
    revise_lo = int(max(1, cfg.revise_every_min))
    revise_hi = int(max(revise_lo, cfg.revise_every_max))
    next_pass_at = rng.randint(revise_lo, revise_hi)

    def delay(factor=1.0):
        nonlocal extra
        d = base * speed * factor * rng.lognormvariate(0.0, max(cfg.jitter, 0.0)) + extra
        extra = 0.0
        return max(0.006, d)

    def emit_char(ch, factor=1.0):
        nonlocal caret
        events.append((delay(factor), "char", ch, i))
        doc.insert(caret, ch)
        caret += 1
        stats.keystrokes += 1

    def emit_back(first=False):
        nonlocal caret, extra
        if first:
            d = rng.uniform(cfg.notice_min, cfg.notice_max)
            extra = 0.0
        else:
            d = delay(cfg.backspace_speed)
        events.append((d, "back", 1, i))
        if caret > 0:
            doc.pop(caret - 1)
            caret -= 1
        stats.keystrokes += 1
        stats.backspaces += 1

    def move_caret_to(target):
        """Walk the cursor to an absolute position with arrow keys."""
        nonlocal caret
        target = max(0, min(len(doc), target))
        step = "left" if target < caret else "right"
        for _ in range(abs(target - caret)):
            events.append((delay(cfg.arrow_speed), step, 1, i))
        stats.keystrokes += abs(target - caret)
        stats.arrows += abs(target - caret)
        caret = target

    def word_end_from(idx):
        j = idx
        while j < n and (text[j].isalnum() or text[j] == "'"):
            j += 1
        return j

    # ---- inline fixing: backspace from the caret, right where we are ----
    def arm_lag():
        if pending is None:
            return
        if pending["mode"] == "immediate":
            pending["lag"] = 0 if rng.random() < 0.6 else rng.randint(1, 3)
        elif pending["mode"] == "word":
            pending["lag"] = max(0, word_end_from(i) - i)
        else:
            pending["lag"] = max(0, word_end_from(i) - i) + rng.randint(2, 14)
        if pending["lag"] <= 0:
            fix_inline()

    def fix_inline():
        nonlocal pending, extra
        if pending is None:
            return
        p, pending = pending, None
        wrong_len = caret - p["doc_start"]
        intended = text[p["text_start"]:i]
        if wrong_len <= 0 and not intended:
            return
        for k in range(wrong_len):
            emit_back(first=(k == 0))
        for k, ch in enumerate(intended):
            if k == 0:
                extra = rng.uniform(0.04, 0.18)
            emit_char(ch, cfg.retype_factor)
        stats.corrections += 1

    def consume(count=1):
        nonlocal i
        i += count
        if pending is not None:
            pending["lag"] -= count
            if pending["lag"] <= 0:
                fix_inline()

    # ---- revision pass: arrow back through everything left behind ----
    def revision_pass():
        nonlocal extra
        if not deferred:
            return
        queue = sorted(deferred, key=lambda e: e["start"])
        deferred.clear()
        extra += rng.uniform(cfg.reread_min, cfg.reread_max)

        for index, err in enumerate(queue):
            move_caret_to(err["start"] + err["wrong_len"])
            extra += rng.uniform(cfg.spot_min, cfg.spot_max)
            for _ in range(err["wrong_len"]):
                emit_back()
            for ch in err["correct"]:
                emit_char(ch, cfg.retype_factor)
            stats.corrections += 1
            # fixing this one shifts everything that comes after it
            shift = len(err["correct"]) - err["wrong_len"]
            if shift:
                for later in queue[index + 1:]:
                    later["start"] += shift

        move_caret_to(len(doc))
        stats.revisions += 1

    # ---- main loop ----
    while i < n:
        ch = text[i]
        prev = text[i - 1] if i else ""
        prev2 = text[i - 2] if i > 1 else ""
        at_sentence_start = (i == 0 or prev == "\n"
                             or (prev == " " and prev2 in ".!?\"')"))
        at_word_start = ch.isalpha() and not (prev.isalpha() or prev == "'")

        # never carry an unfixed mistake across a line break
        if ch == "\n":
            if pending is not None:
                fix_inline()
            if deferred:
                revision_pass()

        # ---- pauses that belong before this keystroke ----
        if prev == "\n":
            extra += rng.uniform(cfg.paragraph_pause_min, cfg.paragraph_pause_max)
        elif prev == " " and prev2 in ".!?":
            extra += rng.uniform(cfg.sentence_pause_min, cfg.sentence_pause_max)
        elif prev in ",;:":
            extra += rng.uniform(cfg.comma_pause_min, cfg.comma_pause_max)
        if at_word_start and rng.random() * 100.0 < cfg.think_pct:
            extra += rng.uniform(cfg.think_min, cfg.think_max)

        if at_word_start and cfg.drift > 0:
            speed = min(1.35, max(0.72, speed * rng.lognormvariate(0.0, cfg.drift)))

        # ---- mistakes ----
        mistake = None
        if pending is None:
            mistake = _pick_mistake(text, i, cfg, rng, at_sentence_start,
                                    at_word_start)

        if mistake is not None:
            stats.mistakes += 1
            if rng.random() * 100.0 < cfg.uncorrected_pct:
                mode = "never"
            elif rng.random() * 100.0 < cfg.revise_pct:
                mode = "defer"
            else:
                mode = "inline"

            start = caret
            if mode == "inline":
                pending = {"doc_start": start, "text_start": i,
                           "mode": rng.choices(
                               ("immediate", "word", "delayed"),
                               weights=[max(cfg.fix_immediate_pct, 0.0),
                                        max(cfg.fix_word_end_pct, 0.0),
                                        max(cfg.fix_delayed_pct, 0.0)]
                               or None)[0],
                           "lag": 0}
            for c in mistake["wrong"]:
                emit_char(c)
            i += mistake["consumed"]
            stats.chars += mistake["consumed"]

            if mode == "defer":
                deferred.append({"start": start,
                                 "wrong_len": len(mistake["wrong"]),
                                 "correct": mistake["correct"]})
            elif mode == "inline":
                arm_lag()
            continue

        # ---- ordinary keystroke ----
        emit_char(ch)
        stats.chars += 1

        if ch in ".!?":
            ended_sentence = True
        elif ended_sentence and ch in " \n":
            ended_sentence = False
            sentences_since_pass += 1
            if (sentences_since_pass >= next_pass_at and deferred
                    and pending is None):
                revision_pass()
                sentences_since_pass = 0
                next_pass_at = rng.randint(revise_lo, revise_hi)

            # walk away for a while, then come back to it
            if session_end is not None and pending is None and not deferred:
                elapsed = sum(e[0] for e in events)
                if elapsed >= session_end:
                    gap = rng.uniform(cfg.break_minutes_min,
                                      cfg.break_minutes_max) * 60.0
                    events.append((max(gap, 1.0), "break", None, i))
                    stats.breaks += 1
                    session_end = elapsed + gap + cfg.session_minutes * 60.0

        consume(1)

    # ---- tidy up anything still outstanding ----
    if pending is not None:
        fix_inline()
    if deferred:
        revision_pass()

    stats.duration = sum(e[0] for e in events)
    stats.result_text = "".join(doc)
    return events, stats


def format_duration(seconds):
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"
