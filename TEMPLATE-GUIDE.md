# Filling the APUSH chapter-summary template

How to write your text so the autotyper lands every piece in the right cell.

## What the table actually looks like

66 rows, 129 cells, two columns. The left column is almost entirely **empty
spacer cells** — only the section numbers (`1`, `2`, `3`…) live there. All
your writing goes in the right column.

That is the one fact that makes the rest make sense: because every other
left-hand cell is an empty spacer you have to tab *through*, the gap between
two cells you actually fill is **two tabs, not one**.

A section (2 onwards) is always five rows:

| Row | Left cell | Right cell |
| --- | --- | --- |
| 1 | the section number | empty |
| 2 | empty | **Idea / Examples / Details** |
| 3 | empty | **Idea / Examples / Details** |
| 4 | empty | **Idea / Examples / Details** |
| 5 | empty | **What's the point?** |

## The two numbers you need

- **`(tab)(tab)`** — move from one Idea/Examples/Details cell to the next,
  and from the third one to *What's the point?*
- **`(tab)(tab)(tab)(tab)`** — move from *What's the point?* past the next
  section number into that section's first Idea cell

Tabbing *through* a cell never changes it, so the section numbers are safe.
Only typing changes a cell.

## The skeleton

Click into the **first Idea cell you want to fill**, then run this. Replace
the angle-bracket parts; leave everything else exactly as it is.

```
Idea: <your first idea>
Examples: <your examples>
Details: <your details>(tab)(tab)Idea: <your second idea>
Examples: <your examples>
Details: <your details>(tab)(tab)Idea: <your third idea>
Examples: <your examples>
Details: <your details>(tab)(tab)What's the point?: <your answer>
```

To carry straight on into the next section, add `(tab)(tab)(tab)(tab)` to
the end and paste the skeleton again.

Note what the line breaks are doing: **Enter inside a cell** is what puts
Idea, Examples and Details on three lines within the *same* cell. Only
`(tab)` moves to a different cell.

## Section 1 is not like the others

Section 1 has only **two** Idea cells instead of three, plus a spare blank
row after it. So for section 1:

- two Idea blocks, separated by `(tab)(tab)`
- then `(tab)(tab)` to *What's the point?*
- then **`(tab)(tab)(tab)(tab)(tab)(tab)`** — six — to reach section 2's
  first Idea cell

Everything from section 2 onwards follows the regular pattern above.

## Do one section per run

Do not try to fill all 66 rows in a single run. One section at a time means
that if a tab count is off, you fix one section instead of unpicking the
whole table. It also lets you check the result before committing to the
next one.

## Before you press start

1. **Duplicate the document** (File → Make a copy) and practise there.
2. In Docs, **Tools → Preferences**, uncheck *Automatically capitalise
   words* and *Automatically correct spelling*. Otherwise Google repairs the
   typos before the typist gets back to them.
3. Paste your text into the box and read the line underneath — it tells you
   how many cell breaks it found. **Count them against the skeleton.** Three
   Idea blocks in one section should show 6 cell breaks, or 10 if you also
   added the four to jump to the next section.
4. Hit **Dry run**, or **Watch it type** at 16x, and check it looks right.
5. Click into the first Idea cell, then **Ctrl+Alt+T**.
6. Hands off until it finishes. It stops itself if you touch anything;
   **Resume where it stopped** picks it back up.

## The one thing to check on your first test run

In Google Docs, pressing Tab moves to the next cell **and selects whatever
is already in it**, so the first thing typed replaces that cell's old
contents. The template ships with `Idea`, `Examples`, `Details` and
`What's the point?` already written in those cells.

That is why the skeleton has you type those labels yourself — so the cell
ends up reading correctly after the old text is replaced.

**Check this on your duplicate before trusting it.** Fill one section and
look at a cell:

- Reads `Idea: your text` — correct, carry on.
- Reads `Idea: your textIdea` or similar — Tab did not select, so the old
  prompt is still there. Delete the prompt text out of the cells you intend
  to fill before running it, and they will then be empty.

This is the only behaviour in the whole process I could not verify without
typing into your actual document, so spend the thirty seconds on it once.

## If it goes wrong

`Ctrl+Z` in Docs undoes in chunks and will walk the whole run back. That is
the real safety net, and it is why you test on a copy first.

Two things that are Docs, not the typer:

- A tab in the **last** cell of the table creates a **new row**. If you tab
  past the end, you will grow the table.
- The table must already exist. This fills cells; it does not draw tables.
