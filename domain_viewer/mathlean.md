# <img src="../assets/domain_icons/mathlean.svg" width="28" height="28" style="vertical-align: middle;"> MathLean

**Category:** Science & Engineering
**File format:** `.lean`
**Summary:** Lean 4 mathematical proofs with theorems, lemmas, and tactics
**Work environments released:** 6 / 6

Lean 4 proof files contain formal mathematical developments using the [Lean](https://lean-lang.org/) theorem prover. Each file consists of imports, section/namespace declarations, and named declarations (theorems, lemmas, definitions, instances) with type signatures and proof bodies written in term-mode or tactic-mode. This domain tests an LLM's ability to manipulate formal proof structures — reordering sections, splitting files, converting proof styles, extracting lemmas, and renaming declarations while preserving mathematical correctness.

**Domain implementation:** [`domain_mathlean.py`](../domains/domain_mathlean.py)

---

## Evaluation

The MathLean domain evaluator parses declarations (theorem, lemma, def, abbrev, instance, example), imports, and sections, then scores reconstruction quality across four dimensions:

- **Declaration matching** — Are all original declarations present with correct names, types, and signatures? (Uses Hungarian algorithm for optimal alignment; 40% weight)
- **Import coverage** — Are all original imports preserved? (25% weight, gated by declaration coverage)
- **Section coverage** — Are section/namespace structures intact? (15% weight, gated by declaration coverage)
- **Text similarity** — How close is the raw text to the reference? (20% weight)

**Score formula:** `0.40 × declaration + coverage² × (0.25 × import + 0.15 × section) + 0.20 × text_similarity`

---

## Example Work Environment: `mathlean1`

**Document:** Sum of Two Squares (Lean)
**Source:** [leanprover-community/mathlib4](https://github.com/leanprover-community/mathlib4/blob/master/Mathlib/NumberTheory/SumTwoSquares.lean) (Apache-2.0 License)
**Size:** 243 lines · 3,901 tokens

### Seed Document Excerpt (`SumTwoSquares.lean`)

```lean
/-
Copyright (c) 2019 Chris Hughes. All rights reserved.
Released under Apache 2.0 license as described in the file LICENSE.
Authors: Chris Hughes, Michael Stoll
-/
module

public import Mathlib.Data.Nat.Squarefree
public import Mathlib.NumberTheory.Zsqrtd.QuadraticReciprocity
public import Mathlib.NumberTheory.Padics.PadicVal.Basic

/-!
# Sums of two squares

Fermat's theorem on the sum of two squares. Every prime `p` congruent to 1 mod 4 is the
sum of two squares; see `Nat.Prime.sq_add_sq` (which has the weaker assumption `p % 4 ≠ 3`).

We also give the result that characterizes the (positive) natural numbers that are sums
of two squares as those numbers `n` such that for every prime `q` congruent to 3 mod 4, the
exponent of the largest power of `q` dividing `n` is even; see `Nat.eq_sq_add_sq_iff`.

There is an alternative characterization as the numbers of the form `a^2 * b`, where `b` is a
natural number such that `-1` is a square modulo `b`; see `Nat.eq_sq_add_sq_iff_eq_sq_mul`.
-/

@[expose] public section


section Fermat

open GaussianInt

/-- **Fermat's theorem on the sum of two squares**. Every prime not congruent to 3 mod 4 is the sum
of two squares. Also known as **Fermat's Christmas theorem**. -/
theorem Nat.Prime.sq_add_sq {p : ℕ} [Fact p.Prime] (hp : p % 4 ≠ 3) :
    ∃ a b : ℕ, a ^ 2 + b ^ 2 = p := by
  apply sq_add_sq_of_nat_prime_of_not_irreducible p
  rwa [_root_.irreducible_iff_prime, prime_iff_mod_four_eq_three_of_nat_prime p]

end Fermat

/-!
### Generalities on sums of two squares
-/


section General

/-- The set of sums of two squares is closed under multiplication in any commutative ring.
See also `sq_add_sq_mul_sq_add_sq`. -/
theorem sq_add_sq_mul {R} [CommRing R] {a b x y u v : R} (ha : a = x ^ 2 + y ^ 2)
    (hb : b = u ^ 2 + v ^ 2) : ∃ r s : R, a * b = r ^ 2 + s ^ 2 :=
  ⟨x * u - y * v, x * v + y * u, by rw [ha, hb]; ring⟩
```
<sup>Showing 50 of 243 lines. The full file contains the Mathlib proof of Fermat's theorem on sums of two squares across 4 sections (Fermat, General, NegOneSquare, Main), including docstrings, deprecation aliases, and various proof styles.</sup>

---

### Edit Tasks (9 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Section Reordering** | Reorder the sections so General comes before Fermat. | Move the Fermat section to the top, before General. | sorting |
| 2 | **Namespace Wrapping** | Wrap everything inside the NegOneSquare section in a NegOneSquare namespace. | Remove the NegOneSquare namespace wrapper, just keep the section. | format knowledge |
| 3 | **File Split** | Split the code into separate files by section. Create `SumTwoSquares/Fermat.lean`, `SumTwoSquares/General.lean`, `SumTwoSquares/NegOneSquare.lean`, and `SumTwoSquares/Main.lean`. Replace the root `SumTwoSquares.lean` with just the existing imports, module docstring, and imports of the four new files. | Consolidate the four section files back into a single root `SumTwoSquares.lean`, with sections ordered Fermat, General, NegOneSquare, Main. Keep the existing imports and module docstring at the top. Delete the `SumTwoSquares/` subdirectory. | split & merge, sorting |
| 4 | **Tactic Proof** | Convert the term-mode proof of `sq_add_sq_mul` to tactic mode. Show each step explicitly with `have`/`exact` instead of the angle bracket constructor. | Simplify the tactic proof of `sq_add_sq_mul` to a compact term-mode proof using the angle bracket constructor. | format knowledge |
| 5 | **Explicit Parameters** | Change all the `[Fact p.Prime]` typeclass instances to explicit `(hp : p.Prime)` parameters. Update the proof bodies to use `hp` directly. | Change the explicit `(hp : p.Prime)` parameters back to `[Fact p.Prime]` typeclass style. Use the `Fact.out` pattern in proofs where needed. | format knowledge |
| 6 | **Lemma Extraction** | In `ZMod.isSquare_neg_one_mul`, extract the anonymous `have : IsSquare (-1 : ZMod m × ZMod n)` proof into a separate lemma called `ZMod.isSquare_neg_one_prod` right before it. | Inline `ZMod.isSquare_neg_one_prod` into `ZMod.isSquare_neg_one_mul` as an anonymous `have` statement and delete the standalone lemma. | format knowledge |
| 7 | **Verbose Names** | Rename the single-letter variables to be more descriptive: `p` → `prime`, `q` → `factor`, `n` → `num`, `m` → `modulus`, `x`/`y` → `summandX`/`summandY`, `a`/`b` → `coeff1`/`coeff2`, `u`/`v` → `witness1`/`witness2`. | Use standard math notation with single letters: `prime` → `p`, `factor` → `q`, `num` → `n`, `modulus` → `m`, `summandX`/`summandY` → `x`/`y`, `coeff1`/`coeff2` → `a`/`b`, `witness1`/`witness2` → `u`/`v`. | string manipulation |
| 8 | **Dependency Subsections** | Add `-- Uses: decl1, decl2` dependency comments before each theorem/lemma/instance listing the file-local declarations its proof calls. Inside the NegOneSquare section, create NatResults and ZModResults subsections grouped by namespace prefix. Tag each declaration with `-- original_order: N`. | Remove all `-- Uses:` comments. Dissolve the NatResults and ZModResults subsections inside NegOneSquare and arrange declarations in their original order using the `-- original_order:` tags. Remove the order comments. | context expansion, sorting |
| 9 | **Generic Names** | Rename each named theorem and deprecated alias to a flat numbered name (`decl_01` through `decl_15` in declaration order). Add a `-- canonical: <original_name>` comment before each renamed declaration. Update all cross-references and alias targets. | Rename each `decl_NN` declaration to the name in its `-- canonical:` comment. Update all cross-references in proof bodies and alias targets. Remove the `-- canonical:` comments. | string manipulation, referencing |
