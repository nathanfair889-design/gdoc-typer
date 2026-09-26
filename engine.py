"""Human typing simulator.

Turns a block of text into a stream of timed keystrokes: characters,
backspaces and the pauses between them, complete with typos, capitalisation
slips and the corrections that follow.

The planner keeps two views of the world:
  * `text` - what should end up in the document
  * `doc`  - what has actually been typed so far
When a mistake is injected the two diverge; a correction backspaces the doc
back to the divergence point and retypes the intended slice. That one rule
handles every mistake type without special-casing the fixes.
"""

from __future__ import annotations

import random
import re
from dataclasses import asdict, dataclass, fields

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

    # corrections
    notice_min: float = 0.12
    notice_max: float = 0.50
    fix_immediate_pct: float = 45.0
    fix_word_end_pct: float = 35.0
    fix_delayed_pct: float = 20.0
    uncorrected_pct: float = 1.0

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
    ]),
    ("Corrections", [
        ("fix_immediate_pct", "Noticed immediately (weight)", 0, 100, 1),
        ("fix_word_end_pct", "Noticed at end of word (weight)", 0, 100, 1),
        ("fix_delayed_pct", "Noticed a few words later (weight)", 0, 100, 1),
        ("uncorrected_pct", "Left uncorrected (%)", 0, 100, 0.5),
        ("notice_min", "Pause before fixing, min (s)", 0, 10, 0.01),
        ("notice_max", "Pause before fixing, max (s)", 0, 10, 0.01),
    ]),
]

