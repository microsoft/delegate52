# <img src="../assets/domain_icons/musicsheet.svg" width="28" height="28" style="vertical-align: middle;"> Music Sheet

**Category:** Creative & Media
**File format:** `.ly`
**Summary:** LilyPond music notation with notes, rhythms, and score layout
**Work environments released:** 6 / 6

LilyPond music notation files (`.ly`) encode musical scores as structured plain text — pitches, durations, dynamics, lyrics, key/time signatures, and multi-voice staff layouts. This domain tests an LLM's ability to manipulate symbolic music: transposing pitches by intervals, splitting and merging voice parts across files, converting between absolute and relative notation, and restructuring score layouts — all while preserving the exact note sequences, rhythms, dynamics, and lyrics of the original composition.

**Domain implementation:** [`domain_musicsheet.py`](../domains/domain_musicsheet.py)

---

## Evaluation

The music sheet domain evaluator parses LilyPond content using the `ly` library and scores reconstruction quality across five dimensions:

- **Note sequence accuracy (35%)** — Are all pitches preserved? (Pitches converted to semitones for transposition-invariant comparison; per-voice matching handles reordered or renamed variables)
- **Rhythm accuracy (25%)** — Are note durations correct? (Compared as duration sequences with per-voice matching)
- **Dynamics (15%)** — Are dynamic markings (`\p`, `\mf`, `\cresc`, etc.) preserved in order?
- **Lyrics (15%)** — Are all lyric words present and in order? (Flattened across all lyric variables)
- **Structural elements (10%)** — Are key/time signatures, header fields (title, composer, arranger), and voice count preserved?

**Score formula:** `0.35 × note + 0.25 × rhythm + 0.15 × dynamics + 0.15 × lyrics + 0.10 × structural`

---

## Example Work Environment: `musicsheet1`

**Document:** Ave Verum TTBB Choral Score
**Source:** [MutopiaProject/MutopiaProject](https://github.com/MutopiaProject/MutopiaProject/blob/master/ftp/MozartWA/AveverumM/AveverumM.ly) (CC-BY-4.0 License)
**Size:** 300 lines · 3,309 tokens

### Seed Document Excerpt (`music_sheet.ly`)

```lilypond
#(set-global-staff-size 15.5) 

\version "2.18.0" 

global = { \key g \major \time 4/4 \tempo "Adagio" } 

TAAveVerum = %\relative g'' 
{ 
a'2\p d''4( fis'4) 
a'4-( gis'4-) g'2 
g'4-( b'4-) a'4-( g'4-) 
g'4-( fis'4-) fis'2 
e'2. e'4 
fis'4\< fis'4 g'4 g'4 
g'2-(\> fis'4-) fis'4 
e'1\! 
e'2. a'4 
a'4-( gis'4-) gis'2 
e'4-(\< gis'2-) b'4 
b'4-(\> a'4-) a'4 a'4 
d''1-(~\! 
d''4 cis''4-) b'4 a'4 
a'2-( gis'4-) gis'4 
a'1 
a'2.\p a'4 
a'4-( bes'4-) bes'2 
bes'4-(\mf\> d''4-) c''4-( bes'4-) 
bes'4-(\p a'4-) a'2 
g'2.\< g'4 
g'4-(\! bes'4-) a'4\> g'4 
g'2-(\< f'8[ e'8]-) f'4 
e'2\! r2 
fis'!2.\pp fis'4 
fis'4-(\cresc e'4-) d'4-( g'4-) 
g'2. g'4 
g'4-( fis'4-) e'4 a'4 
a'1~\( 
a'4 g'4\) a'4 b'4 
fis'2-(\> e'4.-) fis'8 
g'2\! g'2\p 
d''1-( 
d''2-(-) dis''2 
e''4 b'4 cis''4 d'' 
cis''4\> b'8[ a'8]-) d''4 g'\pp 
fis'2-( e'4.-) e'8 
d'1\fermata 
\bar "|." 
} 

TBAveVerum = { 
fis'2 fis'2 
e'2 e'2 
e'4-( g'4-) fis'4-( e'4-) 
e'4-( d'4-) d'2 
cis'2. cis'4 
```
<sup>Showing 50 of 300 lines. The full score is a four-part TTBB choral arrangement (Tenor I/II, Bass I/II) of Mozart's "Ave verum corpus" with Latin and German lyrics, dynamics markings, and header metadata.</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Transposition** | transpose this up a perfect fourth to C major | transpose this down a perfect fourth to G major | numerical reasoning |
| 2 | **Part Split** | I need to give each singer their own part. split this into 4 separate files: tenor1.ly, tenor2.ly, bass1.ly, bass2.ly. each should be a standalone file that compiles on its own. add the part name to the title (like "Ave verum - Tenor I"). delete music_sheet.ly | merge these part files into a single score called music_sheet.ly. put both tenors on one staff named 'boys' and both basses on one staff named 'men' (use voiceOne/voiceTwo with dynamicUp/dynamicDown). attach the latin and german lyrics to tenor 2, and the LB/DB variants to bass 1. use a ChoirStaff. delete the individual part files | split & merge, classification |
| 3 | **Relative Notation** | convert all the voice parts to use \relative notation | convert TAAveVerum and TBAveVerum from relative pitch notation to absolute | format knowledge |
| 4 | **Four-Staff Layout** | change the layout to use 4 separate staves, one per voice with the voice name labeled. attach lyrics under each staff | condense this to 2 staves - put tenor I and II on one staff using voiceOne/voiceTwo, same for the basses. name the staves 'boys' and 'men'. move the lyrics so latin and german verses are attached to TenorB, and the LB/DB variants to BassA. add dynamicUp/dynamicDown for the voice directions | format knowledge |
| 5 | **Dynamics Extraction** | pull the dynamic markings out of the note variables and into dedicated Dynamics context variables (TAAveVerumDyn, TBAveVerumDyn, BBAveVerumDyn) using spacer rests that follow the rhythm note-by-note. in the score, remove \dynamicUp and \dynamicDown from the voice contexts and add \new Dynamics contexts to render the extracted dynamics between staves | fold the dynamics from TAAveVerumDyn, TBAveVerumDyn, and BBAveVerumDyn back into the note variables. put \dynamicUp back in the TenorA and BassA voice contexts, \dynamicDown in TenorB and BassB. delete the three Dyn variables and the \new Dynamics lines from the score | format knowledge |
| 6 | **Lyric Tagging** | make the lyrics language-switchable using lilypond tags. wrap each lyrics variable with \tag #'latin or \tag #'german as appropriate. inside each lyricmode block, add a \set stanza with label lat. for Latin and deu. for German as the first element. in the score, prepend \tag #'latin to the two Latin lyrics context lines and \tag #'german to the two German ones -- both the ordering declarations and the \lyricsto attachments. add a comment before the ChoirStaff line: %% \keepWithTag #'latin for Latin-only, #'german for German-only | strip all \tag #'latin and \tag #'german wrappers from the lyrics variable definitions and from every lyrics context line in the score. remove the \set stanza lines from inside each lyricmode block. delete the keepWithTag comment above the ChoirStaff | string manipulation |
