# <img src="../assets/domain_icons/latex.svg" width="28" height="28" style="vertical-align: middle;"> LaTeX

**Category:** Creative & Media
**File format:** `.tex`, `.bib`
**Summary:** LaTeX documents with BibTeX bibliographies, equations, and formatting
**Work environments released:** 6 / 6

LaTeX academic documents consist of `.tex` source files with sectioning commands, inline citations (`\cite`, `\citep`, `\citet`), and standard formatting, paired with `.bib` BibTeX bibliography files containing complete bibliographic entries. This domain tests an LLM's ability to manipulate structured academic content — converting between formats, splitting and merging multi-file projects, reordering bibliographies, factoring macros, and preserving citation–reference linkages across transformations.

**Domain implementation:** [`domain_latex.py`](../domains/domain_latex.py)

---

## Evaluation

The LaTeX domain evaluator scores reconstruction quality across four weighted components:

- **Text content** — Is the prose content of the LaTeX document preserved? (Levenshtein similarity on extracted text, 35%)
- **Citation sequence** — Are citations preserved in the correct document order? (Sequence matching on fingerprinted entries, 25%)
- **Bibliography completeness** — Are all BibTeX entries present? (Jaccard similarity on content-based fingerprints, 20%)
- **Field accuracy** — Are bibliographic fields (author, title, year, journal, etc.) correct? (Fuzzy matching on matched entry pairs, 20%)

**Score formula:** `0.35 × text + 0.25 × citation_sequence + 0.20 × bib_completeness + 0.20 × field_accuracy`

---

## Example Work Environment: `latex1`

**Document:** LLM Multi-Turn Conversation Paper
**Source:** [arxiv.org/abs/2505.06120](https://arxiv.org/abs/2505.06120) (CC-BY-4.0 License)
**Size:** 366 lines · 6,061 tokens

### Seed Document Excerpt (`llm_multiterm_conversation.tex`)

```latex
Today's large language models (LLMs) function as conversational interfaces
(\textit{e.g.}, ChatGPT, Gemini, Claude), enabling users to interact with
the LLM through multiple conversation turns. Such interaction promises to
help users not only when they know what they need (i.e., they can fully
specify their requirements in an instruction), but also when they don't.
In such cases, users might start with an underspecified instruction and
further clarify their needs through turn interactions.
Though studies of LLM conversation logs have confirmed that
underspecification in user instructions is prevalent
\citep{herlihy2024overcoming}, LLM systems are typically evaluated in
single-turn, fully-specified settings.

Even though a growing body of work proposes to evaluate LLMs in a
\textbf{multi-turn} fashion, we identify in our review (Background and
Related Work section) that most prior work treats the conversation as
\textit{episodic}: conversation turns might relate to each other, but the
conversation can effectively be decomposed as an array of subtasks that
can be evaluated in isolation.
We argue that episodic tasks move away from what is prevalent in human
conversation: underspecification~\cite{zipf1949human,herlihy2024overcoming}.

In this work, we close this gap by creating a simulation environment for
multi-turn underspecified conversations  -- sharded simulation -- that
leverages existing instructions from high-quality single-turn benchmarks.
```
<sup>Showing 25 of 61 lines in the .tex file. The full document covers introduction and background sections with inline citations. The accompanying <code>bibtex.bib</code> (307 lines) contains 30+ bibliographic entries spanning LLM evaluation, conversational AI, NLP foundations, and human factors.</sup>

---

### Edit Tasks (5 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Markdown Conversion** | Convert this LaTeX document to a Markdown file called `document.md`. Replace all citations with numbered references [1], [2], [3] in order of first appearance. At the end, add a '## References' section with Chicago Bibliography style using full author names, all available bibliographic metadata, and the original bibtex citation key in parentheses at the end of each reference. Delete bibtex.bib. | Convert this Markdown document to LaTeX format as `latex.tex` and `bibtex.bib`. Replace all numbered citations [N] with `\citep{KEY}` commands using the bibtex keys from the References section. Reconstruct @article bibtex entries from the Chicago-style references. Remove the References section from the LaTeX output. | format knowledge, referencing, context expansion |
| 2 | **Document Splitting** | Split `llm_multiterm_conversation.tex` into multiple files: `main.tex` with `\input{}` includes, `abstract.tex` with a ~150 word abstract, `introduction.tex` and `background.tex` with the corresponding sections. Split the bibliography into per-section `.bib` files. Delete the originals. | Merge the split LaTeX files back into a single `llm_multiterm_conversation.tex` by inlining content from `\input{}` files. Remove the abstract section entirely. Combine the split `.bib` files into a single `bibtex.bib`, deduplicating entries. Delete all split files. | split & merge, context expansion |
| 3 | **Bibliography Sorting** | Sort the bibtex entries by citation frequency — most cited entries first. For entries cited the same number of times, sort alphabetically by first author's last name. Don't change latex.tex. | Reorder the bibtex entries in order of first appearance in the document. Don't change latex.tex. | sorting |
| 4 | **Topic Clustering** | Reorganize the bibliography into topic-clustered sections delimited by `@comment{TOPIC}` lines. Use four clusters: "LLM Evaluation", "Conversational AI", "NLP Foundations", "Human Factors & AI Adoption". Sort entries within each cluster by year ascending. Annotate each citation in the tex file with `\citetopic{topic}`. Add an `%% ORIGINAL_ORDER` comment listing current entry keys. | Strip all `\citetopic{...}` annotations from the tex file. Reorder bib entries to match the `%% ORIGINAL_ORDER` comment, then remove that comment and all `@comment{}` topic delimiter lines. | topic modeling, sorting |
| 5 | **Macro Factoring** | Factor recurring technical phrases into LaTeX macros defined in a `%% BEGIN_MACROS` / `%% END_MACROS` block at the top of the tex file. Create macros for at least: "sharded simulation", "sharded instructions", "lost in conversation phenomenon", and "underspecified user instructions". Add a restoration map as comments. Convert inline numbered lists into `\begin{enumerate}` environments. Don't change bibtex.bib. | Expand all custom macros to their full text using the MACRO_MAP comments. Convert enumerate environments into inline parenthesized numbered lists. Remove the macro definitions block. Don't touch bibtex.bib. | string manipulation, referencing |
