# <img src="../assets/domain_icons/chess.svg" width="28" height="28" style="vertical-align: middle;"> Chess

**Category:** Everyday
**File format:** `.pgn`
**Summary:** PGN chess game notation with moves, annotations, and game metadata
**Work environments released:** 5 / 5

PGN (Portable Game Notation) files record chess games with standard headers (event, players, ratings, opening classification), algebraic move notation, and optional engine annotations. Each move can carry evaluation scores (`[%eval]`) and quality markers (NAGs like `?`, `!`, `??`). This domain tests an LLM's ability to parse and transform structured game records — converting between notation systems, splitting by game phase, reformatting annotations, and manipulating positional data across lengthy move sequences.

**Domain implementation:** [`domain_chess.py`](../domains/domain_chess.py)

---

## Evaluation

The chess domain evaluator parses PGN files using `python-chess` and scores reconstruction quality across four dimensions:

- **Move sequence accuracy (70%)** — Are all moves present in the correct order? (Compares UCI move sequences)
- **Annotation preservation (10%)** — Are engine evaluations and NAG markers intact?
- **Header accuracy (10%)** — Are game metadata fields (event, players, ratings, ECO, opening) preserved?
- **Result correctness (10%)** — Is the game result string correct?

**Score formula:** `0.70 × move_sequence + 0.10 × annotation + 0.10 × header + 0.10 × result`

---

## Example Work Environment: `chess2`

