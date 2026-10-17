"""Generate plausible *earlier drafts* of sentences.

Every other mistake in this project is mechanical - a wrong key, a dropped
letter. Real writing also contains changes of mind: you write a sentence,
carry on, re-read it, and replace it with a better one. That is what this
module feeds the engine.

The direction matters and it is backwards from every "rewriter" tool out
there. We already have the finished sentence. What is missing is the rougher
thing that came *before* it - the draft a writer would later improve into
the text we have. So these backends degrade a sentence rather than polish
one.

Two backends, same interface:

    RuleBased  - deterministic downgrades, no dependencies, works offline
    Claude     - asks the model for an earlier draft, needs an API key

Both return {sentence_start_index: earlier_draft_text}.
"""

from __future__ import annotations

import json
import random
import re

SENTENCE_RE = re.compile(r"[^.!?\n]*[.!?]+|[^.!?\n]+", re.MULTILINE)

# Finished writing tends to be more precise than a first draft. Going the
# other way: swap the precise word for the loose one a draft would have.
DOWNGRADES = [
    (r"\bdemonstrates?\b", "shows"), (r"\bindicates?\b", "shows"),
    (r"\billustrates?\b", "shows"), (r"\breveals?\b", "shows"),
    (r"\butili[sz]e[sd]?\b", "use"), (r"\bobtain(ed|s)?\b", "get"),
    (r"\bsufficient\b", "enough"), (r"\badditional\b", "more"),
    (r"\battempt(ed|s)?\b", "try"), (r"\brequire[sd]?\b", "need"),
    (r"\bassist(ed|s)?\b", "help"), (r"\bpurchase[sd]?\b", "buy"),
    (r"\bindividuals\b", "people"), (r"\bnumerous\b", "a lot of"),
    (r"\bapproximately\b", "about"), (r"\bprior to\b", "before"),
    (r"\bsubsequently\b", "later"), (r"\bin order to\b", "to"),
    (r"\bdue to the fact that\b", "because"), (r"\bwith regard to\b", "about"),
    (r"\bin the event that\b", "if"), (r"\bat this point in time\b", "now"),
    (r"\bthe majority of\b", "most of"), (r"\bconsequently\b", "so"),
    (r"\bnevertheless\b", "but"), (r"\bfurthermore\b", "also"),
    (r"\bsignificant\b", "big"), (r"\bextremely\b", "very"),
]

# Qualifiers and connectives a draft often lacks and an edit adds.
INTENSIFIERS = [r"\bsignificantly\s+", r"\bsubstantially\s+",
                r"\bparticularly\s+", r"\bespecially\s+", r"\bnotably\s+",
                r"\bclearly\s+", r"\barguably\s+", r"\beffectively\s+",
                r"\bgenerally\s+", r"\brelatively\s+"]

OPENERS = [r"^However,\s+", r"^Moreover,\s+", r"^Furthermore,\s+",
           r"^In addition,\s+", r"^Therefore,\s+", r"^Consequently,\s+",
           r"^Nevertheless,\s+", r"^Additionally,\s+", r"^Ultimately,\s+"]

CONTRACTIONS = [(r"\bit is\b", "it's"), (r"\bdo not\b", "don't"),
                (r"\bcannot\b", "can't"), (r"\bthat is\b", "that's"),
                (r"\bthere is\b", "there's"), (r"\bwill not\b", "won't"),
                (r"\bis not\b", "isn't"), (r"\bthey are\b", "they're"),
                (r"\bwe are\b", "we're"), (r"\bdoes not\b", "doesn't")]


def find_sentences(text, min_words=6):
    """Return [(start_index, sentence_text)] for sentences worth rewriting."""
    out = []
    for match in SENTENCE_RE.finditer(text):
        raw = match.group(0)
        stripped = raw.strip()
        if len(stripped.split()) < min_words:
            continue
        start = match.start() + (len(raw) - len(raw.lstrip()))
        out.append((start, stripped))
    return out


