# <img src="../assets/domain_icons/screenplay.svg" width="28" height="28" style="vertical-align: middle;"> Screenplay

**Category:** Creative & Media
**File format:** `.txt`
**Summary:** Play and screenplay scripts with dialogue, stage directions, and scenes
**Work environments released:** 6 / 6

Plain-text play scripts use a structured format with `# CHARACTERS:`, `# SCENE:`, and `# DIALOGUE:` sections. Characters are listed with descriptions, the scene section provides setting and staging details, and dialogue lines follow a `CHARACTER: text` format with parenthetical stage directions inline or on standalone lines. This domain tests an LLM's ability to manipulate dramatic text — converting between screenplay formats, reorganizing narrative structure, extracting and reintegrating embedded annotations, and reformatting dialogue into tabular or annotated forms.

**Domain implementation:** [`domain_screenplay.py`](../domains/domain_screenplay.py)

---

## Evaluation

The screenplay domain evaluator parses plays into structured records (characters, dialogue sequences, stage directions) and scores reconstruction quality across four dimensions:

- **Dialogue sequence** — Are all dialogue lines present in the correct order? (Uses SequenceMatcher on `(character, text_prefix)` tuples)
- **Character coverage** — Are all characters listed? (Jaccard similarity on character name sets)
- **Stage directions** — Are standalone stage directions preserved? (SequenceMatcher on normalized direction text)
- **Text similarity** — Is the raw text faithfully reconstructed? (SequenceMatcher on normalized full text)

**Score formula:** `0.45 × dialogue + 0.20 × character + 0.20 × direction + 0.15 × text`

---

## Example Work Environment: `screenplay1`

**Document:** The Outside (Glaspell)
**Source:** [Project Gutenberg #10623](https://www.gutenberg.org/ebooks/10623) (Public Domain)
**Size:** 231 lines · 5,512 tokens

### Seed Document Excerpt (`screenplay.txt`)

```text
# CHARACTERS:

- CAPTAIN: of 'The Bars' Life-Saving Station
- BRADFORD: a Life-Saver
- TONY: a Portuguese Life-Saver
- MRS PATRICK: who lives in the abandoned Station
- ALLIE MAYO: who works for her

# SCENE: 

A room in a house which was once a life-saving station. Since ceasing to be that
it has taken on no other character, except that of a place which no one cares
either to preserve or change. It is painted the life-saving grey, but has not
the life-saving freshness. This is one end of what was the big boat room, and at
the ceiling is seen a part of the frame work from which the boat once swung.
About two thirds of the back wall is open, because of the big sliding door, of
the type of barn door, and through this open door are seen the sand dunes, and
beyond them the woods.

# DIALOGUE:

CAPTAIN: I'll take this now, boys.

BRADFORD: No need for anybody to take it, Capt'n. He was dead when we picked
him up.

CAPTAIN: Dannie Sears was dead when we picked him up. But we brought him back.
I'll go on awhile.

(The two men who have been bending over the body rise, stretch to relax, and
come into the room.)

BRADFORD: (pushing back his arms and putting his hands on his chest) Work,—tryin
to put life in the dead.

CAPTAIN: Where'd you find him, Joe?

BRADFORD: In front of this house. Not forty feet out.

CAPTAIN: What'd you bring him up here for?

(He speaks in an abstracted way, as if the working part of his mind is on
something else, and in the muffled voice of one bending over.)

BRADFORD: (with a sheepish little laugh) Force of habit, I guess. We brought so
many of 'em back up here, (looks around the room) And then it was kind of
unfriendly down where he was—the wind spittin' the sea onto you till he'd have
no way of knowin' he was ashore.

TONY: Lucky I was not sooner or later as I walk by from my watch.
```
<sup>Showing 50 of 231 lines. The full play contains 5 characters, approximately 90 dialogue lines, and numerous stage directions spanning the complete one-act play.</sup>

---

### Edit Tasks (4 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Fountain Conversion** | Convert this plain-text play to Fountain format in `screenplay.fountain`. Use standard Fountain conventions. Turn the character list into action lines introducing each character at first appearance. Rename TONY to ANTONIO throughout. Delete screenplay.txt. | Convert this Fountain screenplay to plain-text play format in `screenplay.txt` with sections: `# CHARACTERS:` (as `- NAME: description`), `# SCENE:` (description paragraph), `# DIALOGUE:` (as `CHARACTER: text`, standalone stage directions on own lines). Rename ANTONIO to TONY throughout. Delete screenplay.fountain. | format knowledge, context expansion, string manipulation |
| 2 | **Flashback Reorganization** | Reorganize this play into a non-linear flashback structure. Divide the dialogue into 4 movements based on character entrances/exits. Restructure in reverse order: MOVEMENT 4 first, then insert `[EARLIER THAT DAY]`, then MOVEMENTS 1–3. Add headers with descriptive titles. Split BRADFORD into BRADFORD (movements 1–2) and PETE (movement 3). | Restore this play to chronological order. Remove all movement headers and the `[EARLIER THAT DAY]` marker. Merge PETE and BRADFORD into a single character named BRADFORD. | sorting, classification, context expansion |
| 3 | **Stage Direction Extraction** | Extract all stage directions (standalone parentheticals and inline ones) into a `# STAGE DIRECTIONS:` section after `# SCENE:`. Number each with position markers referencing surrounding dialogue. Remove all parentheticals from `# DIALOGUE:`. | Reintegrate all stage directions from `# STAGE DIRECTIONS:` back into `# DIALOGUE:` using each direction's position markers. Remove the `# STAGE DIRECTIONS:` section. | referencing, format knowledge |
| 4 | **Rehearsal Reformat** | Reformat into a director's rehearsal working copy: break `# SCENE:` into sentence-by-sentence bullets under `# SCENE BREAKDOWN:` with category tags. Replace `# DIALOGUE:` with `# BLOCKING CHART:` as pipe-delimited rows with columns for number, character, line, and blocking. | Merge `# SCENE BREAKDOWN:` bullets into a single `# SCENE:` paragraph, stripping category tags. Rebuild `# DIALOGUE:` from `# BLOCKING CHART:`: rows with WHO become dialogue lines, rows with only BLOCKING become stage directions. | classification, format knowledge |
