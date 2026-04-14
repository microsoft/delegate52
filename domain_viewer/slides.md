# <img src="../assets/domain_icons/slides.svg" width="28" height="28" style="vertical-align: middle;"> Slides

**Category:** Creative &amp; Media
**File format:** `.md`
**Summary:** Markdown presentations with slides, bullet points, and speaker notes
**Work environments released:** 1 / 6

Presentation slide files use a Markdown-based format with YAML frontmatter, `## ` slide headers, bullet points, image/chart placeholders, and position annotations `[@(x,y)]` for layout control. Each element can carry an optional font size (e.g., `[@(3,7) | 24pt]`). This domain tests an LLM's ability to restructure, split, merge, reorder, and reformat presentation content — preserving slide structure, element ordering, image placement, and spatial coordinates across transformations.

**Domain implementation:** [`domain_slides.py`](../domains/domain_slides.py)

---

## Evaluation

The slides domain evaluator parses presentations into structured records (slides, titles, bullets, images, charts, speaker notes, positions) and scores reconstruction quality across six dimensions:

- **Slide coverage (20%)** — Are all original slides present? (Jaccard overlap of normalized slide titles)
- **Slide order (10%)** — Are slides in the correct sequence? (SequenceMatcher on title sequences)
- **Content matching (40%)** — Are text elements preserved? (Hungarian matching on title/bullet/subtitle/table/notes elements, weighted by text similarity, type match, position, and indent level)
- **Image score (7.5%)** — Are all image references present? (Jaccard overlap of image filenames)
- **Image order (7.5%)** — Are images in the correct sequence? (SequenceMatcher on image filename sequences)
- **Position accuracy (15%)** — Are `[@(x,y)]` coordinates correct for matched elements? (L1 distance with tolerance)

**Score formula:** `0.20 × coverage + 0.10 × order + 0.40 × content + 0.075 × image + 0.075 × image_order + 0.15 × position`

---

## Example Work Environment: `slides1`

**Document:** LLM Reading & Writing Interfaces Slides
**Source:** Original content (author-owned)
**Size:** 419 lines · 4,680 tokens

### Seed Document Excerpt (`presentation.md`)

```markdown
---
title: "Untitled Presentation"
total_slides: 44
---

## Reading and Writing Interfaces with LLMs [@(2,1)]

- Philippe Laban [@(2,4)]
- Cambridge LTL Seminar – May 2025 [@(2,4)]
[IMAGE: image_ZUAB.png @(5,5)]


## Part 1:LLMs Get Lost in Multi-TurnConversation [@(3,0)]

[IMAGE: image_SQDX.jpg @(1,3)]

- In collaboration with [@(3,3)]
[IMAGE: image_BYHO.jpeg @(6,4)]

[IMAGE: image_YIPQ.jpg @(10,4)]

- Jennifer Neville [@(10,6)]
- Hiroaki Hayashi [@(6,6)]
- * AI-Generated Illustrative Image [@(0,7)]

## Slide 3

- Motivation (circa September 2024) [@(0,0)]
- PL Benchmarks are saturated. LLMs get 90+ on HumanEval, but they're still no-good. We did harder benchmarks. [@(3,2)]
[IMAGE: image_BYHO.jpeg @(1,2)]

- What is HumanEval? [@(7,4)]
- Show me… [@(7,4)]
[IMAGE: image_ZUAB.png @(10,4)]

- Hiroaki Hayashi [@(1,4)]
- "PL expert" [@(1,4)]
- Philippe [@(10,6)]
- "PL noob" [@(10,6)]

## Motivation (Circa September 2024) [@(2,0)]

[IMAGE: image_WVHI.png @(0,1)]

- Sharded Instruction Equivalent (6 shards) [@(7,2)]
- Sample: HumanEval/3 [@(0,2)]
```
<sup>Showing 50 of 419 lines. The full presentation contains 44 slides covering multi-turn conversation, creative writing evaluation, and writing quality reward models, with position-annotated elements, images, and charts throughout.</sup>

---

