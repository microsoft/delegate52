# <img src="../assets/domain_icons/treebank.svg" width="28" height="28" style="vertical-align: middle;"> Treebank

**Category:** Structured Records
**File format:** `.conllu`
**Summary:** CoNLL-U treebank files with POS tags, morphology, and dependency annotations
**Work environments released:** 6 / 6

CoNLL-U treebank files use the [Universal Dependencies](https://universaldependencies.org/) annotation format. Each sentence is a block of tab-separated token lines with ten columns — ID, form, lemma, UPOS, XPOS, morphological features, head, dependency relation, enhanced dependencies, and miscellaneous annotations — preceded by metadata comments (sentence ID, raw text, speaker). This domain tests an LLM's ability to manipulate richly annotated linguistic data — splitting by speaker, swapping tag systems, extracting and reintegrating annotation layers, and converting between vertical and horizontal formats.

**Domain implementation:** [`domain_treebank.py`](../domains/domain_treebank.py)

---

## Evaluation

The treebank domain evaluator parses CoNLL-U content into structured sentence/token records using the `conllu` Python package and scores reconstruction quality with a multiplicative model: completeness × quality.

- **Completeness** — Fraction of reference tokens that have an aligned partner in the generated output (uses Hungarian algorithm via `scipy.optimize.linear_sum_assignment` for sentence and token matching)
- **Quality** — Weighted sum of field accuracies over matched tokens:
  - Form (10%), Lemma (8%), UPOS (15%), XPOS (7%), Features (10%), Head (20%), Deprel (15%), Metadata (10%), Sequence ordering (5%)

**Score formula:** `completeness × quality`

---

## Example Work Environment: `treebank1`

**Document:** Court Hearing Treebank
**Source:** [UD_English-GUM](https://github.com/UniversalDependencies/UD_English-GUM) (CC BY-SA License)
**Size:** 220 lines · 3,913 tokens

### Seed Document Excerpt (`court_hearing.conllu`)

```conllu
# newdoc id = GUM_court_carpet
# meta::author = Santa Barbara Corpus of Spoken American English (ed. John W. Du Bois)
# meta::dateCollected = 2020-08-05
# meta::dateCreated = 2000-01-01
# meta::dateModified = 2000-01-01
# meta::genre = court
# meta::sourceURL = https://www.linguistics.ucsb.edu/research/santa-barbara-corpus#SBC053
# meta::speakerCount = 5
# meta::title = I Will Appeal
# newpar
# sent_id = GUM_court_carpet-1
# speaker = Judge
# addressee = Mitchell
# text = Okay, the next case will be uh, Mitchell Roberts, versus, uh, Matthew Collins, ABC Builders Interiors?
1	Okay	okay	INTJ	UH	_	10	discourse	10:discourse	SpaceAfter=No
2	,	,	PUNCT	,	_	1	punct	1:punct	_
3	the	the	DET	DT	Definite=Def|PronType=Art	5	det	5:det	_
4	next	next	ADJ	JJ	Degree=Pos	5	amod	5:amod	_
5	case	case	NOUN	NN	Number=Sing	10	nsubj	10:nsubj	_
6	will	will	AUX	MD	VerbForm=Fin	10	aux	10:aux	_
7	be	be	AUX	VB	VerbForm=Inf	10	cop	10:cop	_
8	uh	uh	INTJ	UH	_	10	discourse	10:discourse	SpaceAfter=No
9	,	,	PUNCT	,	_	8	punct	8:punct	_
10	Mitchell	Mitchell	PROPN	NNP	Number=Sing	0	root	0:root	_
11	Roberts	Roberts	PROPN	NNP	Number=Sing	10	flat	10:flat	SpaceAfter=No
12	,	,	PUNCT	,	_	13	punct	13:punct	_
13	versus	versus	ADP	IN	_	17	case	17:case	SpaceAfter=No
14	,	,	PUNCT	,	_	13	punct	13:punct	_
15	uh	uh	INTJ	UH	_	17	discourse	17:discourse	SpaceAfter=No
16	,	,	PUNCT	,	_	15	punct	15:punct	_
17	Matthew	Matthew	PROPN	NNP	Number=Sing	10	obl	10:obl:versus	_
18	Collins	Collins	PROPN	NNP	Number=Sing	17	flat	17:flat	SpaceAfter=No
19	,	,	PUNCT	,	_	22	punct	22:punct	_
20	ABC	ABC	PROPN	NNP	Abbr=Yes|Number=Sing	21	compound	21:compound	_
21	Builders	Builder	PROPN	NNPS	Number=Plur	22	compound	22:compound	_
22	Interiors	Interior	PROPN	NNPS	Number=Plur	17	appos	17:appos	SpaceAfter=No
23	?	?	PUNCT	.	_	10	punct	10:punct	_

# newpar
# sent_id = GUM_court_carpet-2
# speaker = Bailiff
# text = This — both sides are here?
1	This	this	PRON	DT	Number=Sing|PronType=Dem	6	reparandum	6:reparandum	_
2	—	—	PUNCT	:	_	1	punct	1:punct	_
3	both	both	DET	DT	PronType=Ind	4	det	4:det	_
4	sides	side	NOUN	NNS	Number=Plur	6	nsubj	6:nsubj	_
5	are	be	AUX	VBP	Mood=Ind|Number=Plur|Person=3|Tense=Pres|VerbForm=Fin	6	cop	6:cop	_
6	here	here	ADV	RB	PronType=Dem	0	root	0:root	SpaceAfter=No
7	?	?	PUNCT	.	_	6	punct	6:punct	_

# sent_id = GUM_court_carpet-3
# speaker = Bailiff
# text = Is this contested?
1	Is	be	AUX	VBZ	Mood=Ind|Number=Sing|Person=3|Tense=Pres|VerbForm=Fin	3	aux:pass	3:aux:pass	_
2	this	this	PRON	DT	Number=Sing|PronType=Dem	3	nsubj:pass	3:nsubj:pass	_
```
<sup>Showing 50 of 220 lines. The full treebank contains a court hearing transcript with 5 speakers, POS tags, morphological features, and dependency annotations including spoken-language phenomena (fillers, false starts, corrections).</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Speaker Split** | Split `court_hearing.conllu` into separate `.conllu` files by speaker — one file per speaker, named after them in lowercase. Preserve sentence/document order, annotations, and metadata. Also create a `speakers.txt` manifest listing each speaker name, sentence count, and total token count. | Merge the per-speaker files back into a single `court_hearing.conllu`. Interleave sentences to follow the original document sequence based on `sent_id` ordering. Delete the per-speaker files and `speakers.txt`. | split & merge, classification |
| 2 | **POS Tag Swap** | Swap the UPOS and XPOS columns (columns 4 and 5) on every token line so PTB tags end up in column 4 and universal tags in column 5. Rename the file to `court_hearing_ptb.conllu`. | Swap columns 4 and 5 back so universal POS is in column 4 and PTB tags in column 5. Rename the file to `court_hearing.conllu`. | string manipulation |
| 3 | **Enhanced Deps Strip** | Strip the enhanced dependency column (DEPS, column 9) by replacing its value with `_`. Save the removed values to `enhanced_deps.tsv` with columns: `sent_id`, `token_id`, `enhanced_deps`. | Use `enhanced_deps.tsv` to restore column 9 (DEPS) in `court_hearing.conllu`. Delete `enhanced_deps.tsv`. | referencing |
| 4 | **Feature Extraction** | Extract morphological features into `morphology.tsv` with columns: `sent_id`, `token_id`, `form`, `feats`. Replace the FEATS column (column 6) with `_` in every token line. | Merge morphological features from `morphology.tsv` back into `court_hearing.conllu`. Delete `morphology.tsv`. | referencing |
| 5 | **Speech Normalization** | Normalize spoken-language artifacts: replace INTJ discourse markers with `[DM]` and reparandum tokens with `[REP]`. Record every replacement in `discourse_markers.json` keyed by `sent_id`. | Restore spoken-language forms from `discourse_markers.json`, replacing `[DM]` and `[REP]` placeholders with saved original values. Delete `discourse_markers.json`. | string manipulation, referencing |
| 6 | **Horizontal Conversion** | Convert vertical CoNLL-U to horizontal tab-separated `court_hearing.tsv` with one sentence per row. Store sentence-level metadata in `sentence_metadata.json` keyed by `sent_id`. | Convert `court_hearing.tsv` back to standard vertical CoNLL-U as `court_hearing.conllu`. Restore metadata from `sentence_metadata.json`. Delete both auxiliary files. | format knowledge, referencing |
