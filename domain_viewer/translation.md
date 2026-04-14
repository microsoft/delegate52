# <img src="../assets/domain_icons/translation.svg" width="28" height="28" style="vertical-align: middle;"> Translation

**Category:** Code &amp; Configuration
**File format:** `.po`
**Summary:** GNU gettext PO translation files with msgid/msgstr pairs, plurals, flags, and metadata
**Work environments released:** 6 / 6

GNU gettext PO files are the standard format for managing software translations in open-source projects. Each file contains a metadata header (language, plural forms, translator credits) followed by entries pairing source strings (`msgid`) with their translations (`msgstr`). Entries can carry flags (`fuzzy`, `c-format`), source file references (`#:`), extracted comments (`#.`), and translator comments (`#`). This domain tests an LLM's ability to manipulate structured multilingual data — splitting by source references, regrouping for review workflows, adapting locales, extracting cross-references, and converting between PO and documentation formats.

**Domain implementation:** [`domain_translation.py`](../domains/domain_translation.py)

---

## Evaluation

The translation domain evaluator parses PO files using the `polib` library into structured entries and scores reconstruction quality across six dimensions:

- **Entry coverage (15%)** — Are all original entries present? (Jaccard similarity on `(msgctxt, msgid)` fingerprints)
- **Translation accuracy (40%)** — Are translations preserved correctly? (SequenceMatcher on matched `msgstr` values, with plural form handling)
- **Flags score (10%)** — Are entry flags (`fuzzy`, `c-format`, etc.) preserved? (Jaccard on per-entry flag sets)
- **Metadata score (10%)** — Are header fields intact? (Important fields like Language, Plural-Forms, Content-Type weighted 0.7; secondary fields weighted 0.3)
- **Comments score (15%)** — Are source references, extracted comments, and translator comments preserved? (Jaccard and SequenceMatcher)
- **Sequence score (10%)** — Is the entry ordering correct? (SequenceMatcher on fingerprint ordering)

**Score formula:** `coverage² × (0.40×translation + 0.10×flags + 0.10×metadata + 0.15×comments + 0.10×sequence + 0.15×coverage)`

---

## Example Work Environment: `translation1`

**Document:** Newsboat RSS Reader French Translation
**Source:** [newsboat/newsboat](https://github.com/newsboat/newsboat/blob/master/po/fr.po) (MIT License)
**Size:** 333 lines · 3,009 tokens

### Seed Document Excerpt (`fr.po`)

```po
#
# Nicolas Martyanoff <khaelin@gmail.com>, 2007–2008.
# Sabrina Dubroca <sd@queasysnail.net>, 2013.
# rugie <fliehen@posteo.net>, 2017.
# Tonus <tonus1@gmail.com>, 2022.
msgid ""
msgstr ""
"Project-Id-Version: newsboat 2.6\n"
"Report-Msgid-Bugs-To: https://github.com/newsboat/newsboat/issues\n"
"POT-Creation-Date: 2025-12-09 18:25+0300\n"
"PO-Revision-Date: 2022-03-04 01:58+0000\n"
"Last-Translator: Tanguy Kerdoncuff <t.kerdonc@gmail.com>\n"
"Language-Team: Nicolas Martyanoff <khaelin@gmail.com>, Tanguy Kerdoncuff "
"<t.kerdonc@gmail.com>\n"
"Language: fr\n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=UTF-8\n"
"Content-Transfer-Encoding: 8bit\n"
"X-Generator: Lokalize 21.12.1\n"
"Plural-Forms: nplurals=2; plural=(n > 1);\n"

#: src/itemlistformaction.cpp:1158
#, c-format
msgid "1 day ago"
msgid_plural "%u days ago"
msgstr[0] "Il y a 1 jour"
msgstr[1] "Il y a %u jours"

#. i18n: This is printed out by --help before the path to the search history file
#: newsboat.cpp:162
#, fuzzy
msgid "search history"
msgstr "Rechercher : "

#. i18n: This string is related to the letters in parentheses in the
#. "Sort by (f)irsttag/..." and "Reverse Sort by
#. (f)irsttag/..." messages
#: src/feedlistformaction.cpp:130 src/feedlistformaction.cpp:173
#, fuzzy
msgid "ftaulsn"
msgstr "ptnida"

#: newsboat.cpp:50
#, fuzzy
msgid "export OPML 2.0 feed including tags to stdout"
msgstr "exporter le fil au format OPML vers la sortie stdout"

#: newsboat.cpp:57
#, fuzzy
msgid "read RSS feed URLs from <file>"
msgstr "lire les liens des fils RSS depuis le fichier <fichier_url>"
```
<sup>Showing 50 of 333 lines. The full PO file contains 60 entries (55 translated, 5 fuzzy, 1 plural) with c-format flags, source file references, and translator/extracted comments.</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Source-Based Split** | Split this PO file into separate .po files grouped by the #: source file references. Name each file after the source filename without directory path or .cpp extension. Each split file should have a minimal PO header with just Language, Content-Type, and Plural-Forms. Create a _manifest.txt containing the complete header block and entry sequence. | Merge all the per-source .po files into a single fr.po. Use the full header from _manifest.txt and arrange entries in the sequence listed in the manifest. Delete all split .po files and _manifest.txt. | split & merge, classification, format knowledge, sorting |
| 2 | **Review Workflow** | Tag every entry with a translator comment `# review-seq: N` numbering them in current file order. Then group the entries by review priority (fuzzy → c-format → simple) with section dividers. | Remove all # review-seq: translator comments and # === section dividers from the PO file. Sort entries by their review-seq numbers (ascending). Delete the section dividers. | classification, sorting, format knowledge |
| 3 | **Locale Adaptation** | Migrate this French (fr) PO file to Canadian French (fr_CA). Rename fr.po to fr_CA.po. Update the header: set Language to fr_CA, add X-Source-Locale: fr, and adapt terminology with FR-CA-ADAPTED comments storing original values plus an adaptation log. | Convert this Canadian French (fr_CA) PO file to standard European French (fr). Rename fr_CA.po to fr.po. Restore Language to fr, remove X-Source-Locale, and revert adaptations using stored original values. | domain knowledge, referencing |
| 4 | **Source Reference Extraction** | Extract all the #: source file reference lines from fr.po and consolidate them into a source_map.json cross-reference file. The JSON should map each msgid string to an array of source references. Remove #: lines from the PO file. | Reintegrate the source file references from source_map.json into fr.po. For each entry, insert the #: lines in standard PO position. Remove source_map.json when done. | referencing, format knowledge |
| 5 | **Release Merge Cleanup** | Prepare this PO file for a release merge. Resolve all fuzzy entries by removing the fuzzy flag. Prefix each extracted comment with [VERIFIED]. Sort entries by source path. Create release_notes.txt storing pre-cleanup state. | Remove the release merge changes. Re-add the fuzzy flag on each entry listed in release_notes.txt. Strip the [VERIFIED] prefix from all extracted comments. Restore original entry order. | sorting |
| 6 | **Documentation Export** | Convert fr.po into: 1) translations.md — a Markdown table with columns: No, Source, Translation, Status, Flags, Source Files. 2) po_metadata.txt — the file header and translator comments. | Reconstruct fr.po from the documentation files. Use translations.md for entry data and po_metadata.txt for the file header and translator comments. | format knowledge |