**Document:** Cakey vs Eks Sicilian Defense
**Source:** [lichess.org/a49lbuz0](https://lichess.org/a49lbuz0) (Creative Commons CC0 1.0 Universal)
**Size:** 17 lines · 2,301 tokens

### Seed Document Excerpt (`cakey_vs_eks_sicilian.pgn`)

```
[Event "Rated Blitz game"]
[Site "https://lichess.org/a49lbuz0"]
[White "cakey"]
[Black "Eks"]
[Result "1-0"]
[UTCDate "2013.01.07"]
[UTCTime "22:22:47"]
[WhiteElo "1649"]
[BlackElo "1350"]
[WhiteRatingDiff "+41"]
[BlackRatingDiff "-41"]
[ECO "B25"]
[Opening "Sicilian Defense: Closed Variation, Traditional"]
[TimeControl "180+5"]
[Termination "Normal"]

1. e4 { [%eval 0.13] } 1... c5 { [%eval 0.25] } 2. Nc3 { [%eval 0.19] } 2... Nc6 { [%eval 0.27] } 3. Nf3 { [%eval 0.2] } 3... Nf6 { [%eval 0.24] } 4. d3 { [%eval -0.05] } 4... e5 { [%eval -0.01] } 5. Bg5 { [%eval 0.03] } 5... Be7 { [%eval 0.03] } 6. Nd5? { [%eval -1.13] } 6... Nb4? { [%eval 0.72] } 7. c3? { [%eval -0.94] } 7... Nbxd5 { [%eval -1.03] } 8. exd5 { [%eval -1.01] } 8... d6?! { [%eval -0.44] } 9. d4 { [%eval -0.66] } 9... cxd4 { [%eval -0.68] } 10. cxd4 { [%eval -0.97] } 10... Qa5+ { [%eval -0.94] } 11. Qd2 { [%eval -1.31] } 11... Qxd5?! { [%eval -0.54] } 12. dxe5 { [%eval -0.53] } 12... Qe4+ { [%eval -0.12] } 13. Be2 { [%eval 0.0] } 13... Ng4?? { [%eval 4.43] } 14. Bxe7 { [%eval 3.9] } 14... Kxe7 { [%eval 4.65] } 15. Qg5+ { [%eval 4.62] } 15... Kd7? { [%eval 6.01] } 16. Nd2? { [%eval 3.49] } 16... Qd4? { [%eval 6.01] } 17. Qxg4+? { [%eval 3.29] } 17... Qxg4 { [%eval 3.53] } 18. Bxg4+ { [%eval 3.27] } 18... Kc7?! { [%eval 4.0] } 19. f3?! { [%eval 3.14] } 19... dxe5 { [%eval 3.27] } 20. Bxc8?! { [%eval 2.61] } 20... Raxc8 { [%eval 2.56] } 21. O-O { [%eval 2.51] } 21... Kb8 { [%eval 2.7] } 22. Rac1 { [%eval 2.64] } 22... f6 { [%eval 2.72] } 23. Rxc8+ { [%eval 2.4] } 23... Rxc8 { [%eval 2.38] } 24. Ne4 { [%eval 1.94] } 24... Rc2 { [%eval 1.99] } 25. Rf2 { [%eval 2.11] } 25... Rc1+ { [%eval 0.0] } 26. Rf1 { [%eval 2.06] } 26... Rc2 { [%eval 2.1] } 27. Rf2? { [%eval 0.0] } 27... Rc1+ { [%eval 0.0] } 28. Rf1 { [%eval 0.0] } 28... Rc2 { [%eval 2.1] } 29. Nd6?! { [%eval 1.57] } 29... Rxb2 { [%eval 1.58] } 30. h3?! { [%eval 0.68] } 30... Rxa2 { [%eval 0.71] }
```
<sup>Showing first 30 moves of a 75-move game. The full PGN contains the complete Sicilian Defense game with engine evaluations and quality markers throughout.</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Symbol Conversion** | Convert numeric eval annotations to traditional move quality symbols: if eval swings by >2.0 against the mover use `??`; >1.0 use `?`; >0.5 use `?!`; improves by >1.0 use `!`; >2.0 use `!!`. Replace `{ [%eval X.XX] }` with the symbol and `{ was: X.XX }`. | Convert move quality symbols back to numeric eval format. Extract values from `{ was: X.XX }` comments and restore as `{ [%eval X.XX] }`. Remove quality symbols from moves. | numerical reasoning, string manipulation |
| 2 | **Phase Split** | Reorganize the game by phase. Split into sections with headers `=== OPENING ===`, `=== MIDDLEGAME ===`, `=== ENDGAME ===`. Remove move numbers within each phase. Add a 1-line summary after each header. Keep all moves and eval annotations. | Remove the phase headers and summaries, restore continuous move numbering throughout. | split & merge, topic modeling, context expansion |
| 3 | **Threat Annotation** | Convert to threat-annotated format. Replace `+` check symbol with `[CHECK]` marker. Add `[THREAT: description]` for tactical threats. Convert evals to threat-level markers like `{ [WINNING] was:2.5 }`. Add `=== TACTICAL MOMENTS ===` summary at end. | Restore standard format. Convert `[CHECK]` back to `+`, remove `[THREAT: ...]` annotations, convert threat-level markers back to numeric evals using `was:X.X` values. Remove TACTICAL MOMENTS section. | string manipulation, context expansion, numerical reasoning |
| 4 | **ECO Study Format** | Convert to opening study format. Replace the [Opening] header with detailed ECO classification. Add `{ book }` or `{ novelty }` markers to each opening move. Remove eval annotations from book moves. Add `=== OPENING TREE ===` at end. | Restore standard PGN. Simplify [Opening] header, remove `{ book }` and `{ novelty }` markers, restore eval annotations to all moves, remove OPENING TREE section. | domain knowledge, context expansion, numerical reasoning |
| 5 | **FEN Truncation** | Truncate the opening phase. Compute the board position (FEN) after move 12, add `[SetUp "1"]` and `[FEN "..."]` headers. Remove moves 1–12 from the move list. Save removed opening moves into `opening_moves.pgn`. | Merge opening moves back into the main game. Prepend the 12 moves from `opening_moves.pgn`, restore continuous numbering from move 1. Remove [SetUp] and [FEN] headers. | numerical reasoning, split & merge |
| 6 | **Scoresheet Format** | Reformat into tournament scoresheet style. Replace PGN headers with a `=== GAME CARD ===` block. Split interleaved moves into `=== WHITE (cakey) ===` and `=== BLACK (Eks) ===` sections. End with `=== RESULT: 1-0 ===`. | Reassemble standard PGN from the scoresheets. Convert GAME CARD fields back to PGN headers. Interleave White and Black move lists into standard notation. Remove section markers. | format knowledge, split & merge |
