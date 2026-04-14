# <img src="../assets/domain_icons/subtitles.svg" width="28" height="28" style="vertical-align: middle;"> Subtitles

**Category:** Creative &amp; Media
**File format:** `.srt`
**Summary:** SRT subtitle files with timestamps, dialogue, and formatting
**Work environments released:** 5 / 6

SRT subtitle files use the [SubRip](https://en.wikipedia.org/wiki/SubRip) plain-text format. Each entry consists of a sequential index, a pair of start/end timestamps with millisecond precision, and one or more lines of caption text (dialogue, music cues, or sound effects). This domain tests an LLM's ability to manipulate timed text — splitting and merging entries, converting between subtitle formats, adjusting timestamps arithmetically, and annotating dialogue with metadata while preserving synchronization.

**Domain implementation:** [`domain_subtitles.py`](../domains/domain_subtitles.py)

---

## Evaluation

The subtitles domain evaluator parses SRT entries into structured records (index, start/end timestamps in milliseconds, content text) and scores reconstruction quality across four dimensions:

- **Entry coverage** — Are all original subtitle entries present? (Jaccard similarity on normalized text fingerprints)
- **Text accuracy** — Is dialogue text preserved correctly? (Hungarian matching with SequenceMatcher similarity)
- **Timing accuracy** — Are start/end timestamps correct? (Compares as `min/max` ratio, scaled by coverage factor)
- **Sequence score** — Is chronological ordering preserved? (SequenceMatcher on rank sequences, scaled by coverage factor)

**Score formula:** `0.20 × coverage + 0.40 × text + 0.25 × timing + 0.15 × sequence`

---

## Example Work Environment: `subtitles2`

**Document:** Ocean Circulation Documentary Subtitles
**Source:** [NASA Scientific Visualization Studio](https://svs.gsfc.nasa.gov/11056/) (Public Domain (NASA))
**Size:** 507 lines · 2,909 tokens

### Seed Document Excerpt (`ocean_documentary.srt`)

```srt
1
00:00:00,010 --> 00:00:03,040
Silence

2
00:00:03,060 --> 00:00:06,060
Silence

3
00:00:06,080 --> 00:00:09,110
Music

4
00:00:09,130 --> 00:00:12,170
Earth is the water

5
00:00:12,190 --> 00:00:15,200
planet. Although forty percent
of

6
00:00:15,220 --> 00:00:18,220
Earth's population lives within
or near

7
00:00:18,240 --> 00:00:21,240
coastal regions, the ocean
impacts

8
00:00:21,260 --> 00:00:24,260
people everywhere. 

9
00:00:24,280 --> 00:00:27,290
Music

10
00:00:27,310 --> 00:00:30,310
Most of Earth's water is stored
in the ocean -

11
00:00:30,330 --> 00:00:33,340
a driving force for weather

12
00:00:33,360 --> 00:00:36,370
and climate.

13
00:00:36,390 --> 00:00:39,400
Music
```
<sup>Showing 52 of 507 lines. The full file contains subtitle entries for an ocean circulation documentary covering thermohaline circulation, El Niño/La Niña, eddies, and hurricane intensification.</sup>

---

### Edit Tasks (8 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Topic Segmentation** | Split this documentary into separate SRT files by topic. Name them like `topic_circulation.srt` etc. Create a `topics_index.csv` with columns `order`, `filename`, and `topic_name` describing each segment. | Merge all the topic segment files into a single `ocean_documentary.srt` using `topics_index.csv` for ordering. Renumber all entries sequentially from 1. | split & merge, topic modeling, sorting |
| 2 | **Glossary Annotation** | Identify scientific/technical terms in the subtitle text. Add an inline `[DEF: ...]` annotation after the first occurrence of each term. Create `glossary.json` with term, definition, and first entry number. | Remove every inline `[DEF: ...]` annotation from the subtitles. Delete `glossary.json`. | context expansion, format knowledge |
| 3 | **TTML Conversion** | Convert to TTML format with region positioning. Place captions in the bottom center region by default, but move them to the top region when the caption mentions something visual at the bottom of the screen. | Convert this TTML to standard SRT format. Ignore all positioning and styling. | format knowledge, constraint satisfaction |
| 4 | **Speed Adjustment** | Adjust all timestamps for 1.25× playback speed. | Adjust timestamps from 1.25× back to normal 1× speed. | numerical reasoning |
| 5 | **PAL Frame Rate** | Convert subtitle timing from 24fps to 25fps for PAL broadcast. | Convert subtitle timing from 25fps back to 24fps film timing. | numerical reasoning |
| 6 | **Reading Normalization** | Normalize subtitle display times so each entry shows for at least 2 seconds. Save the pre-normalization timings to `timing_backup.json`. | Replace subtitle timings with those from `timing_backup.json`. Remove the backup file. | constraint satisfaction |
| 7 | **Educational Tiers** | Replace scientific jargon with kid-friendly equivalents and split subtitles into three SRT files by difficulty (`basic_tier.srt`, `intermediate_tier.srt`, `advanced_tier.srt`). Create `vocabulary_map.json` and `tier_assignments.csv`. | Merge the three tier files using `tier_assignments.csv` for ordering. Swap simplified terms back to scientific wording using `vocabulary_map.json`. Delete auxiliary files. | domain knowledge, split & merge, classification, sorting, referencing |
| 8 | **Cue Merging** | Merge consecutive identical non-speech captions (Music/Silence/Beeping) into single entries spanning the full time range. Renumber entries and save `cue_merge_map.json` listing each merge. | Expand each merged non-speech cue into its individual entries using `cue_merge_map.json`. Restore per-entry timestamps and renumber sequentially. Delete the map file. | constraint satisfaction, referencing |
