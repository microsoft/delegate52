# <img src="../assets/domain_icons/fiction.svg" width="28" height="28" style="vertical-align: middle;"> Fiction

**Category:** Creative &amp; Media
**File format:** `.txt`
**Summary:** Creative short fiction stories evaluated by LLM judge for quality
**Work environments released:** 0 / 6

Creative fiction pieces are short stories in plain text, featuring dialogue, internal thoughts, and emotional beats. Unlike most domains that evaluate against a reference document, the Fiction domain uses quality metrics to acknowledge creative variation. Edit tasks include opening scene rewrites, ending modifications, and dialogue/narrative conversions — all requiring the model to maintain narrative coherence, character consistency, and prose quality while transforming the story's structure.

**Domain implementation:** [`domain_fiction.py`](../domains/domain_fiction.py)

---

## Evaluation

The Fiction domain evaluator uses TTCW (14 creative-writing aspects) scored by an LLM judge on a 0–5 Likert scale, plus a length penalty that enforces word-count fidelity:

- **Narrative Ending** — Does the story resolve satisfyingly?
- **Understandability and Coherence** — Is the narrative logically consistent?
- **Scene vs Summary** — Appropriate balance of showing and telling?
- **Narrative Pacing** — Does the story flow at a natural tempo?
- **Language Proficiency and Literary Devices** — Quality of prose and figurative language?
- **Emotional Flexibility** — Range and authenticity of emotional expression?
- **Structural Flexibility** — Varied and effective story structure?
- **Perspective and Voice Flexibility** — Consistent and appropriate narrative voice?
- **Originality in Thought** — Fresh ideas and perspectives?
- **Originality in Form and Structure** — Creative structural choices?
- **Originality in Theme and Content** — Novel thematic exploration?
- **Rhetorical Complexity** — Layered meaning and subtext?
- **World Building and Setting** — Vivid and immersive environment?
- **Character Development** — Believable character arcs and depth?

The TTCW normalized score (average of 14 aspects ÷ 5) is compared against a cached baseline computed on the original story. A **length penalty** requires the output to stay within 10% of the target word count; deviation beyond that range incurs an exponential penalty (e.g., 200% of target → 0.75 penalty, 300% → 0.56).

**Score formula:** `min(1, ttcw_score / baseline_ttcw) × length_penalty`