PRESETS = {
    "Careful writer": dict(wpm=48, jitter=0.26, typo_pct=1.0, cap_error_pct=3.0,
                           word_typo_pct=2.0, think_pct=5.0,
                           sentence_pause_min=0.8, sentence_pause_max=2.4,
                           fix_immediate_pct=70, fix_word_end_pct=25,
                           fix_delayed_pct=5, uncorrected_pct=0.0),
    "Average typist": dict(),
    "Fast and sloppy": dict(wpm=95, jitter=0.38, typo_pct=5.0, cap_error_pct=10.0,
                            stuck_shift_pct=1.5, word_typo_pct=14.0, think_pct=1.5,
                            sentence_pause_min=0.25, sentence_pause_max=0.9,
                            paragraph_pause_min=0.5, paragraph_pause_max=1.6,
                            fix_immediate_pct=30, fix_word_end_pct=35,
                            fix_delayed_pct=35, uncorrected_pct=4.0),
    "Hunt and peck": dict(wpm=26, jitter=0.55, drift=0.12, typo_pct=3.5,
                           cap_error_pct=14.0, word_typo_pct=8.0, think_pct=8.0,
                           think_min=1.0, think_max=4.0,
                           backspace_speed=0.8, retype_factor=1.0),
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
    mistakes: int = 0
    corrections: int = 0
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


def build_plan(text, cfg):
    """Return (events, stats). Each event is (delay_seconds, kind, value)."""
    rng = random.Random(cfg.seed.strip() or None)
    text = normalise(text)
    n = len(text)

    events = []
    doc = []
    stats = Stats()

    base = 60.0 / (max(cfg.wpm, 1.0) * 5.0)
    speed = 1.0
    extra = 0.0        # pause folded into the next keystroke
    pending = None     # mistake typed but not yet corrected
    i = 0

    def delay(factor=1.0):
        nonlocal extra
        d = base * speed * factor * rng.lognormvariate(0.0, max(cfg.jitter, 0.0)) + extra
        extra = 0.0
        return max(0.006, d)

    def emit_char(ch, factor=1.0):
        events.append((delay(factor), "char", ch))
        doc.append(ch)
        stats.keystrokes += 1

    def emit_back(first=False):
        nonlocal extra
        if first:
            d = rng.uniform(cfg.notice_min, cfg.notice_max)
            extra = 0.0
        else:
            d = delay(cfg.backspace_speed)
        events.append((d, "back", 1))
        if doc:
            doc.pop()
        stats.keystrokes += 1
        stats.backspaces += 1

    def word_end_from(idx):
        j = idx
        while j < n and (text[j].isalnum() or text[j] == "'"):
            j += 1
        return j

    def start_mistake():
        """Register a mistake starting at the current position."""
        nonlocal pending
        stats.mistakes += 1
        if rng.random() * 100.0 < cfg.uncorrected_pct:
            pending = None
            return False
        weights = [max(cfg.fix_immediate_pct, 0.0), max(cfg.fix_word_end_pct, 0.0),
                   max(cfg.fix_delayed_pct, 0.0)]
        if sum(weights) <= 0:
            weights = [1.0, 1.0, 1.0]
        mode = rng.choices(("immediate", "word", "delayed"), weights=weights)[0]
        pending = {"doc_start": len(doc), "text_start": i, "mode": mode, "lag": 0}
        return True

    def arm_lag():
        """Decide how many more characters get typed before the penny drops."""
        if pending is None:
            return
        if pending["mode"] == "immediate":
            pending["lag"] = 0 if rng.random() < 0.6 else rng.randint(1, 3)
        elif pending["mode"] == "word":
            pending["lag"] = max(0, word_end_from(i) - i)
        else:
            pending["lag"] = max(0, word_end_from(i) - i) + rng.randint(2, 14)
        if pending["lag"] <= 0:
            correct()

    def correct():
        nonlocal pending, extra
        if pending is None:
            return
        p, pending = pending, None
        wrong_len = len(doc) - p["doc_start"]
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
        """Advance through the intended text, tripping the fix when it is due."""
        nonlocal i
        i += count
        if pending is not None:
            pending["lag"] -= count
            if pending["lag"] <= 0:
                correct()

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        prev = text[i - 1] if i else ""
        prev2 = text[i - 2] if i > 1 else ""
        at_sentence_start = (i == 0 or prev == "\n"
                             or (prev == " " and prev2 in ".!?\"')"))
        at_word_start = ch.isalpha() and not (prev.isalpha() or prev == "'")

        # never carry a mistake across a line break
        if ch == "\n" and pending is not None:
            correct()

        # ---- pauses that belong before this keystroke ----
        if prev == "\n":
            extra += rng.uniform(cfg.paragraph_pause_min, cfg.paragraph_pause_max)
        elif prev == " " and prev2 in ".!?":
            extra += rng.uniform(cfg.sentence_pause_min, cfg.sentence_pause_max)
        elif prev in ",;:":
            extra += rng.uniform(cfg.comma_pause_min, cfg.comma_pause_max)
        if at_word_start and rng.random() * 100.0 < cfg.think_pct:
            extra += rng.uniform(cfg.think_min, cfg.think_max)

        # ---- speed drifts gently from word to word ----
        if at_word_start and cfg.drift > 0:
            speed = min(1.35, max(0.72, speed * rng.lognormvariate(0.0, cfg.drift)))

        if pending is None:
            # ---- whole-word misspelling ----
            if at_word_start and cfg.word_typo_pct > 0:
                m = WORD_RE.match(text, i)
                if (m and m.group(0).lower() in MISSPELLINGS
                        and rng.random() * 100.0 < cfg.word_typo_pct):
                    word = m.group(0)
                    wrong = _match_case(word, rng.choice(MISSPELLINGS[word.lower()]))
                    start_mistake()
                    for c in wrong:
                        emit_char(c)
                    i += len(word)
                    stats.chars += len(word)
                    arm_lag()
                    continue

            # ---- capitalisation slips ----
            if ch.isalpha() and ch.isupper() and rng.random() * 100.0 < cfg.cap_error_pct:
                start_mistake()
                if at_sentence_start and nxt.isalpha() and nxt.islower() and rng.random() < 0.4:
                    emit_char(ch)              # sticky shift: "THis"
                    emit_char(nxt.upper())
                    i += 2
                    stats.chars += 2
                else:
                    emit_char(ch.lower())      # missed shift: "this"
                    i += 1
                    stats.chars += 1
                arm_lag()
                continue

            if at_word_start and ch.islower() and rng.random() * 100.0 < cfg.stuck_shift_pct:
                start_mistake()
                emit_char(ch.upper())
                i += 1
                stats.chars += 1
                arm_lag()
                continue

            # ---- mechanical typos ----
            if ch.strip() and rng.random() * 100.0 < cfg.typo_pct:
                kinds = ["substitute", "insert", "double", "omit"]
                weights = [34, 30, 18, 8]
                if ch.isalnum() and nxt.isalnum():
                    kinds.append("transpose")
                    weights.append(18)
                kind = rng.choices(kinds, weights=weights)[0]
                start_mistake()
                if kind == "substitute":
                    emit_char(_wrong_key(ch, rng) or ch)
                    i += 1
                    stats.chars += 1
                elif kind == "insert":
                    emit_char(_wrong_key(ch, rng) or ch)   # stray letter, nothing consumed
                elif kind == "double":
                    emit_char(ch)
                    emit_char(ch, 0.6)
                    i += 1
                    stats.chars += 1
                elif kind == "omit":
                    i += 1
                    stats.chars += 1
                else:
                    emit_char(nxt)                          # transposition
                    emit_char(ch)
                    i += 2
                    stats.chars += 2
                arm_lag()
                continue

        # ---- ordinary keystroke ----
        emit_char(ch)
        stats.chars += 1
        consume(1)

    if pending is not None:
        correct()

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
