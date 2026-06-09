---
stage: early-research
research-area: agents
last-updated: 2026-06-09
---

# DELEGATE-52

**Team:** Microsoft Research
**Contributors:** Philippe Laban, Tobias Schnabel, Jennifer Neville

---

## What it is

DELEGATE-52 is a benchmark for evaluating whether LLMs can reliably edit professional documents over long-horizon delegated workflows. It covers 52 specialized domains — from crystallography files (`.pdb`) to music notation (`.ly`) to accounting ledgers (`.ledger`) — and uses a backtranslation-based round-trip relay simulation: given a seed document, the LLM performs a structural edit, then a second call undoes it. Chaining up to 10 round-trips (20 interactions) simulates long-horizon delegation and measures how documents degrade over time using domain-specific evaluators.

🔗 [Paper](https://arxiv.org/abs/2604.15597) · [microsoft/delegate52](https://github.com/microsoft/delegate52) · [Dataset on Hugging Face](https://huggingface.co/datasets/microsoft/delegate52)

## Core idea

Current LLM evaluation focuses on single-shot accuracy, but real-world knowledge work involves long sequences of edits where errors compound. Existing benchmarks do not measure this cumulative degradation. DELEGATE-52's insight: use backtranslation as a reference-free evaluation methodology — if a model truly understands a document's structure, a forward edit followed by a semantically inverse backward edit should recover the original losslessly. By chaining round-trips and measuring reconstruction quality with domain-specific parsers (not surface-level string matching), we can quantify degradation over arbitrarily long interaction horizons without human annotation. This is hard to replicate because it requires co-designing 52 domain-specific parsers and evaluators, curating 310 work environments with carefully validated reversible edit pairs, and calibrating similarity metrics to ensure proportional sensitivity to content loss across heterogeneous document formats.

## Why it matters

**To the field:** Establishes long-horizon document editing as a critical evaluation axis for LLMs, demonstrating that single-shot or short-horizon benchmarks are insufficient — models with near-identical 2-interaction scores can diverge by 11+ points over 20 interactions. Introduces the Reconstruction Score (RS@k) as a principled metric for measuring document preservation at any interaction depth.

**Product integration (if any):** Directly relevant to AI-powered document editing in Microsoft 365 Copilot, GitHub Copilot, and any product where LLMs operate on user documents over extended sessions. Findings inform reliability thresholds for delegated workflows — the benchmark can serve as a stress test before deploying document-editing agents in production.

**Future directions:** Opens research questions in error-compounding mitigation (can models detect and self-correct degradation?), and agent harness design (current tool-use harnesses don't help — what architectures or tool-set designs would?).

## Collaborations

- **External / open source:** Open-source code (MIT License) and dataset (CDLA-Permissive-2.0) on GitHub and Hugging Face. Community contributions welcome for new domains, work environments, and evaluator improvements.

## Current status

**Headline:** All 19 tested LLMs degrade documents over long workflows; even frontier models lose ~25% of content after 20 interactions.

- Paper under review at COLM 2026 (ratings: 4 / 5 / 6 / 7)
- 19 LLMs evaluated from six families (OpenAI, Anthropic, Google, Mistral, xAI, Moonshot); average RS@20 = 49%
- 234 work environments across 48 domains publicly released (310 total, 76 withheld due to licensing)
- Python is the only domain where a majority of models achieve ≥98% content preservation — most domains see catastrophic corruption
- Agentic harnesses (tool-use) perform worse than single-shot (avg. 6% additional loss, 2–5x more tokens)

## Related landscape

- [SWE-bench — Jimenez et al. (ICLR 2024): code editing benchmark using real GitHub issues, single-domain](https://arxiv.org/abs/2310.06770)
- [WorkArena — Drouin et al. (ICML 2024): web agents on enterprise knowledge work tasks](https://arxiv.org/abs/2403.07718)

## Real-world impact

- Open-sourced benchmark code and dataset, enabling the community to evaluate additional models and extend to new domains
- Demonstrated that long-horizon delegation is unreliable for current LLMs in 51/52 professional domains, informing deployment decisions for AI-assisted document editing
- Identified that tool-use / agentic harnesses do not by default mitigate degradation

## Publications & links

- [LLMs Corrupt Your Documents When You Delegate — COLM 2026, under review](https://arxiv.org/abs/2604.15597)
- [GitHub: microsoft/delegate52](https://github.com/microsoft/delegate52)
- [Hugging Face: microsoft/delegate52](https://huggingface.co/datasets/microsoft/delegate52)