class RuleBased:
    """Downgrade a sentence with deterministic edits. No dependencies."""

    name = "Rule-based (offline, free)"

    def __init__(self, seed=None):
        self.rng = random.Random(seed)

    def _downgrade(self, sentence):
        text = sentence
        changed = False

        for pattern in OPENERS:
            new = re.sub(pattern, "", text)
            if new != text:
                text = new[:1].upper() + new[1:]
                changed = True
                break

        for pattern in INTENSIFIERS:
            new = re.sub(pattern, "", text, count=1)
            if new != text:
                text, changed = new, True
                break

        swaps = self.rng.sample(DOWNGRADES, len(DOWNGRADES))
        for pattern, replacement in swaps:
            new = re.sub(pattern, replacement, text, count=1, flags=re.IGNORECASE)
            if new != text:
                text, changed = new, True
                break

        if not changed or self.rng.random() < 0.3:
            for pattern, replacement in CONTRACTIONS:
                new = re.sub(pattern, replacement, text, count=1)
                if new != text:
                    text, changed = new, True
                    break

        return text if changed and text != sentence else None

    def drafts(self, text, wanted, rng=None):
        picks = _choose(find_sentences(text), wanted, rng or self.rng)
        out = {}
        for start, sentence in picks:
            draft = self._downgrade(sentence)
            if draft:
                out[start] = (draft, len(sentence))
        return out


class Claude:
    """Ask Claude for a rougher earlier draft of each sentence."""

    name = "Claude API"

    PROMPT = (
        "You are helping simulate how a document was written. For each "
        "numbered sentence below, write the ROUGHER EARLIER DRAFT that a "
        "writer would plausibly have typed first and later improved into "
        "the given sentence.\n\n"
        "The draft should be clearly worse but still natural:\n"
        "- looser word choice, vaguer verbs\n"
        "- missing a qualifier or transition the final version has\n"
        "- slightly clumsier phrasing or word order\n"
        "- similar length, same basic meaning\n"
        "- NOT a summary, NOT a different claim, NOT with spelling errors\n\n"
        "Reply with only a JSON object mapping each number to its draft, "
        'like {"1": "...", "2": "..."}. No other text.'
    )

    def __init__(self, api_key, model="claude-opus-5-5", effort="low"):
        self.api_key = api_key
        self.model = model
        self.effort = effort
        self.last_usage = None

    def drafts(self, text, wanted, rng=None):
        import anthropic                       # imported lazily and on purpose

        picks = _choose(find_sentences(text), wanted, rng or random.Random())
        if not picks:
            return {}

        numbered = "\n".join(f"{n}. {s}" for n, (_i, s) in enumerate(picks, 1))
        client = anthropic.Anthropic(api_key=self.api_key)
        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            output_config={"effort": self.effort},
            system=self.PROMPT,
            messages=[{"role": "user", "content": numbered}],
        )
        self.last_usage = response.usage

        reply = "".join(b.text for b in response.content if b.type == "text")
        drafts = _parse_json_object(reply)

        out = {}
        for n, (start, sentence) in enumerate(picks, 1):
            draft = (drafts.get(str(n)) or "").strip()
            # a draft that is identical, empty or wildly the wrong size is junk
            if draft and draft != sentence and 0.4 < len(draft) / len(sentence) < 2.2:
                out[start] = (draft, len(sentence))
        return out

    def estimate_cost(self):
        """Dollars for the last call, or None. Rates per million tokens."""
        rates = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0),
                 "claude-haiku-5-5": (0.10, 0.50)}
        if not self.last_usage or self.model not in rates:
            return None
        inp, outp = rates[self.model]
        return (self.last_usage.input_tokens * inp / 1e6
                + self.last_usage.output_tokens * outp / 1e6)


def _choose(sentences, wanted, rng):
    if wanted <= 0 or not sentences:
        return []
    if wanted >= len(sentences):
        return sentences
    return sorted(rng.sample(sentences, wanted), key=lambda s: s[0])


def _parse_json_object(reply):
    """Pull the JSON object out of a reply, tolerating stray prose or fences."""
    reply = reply.strip()
    if reply.startswith("```"):
        reply = re.sub(r"^```[a-z]*\n?|```$", "", reply, flags=re.MULTILINE).strip()
    try:
        value = json.loads(reply)
        return value if isinstance(value, dict) else {}
    except ValueError:
        pass
    start, end = reply.find("{"), reply.rfind("}")
    if 0 <= start < end:
        try:
            value = json.loads(reply[start:end + 1])
            return value if isinstance(value, dict) else {}
        except ValueError:
            pass
    return {}
