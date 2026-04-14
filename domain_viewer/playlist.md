# <img src="../assets/domain_icons/playlist.svg" width="28" height="28" style="vertical-align: middle;"> Playlist

**Category:** Everyday
**File format:** `.xspf`
**Summary:** XSPF playlist files with track metadata, durations, and ordering
**Work environments released:** 0 / 6

XSPF media playlists use an XML-based format to describe ordered track lists with rich metadata — artist, title, album, year, label, rotation status, and DJ annotations. This domain tests an LLM's ability to parse, transform, and reconstruct structured playlist data including splitting by decade or genre, extracting show notes, and classifying tracks by artist type.

**Domain implementation:** [`domain_playlist.py`](../domains/domain_playlist.py)

---

## Evaluation

The playlist domain evaluator parses XSPF tracks into structured records and scores reconstruction quality across four dimensions:

- **Track coverage** — Are all original tracks present? (Jaccard similarity on title+creator fingerprints)
- **Track metadata accuracy** — Are album, year, label, rotation, local/request flags preserved? (Weighted field matching)
- **Annotation preservation** — Are DJ show notes and music trivia intact? (Levenshtein similarity)
- **Sequence score** — Is the original track ordering maintained?

**Score formula:** `coverage² × metadata × √((annotation + sequence) / 2)`