### Edit Tasks (9 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Gradual Build** | Gradually build up some slides with transitions: slide 4 (left then right), slide 6 (introduce each bullet point in a new slide), slide 20 (first the question, then on the next slide the question and the answer), slide 22 (first just the research question, then full slide with image, paper title, etc.). | For all slides that build up gradually, remove the intermediate slides and keep only the final completed slide. | constraint satisfaction |
| 2 | **Section Swap** | I want to swap the order in the presentation: start with creative writing and then go to lost in conv. | I want to swap the order in the presentation: start with lost in conv and then go to creative writing. | sorting |
| 3 | **Multi-Deck Split** | Split into separate slide decks, one per paper: Lost in Conv, InkSync, Art or Artifice, LAMP, and WQRM. Name them like "presentation_[PAPER].md". Put slides that don't fit neatly into a paper deck into "transitions.md", so every slide ends up in exactly one file. Each paper deck should have its own Intro and Questions? slide so it works standalone. | Combine all decks into a single presentation titled "Reading and Writing Interfaces with LLMs". Order: Lost in Conv, InkSync, Art or Artifice, LAMP, WQRM. Use the transition slides between papers. Only one intro slide and one Questions? slide at the end. | split & merge, classification, topic modeling, sorting |
| 4 | **Appendix Move** | Pick 5 slides of technical/detailed content and move them to an appendix section after the Questions slide. | Move the appendix slides back into the main flow in their proper positions. Delete the appendix section header. | topic modeling |
| 5 | **Widescreen Scale** | Scale all x positions by 1.5x for 16:9 widescreen (@(4,2) becomes @(6,2)). | Scale all x positions by dividing by 1.5 for 4:3 aspect ratio (@(6,2) becomes @(4,2)). | numerical reasoning |
| 6 | **Two-Column Layout** | For slides with more than 5 bullets, reorganize into two columns. Odd bullets (1st, 3rd, 5th...) go to left column (x=1), even bullets (2nd, 4th, 6th...) to right column (x=7). | Convert two-column slides to single column at x=1. Interleave left and right bullets in order: left1, right1, left2, right2... | numerical reasoning, constraint satisfaction |
| 7 | **Descriptive Titles** | Slides 3, 8, 9, 16, 29, and 44 have placeholder 'Slide N' titles — give each a short descriptive title based on its content. Also disambiguate duplicate titles: 'Why do models get lost in conversation?' (3x), 'Evaluating Fiction Writing' (2x), 'Art or Artifice - Setup' (2x), 'Writing Quality Reward Models' (3x) by adding a short parenthetical to make each unique. Update total_slides in frontmatter if needed. | For slides 3, 8, 9, 16, 29, and 44 (counting from top), replace the title with 'Slide N' where N is the slide number. Strip any parenthetical at the end of a title. | context expansion, string manipulation |
| 8 | **Split Dense Slides** | Split any slide with more than 6 bullet points into consecutive slides. The first keeps its title; continuations get the same title with ' (cont.)' appended. Distribute bullets in order (first 6 stay, rest go to continuations). Images stay with the bullet directly above them. Update total_slides in frontmatter. At the end of the file add a comment: `<!-- SPLITS: 'Title A' into 2 slides, 'Title B' into 3 slides -->`. | Combine any consecutive slides where the title ends in '(cont.)' with the preceding slide sharing the same base title. Concatenate all bullets and images in order under the base title. Use the SPLITS comment at the bottom to verify merge counts, then delete it. Update total_slides in frontmatter. | constraint satisfaction, split & merge |
| 9 | **Deck Rebalance** | Merge each slide whose body contains only [IMAGE:] lines (no bullets) into the preceding slide by appending its images after that slide's content and removing its ## heading. After merges, if any slide has more than 8 content lines (bullets + [IMAGE:] lines), split it into two roughly equal slides — keep the title on both, append ' [b]' to the second. Update total_slides in frontmatter. Add a comment at the end: `<!-- RECUT: merged 'Old Title' into 'Preceding Title'; split 'Title' into 2; ... -->` | Using the RECUT comment at the end of the file: for each merge listed, extract the appended images into their own slide using the title from the comment, placed right after the slide they were merged into. For each split, fold the '[b]' slide's content into the base-titled slide. Delete the RECUT comment and update total_slides. | constraint satisfaction, split & merge |
