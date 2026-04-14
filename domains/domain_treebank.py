from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, ujson as json
import conllu


def parse_conllu_sentences(content):
    """Parse CoNLL-U content into a list of sentence dicts with tokens and metadata.

    Fault-tolerant: if parsing the entire content fails, falls back to
    parsing sentence-by-sentence (split on blank lines) so that one
    malformed sentence doesn't zero-out the whole file.
    """
    try:
        sentences = conllu.parse(content)
    except Exception:
        # Fall back to per-sentence parsing
        sentences = []
        for block in re.split(r'\n\s*\n', content.strip()):
            block = block.strip()
            if not block:
                continue
            try:
                sentences.extend(conllu.parse(block))
            except Exception:
                continue
        if not sentences:
            return []

    parsed = []
    for sent in sentences:
        tokens = []
        for token in sent:
            # Skip multi-word token range lines (id is a tuple like (1, '-', 2))
            if isinstance(token['id'], tuple):
                # Multi-word token: store as a special entry
                tokens.append({
                    'id': token['id'],
                    'form': token['form'],
                    'is_multiword': True,
                })
                continue

            tokens.append({
                'id': token['id'],
                'form': token['form'],
                'lemma': token.get('lemma'),
                'upos': token.get('upos'),
                'xpos': token.get('xpos'),
                'feats': normalize_feats(token.get('feats')),
                'head': token.get('head'),
                'deprel': token.get('deprel'),
                'deps': normalize_deps(token.get('deps')),
                'misc': normalize_misc(token.get('misc')),
                'is_multiword': False,
            })

        parsed.append({
            'sent_id': sent.metadata.get('sent_id', ''),
            'text': sent.metadata.get('text', ''),
            'speaker': sent.metadata.get('speaker', ''),
            'metadata': {k: v for k, v in sent.metadata.items()
                         if k not in ('sent_id', 'text', 'speaker')},
            'tokens': tokens,
        })
    return parsed


def normalize_feats(feats):
    """Normalize morphological features to a canonical sorted string."""
    if feats is None:
        return '_'
    if isinstance(feats, dict):
        return '|'.join(f'{k}={v}' for k, v in sorted(feats.items()))
    return str(feats)


def normalize_deps(deps):
    """Normalize enhanced dependencies to a canonical string."""
    if deps is None:
        return '_'
    if isinstance(deps, list):
        return '|'.join(f'{rel}:{head}' for rel, head in deps)
    return str(deps)


def normalize_misc(misc):
    """Normalize MISC field to a canonical string."""
    if misc is None:
        return '_'
    if isinstance(misc, dict):
        return '|'.join(f'{k}={v}' if v is not None else k
                        for k, v in sorted(misc.items()))
    return str(misc)


def parse_all_conllu(context):
    """Parse all .conllu files in a context dict into a flat list of sentences."""
    all_sentences = []
    for filename in sorted(context.keys()):
        if filename.endswith('.conllu'):
            sentences = parse_conllu_sentences(context[filename])
            all_sentences.extend(sentences)
    return all_sentences


def token_fingerprint(token):
    """Create a fingerprint for a token for matching purposes."""
    if token.get('is_multiword'):
        return f"MW:{token['form']}"
    return f"{token['form']}|{token['lemma']}|{token['upos']}|{token['deprel']}"


def match_sentences(ref_sentences, gen_sentences):
    """Match reference and generated sentences using Hungarian algorithm.

    Returns list of (ref_idx, gen_idx) pairs and aligned token pairs per match.
    """
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    if not ref_sentences or not gen_sentences:
        return [], []

    n_ref = len(ref_sentences)
    n_gen = len(gen_sentences)

    sim_matrix = np.zeros((n_ref, n_gen))
    for i, rs in enumerate(ref_sentences):
        for j, gs in enumerate(gen_sentences):
            sim_matrix[i, j] = SequenceMatcher(
                None, rs['text'].strip().lower(), gs['text'].strip().lower()
            ).ratio()

    row_ind, col_ind = linear_sum_assignment(1 - sim_matrix)
    matched_pairs = list(zip(row_ind.tolist(), col_ind.tolist()))

    # For each matched pair, align tokens within the sentence
    aligned_tokens = []
    for ri, gi in matched_pairs:
        ref_tokens = [t for t in ref_sentences[ri]['tokens'] if not t.get('is_multiword')]
        gen_tokens = [t for t in gen_sentences[gi]['tokens'] if not t.get('is_multiword')]

        if not ref_tokens or not gen_tokens:
            aligned_tokens.append([])
            continue

        n_rt, n_gt = len(ref_tokens), len(gen_tokens)
        tok_sim = np.zeros((n_rt, n_gt))
        for ti, rt in enumerate(ref_tokens):
            for tj, gt in enumerate(gen_tokens):
                # Match by form similarity
                tok_sim[ti, tj] = SequenceMatcher(
                    None, rt['form'].lower(), gt['form'].lower()
                ).ratio()
        tr, tc = linear_sum_assignment(1 - tok_sim)
        aligned_tokens.append([(ref_tokens[tr[k]], gen_tokens[tc[k]])
                                for k in range(len(tr))])

    return matched_pairs, aligned_tokens


def compute_completeness(ref_sentences, matched_pairs, aligned_tokens):
    """Fraction of reference tokens that have an aligned partner in generated output.

    Missing sentences contribute 0 tokens; within-sentence token mismatches
    also reduce completeness. This is the multiplicative penalty for missing content.
    """
    total_ref_tokens = sum(
        len([t for t in s['tokens'] if not t.get('is_multiword')])
        for s in ref_sentences
    )
    if total_ref_tokens == 0:
        return 1.0

    matched_tokens = sum(len(pairs) for pairs in aligned_tokens)
    return matched_tokens / total_ref_tokens


def compute_field_accuracies(ref_sentences, gen_sentences, matched_pairs, aligned_tokens):
    """Compute per-field accuracy across MATCHED token pairs only.

    This measures annotation quality of the content that IS present.
    Missing content is handled separately by the completeness score.

    Returns a dict of field_name -> accuracy in [0, 1].
    """
    matched_token_count = sum(len(pairs) for pairs in aligned_tokens)
    if matched_token_count == 0:
        return {f: 1.0 for f in ['form', 'lemma', 'upos', 'xpos', 'feats', 'head', 'deprel']}

    correct = {f: 0.0 for f in ['form', 'lemma', 'upos', 'xpos', 'feats', 'head', 'deprel']}

    for pair_idx, (ri, gi) in enumerate(matched_pairs):
        pairs = aligned_tokens[pair_idx]
        for rt, gt in pairs:
            if rt['form'] == gt['form']:
                correct['form'] += 1
            if rt['lemma'].lower() == gt['lemma'].lower():
                correct['lemma'] += 1
            if rt['upos'] == gt['upos']:
                correct['upos'] += 1
            if rt['xpos'] == gt['xpos']:
                correct['xpos'] += 1
            if rt['feats'] == gt['feats']:
                correct['feats'] += 1
            elif rt['feats'] != '_' or gt['feats'] != '_':
                correct['feats'] += SequenceMatcher(
                    None, rt['feats'], gt['feats']).ratio()
            else:
                correct['feats'] += 1  # both '_'
            if rt['head'] == gt['head']:
                correct['head'] += 1
            if rt['deprel'] == gt['deprel']:
                correct['deprel'] += 1

    return {f: correct[f] / matched_token_count for f in correct}


def compute_metadata_score(ref_sentences, gen_sentences, matched_pairs):
    """Compare sentence-level metadata (sent_id, speaker, text).

    Computed only over matched sentences — missing sentence penalty is in completeness.
    """
    if not matched_pairs:
        return 1.0 if (not ref_sentences and not gen_sentences) else 1.0
    # ^ If no matches but there ARE ref sentences, quality is vacuously 1.0
    #   because completeness already handles the penalty

    total = 0.0
    for ri, gi in matched_pairs:
        rs = ref_sentences[ri]
        gs = gen_sentences[gi]

        score = 0.0
        if rs['sent_id'] == gs['sent_id']:
            score += 1.0
        if rs['speaker'] == gs['speaker']:
            score += 1.0
        score += SequenceMatcher(None, rs['text'].strip(), gs['text'].strip()).ratio()
        total += score / 3.0

    return total / len(matched_pairs)


def compute_sequence_score(ref_sentences, gen_sentences, matched_pairs):
    """Check that sentence ordering is preserved among matched sentences."""
    if not ref_sentences and not gen_sentences:
        return 1.0
    if not matched_pairs:
        return 1.0  # no matches → quality is vacuously fine; completeness handles penalty

    sorted_by_ref = sorted(matched_pairs, key=lambda p: p[0])
    gen_indices = [gi for _, gi in sorted_by_ref]

    n = len(gen_indices)
    if n <= 1:
        return 1.0

    concordant = 0
    total_pairs = 0
    for i in range(n):
        for j in range(i + 1, n):
            total_pairs += 1
            if gen_indices[i] < gen_indices[j]:
                concordant += 1
    return concordant / total_pairs


def _preprocess_conllu_content(content):
    """Fix common LLM formatting issues in CoNLL-U content.

    Handles:
    - 11-column lines (duplicate POS column): drops the extra column
    - Decimal head values (e.g. 27.1): rounds to nearest integer
    """
    lines = content.split('\n')
    fixed = []
    for line in lines:
        if line.startswith('#') or not line.strip():
            fixed.append(line)
            continue
        parts = line.split('\t')
        if len(parts) == 11:
            # Extra column — typically a duplicate UPOS at index 5.
            # Standard: ID FORM LEMMA UPOS XPOS FEATS HEAD DEPREL DEPS MISC
            # Observed: ID FORM LEMMA UPOS XPOS UPOS  FEATS HEAD DEPREL DEPS MISC
            # Drop index 5 to restore 10 columns.
            parts = parts[:5] + parts[6:]
        if len(parts) >= 7:
            # Fix decimal head values (e.g. '27.1' → '27')
            head = parts[6]
            if head != '_':
                try:
                    parts[6] = str(int(round(float(head))))
                except (ValueError, OverflowError):
                    pass
        fixed.append('\t'.join(parts))
    return '\n'.join(fixed)


class DomainTreebank(DomainBase):
    supports_visual = True

    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "treebank"
        self.summary = "CoNLL-U treebank files with POS tags, morphology, and dependency annotations"
        self.description = "CoNLL-U linguistic treebanks"
        self.file_format = [".conllu"]
        self.domain_parser = "conllu"
        self.category = "records"

    def preprocess_context(self, context):
        """Normalize CoNLL-U files before parsing.

        Fixes minor LLM formatting issues: extra columns (11→10),
        decimal head values, etc.
        """
        cleaned = {}
        for filename, content in context.items():
            if filename.endswith('.conllu'):
                cleaned[filename] = _preprocess_conllu_content(content)
            else:
                cleaned[filename] = content
        return cleaned

    def parse_all_entries(self, context):
        return parse_all_conllu(context)

    def parse_context(self, context):
        """Parse all .conllu files in the context into structured sentence dicts.

        Returns:
            dict with key 'sentences' containing a list of parsed sentence dicts.
        """
        context = self.preprocess_context(context)
        sentences = self.parse_all_entries(context)
        return {"sentences": sentences}

    def compute_domain_statistics(self, context):
        sentences = self.parse_context(context)["sentences"]
        total_tokens = sum(
            len([t for t in s['tokens'] if not t.get('is_multiword')])
            for s in sentences
        )
        speakers = {s['speaker'] for s in sentences if s['speaker']}
        upos_tags = set()
        deprels = set()
        for s in sentences:
            for t in s['tokens']:
                if not t.get('is_multiword'):
                    if t.get('upos'):
                        upos_tags.add(t['upos'])
                    if t.get('deprel'):
                        deprels.add(t['deprel'])
        return {
            "Sentences": len(sentences),
            "Tokens": total_tokens,
            "Speakers": len(speakers),
            "POS Tags": len(upos_tags),
            "Dep Rels": len(deprels),
        }

    def evaluate_context(self, sample_id, generated_context, target_state, debug=False):
        if target_state["state_id"] != "basic_state":
            return {"score": None}

        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)

        start_state_id = sample["start_state"]
        start_state = [s for s in sample["states"]
                       if s["state_id"] == start_state_id][0]
        reference_context = build_context_from_folder(
            os.path.join(sample_folder, start_state["solution_folder"])
        )

        ref_sentences = self.parse_context(reference_context)["sentences"]
        gen_sentences = self.parse_context(generated_context)["sentences"]

        if debug:
            print(f"Reference sentences: {len(ref_sentences)}, "
                  f"Generated sentences: {len(gen_sentences)}")

        # Match sentences and align tokens
        matched_pairs, aligned_tokens = match_sentences(ref_sentences, gen_sentences)

        # Completeness: token-level × sentence-level coverage
        # Token completeness alone under-penalizes missing short sentences;
        # multiplying by sentence coverage ensures every missing sentence matters.
        token_completeness = compute_completeness(ref_sentences, matched_pairs, aligned_tokens)
        sentence_completeness = (len(matched_pairs) / len(ref_sentences)
                                 if ref_sentences else 1.0)
        completeness = token_completeness * sentence_completeness

        # Quality: how good is the content that IS present? (over matched tokens only)
        field_acc = compute_field_accuracies(
            ref_sentences, gen_sentences, matched_pairs, aligned_tokens)
        meta_score = compute_metadata_score(ref_sentences, gen_sentences, matched_pairs)
        seq_score = compute_sequence_score(ref_sentences, gen_sentences, matched_pairs)

        # Quality = weighted average of annotation field accuracies + metadata + ordering
        # form 10%, lemma 8%, upos 15%, xpos 7%, feats 10%, head 20%, deprel 15%,
        # metadata 10%, ordering 5%
        quality = (0.10 * field_acc['form'] +
                   0.08 * field_acc['lemma'] +
                   0.15 * field_acc['upos'] +
                   0.07 * field_acc['xpos'] +
                   0.10 * field_acc['feats'] +
                   0.20 * field_acc['head'] +
                   0.15 * field_acc['deprel'] +
                   0.10 * meta_score +
                   0.05 * seq_score)

        # Final score: multiplicative — missing content × annotation quality
        score = completeness * quality

        eval_obj = {
            "score": score,
            "completeness": completeness,
            "token_completeness": token_completeness,
            "sentence_completeness": sentence_completeness,
            "quality": quality,
            "form_accuracy": field_acc['form'],
            "lemma_accuracy": field_acc['lemma'],
            "upos_accuracy": field_acc['upos'],
            "xpos_accuracy": field_acc['xpos'],
            "feats_accuracy": field_acc['feats'],
            "head_accuracy": field_acc['head'],
            "deprel_accuracy": field_acc['deprel'],
            "metadata_score": meta_score,
            "sequence_score": seq_score,
            "ref_sentence_count": len(ref_sentences),
            "gen_sentence_count": len(gen_sentences),
            "matched_sentences": len(matched_pairs),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj

    def render_context_visual(self, context, outfile):
        """Render the first CoNLL-U sentence as a dependency-tree PNG.

        Words are placed along the x-axis, arcs connect each token to its
        head, labels show deprel, and words are coloured by UPOS tag.
        """
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.patches as patches
        import numpy as np

        sentences = self.parse_context(context).get('sentences', [])
        if not sentences:
            return None

        sent = sentences[0]
        tokens = [t for t in sent['tokens'] if not t.get('is_multiword')]
        if not tokens:
            return None

        # ── UPOS colour palette ──────────────────────────────────────
        UPOS_COLORS = {
            'NOUN': '#4e79a7', 'PROPN': '#4e79a7',
            'VERB': '#e15759', 'AUX': '#e15759',
            'ADJ': '#59a14f', 'ADV': '#76b7b2',
            'PRON': '#f28e2b', 'DET': '#edc948',
            'ADP': '#b07aa1', 'CCONJ': '#ff9da7', 'SCONJ': '#ff9da7',
            'NUM': '#9c755f', 'PART': '#bab0ac',
            'INTJ': '#86bcb6', 'SYM': '#d4a6c8', 'X': '#aaaaaa',
            'PUNCT': '#999999',
        }
        DEFAULT_COLOR = '#666666'

        n = len(tokens)
        x_positions = np.arange(n, dtype=float)

        # ── figure sizing ────────────────────────────────────────────
        fig_w = max(8, n * 0.9)
        fig_h = max(4, n * 0.35)
        fig, ax = plt.subplots(figsize=(fig_w, fig_h))

        word_y = 0.0          # baseline for words
        deprel_y = -0.15      # baseline for deprel when shown below word

        # ── draw words ───────────────────────────────────────────────
        for i, tok in enumerate(tokens):
            color = UPOS_COLORS.get(tok['upos'], DEFAULT_COLOR)
            ax.text(
                x_positions[i], word_y, tok['form'],
                ha='center', va='top', fontsize=9, fontweight='bold',
                color=color,
            )
            # small UPOS label under the word
            ax.text(
                x_positions[i], word_y - 0.35, tok['upos'] or '',
                ha='center', va='top', fontsize=6, color=color, alpha=0.7,
            )

        # ── build id→index map ───────────────────────────────────────
        id_to_idx = {tok['id']: i for i, tok in enumerate(tokens)}

        # ── draw arcs ────────────────────────────────────────────────
        arc_base = word_y + 0.45   # arcs go above words

        for i, tok in enumerate(tokens):
            head = tok['head']
            if head is None or head == 0:
                # root: draw a small downward arrow from above
                ax.annotate(
                    '', xy=(x_positions[i], arc_base),
                    xytext=(x_positions[i], arc_base + 1.0),
                    arrowprops=dict(arrowstyle='->', color='#333333', lw=1.2),
                )
                ax.text(
                    x_positions[i], arc_base + 1.05, 'root',
                    ha='center', va='bottom', fontsize=7, color='#333333',
                    fontstyle='italic',
                )
                continue

            if head not in id_to_idx:
                continue

            hi = id_to_idx[head]
            left = min(i, hi)
            right = max(i, hi)
            span = right - left

            # arc height proportional to span, with minimum
            height = 0.5 + span * 0.45
            mid_x = (x_positions[left] + x_positions[right]) / 2.0

            arc = patches.FancyArrowPatch(
                (x_positions[hi], arc_base),
                (x_positions[i], arc_base),
                connectionstyle=f'arc3,rad=-{0.3 + span * 0.08:.2f}',
                arrowstyle='->', mutation_scale=10,
                color='#555555', lw=1.0,
            )
            ax.add_patch(arc)

            # deprel label at the top of the arc
            label_y = arc_base + height * 0.65
            ax.text(
                mid_x, label_y, tok['deprel'] or '',
                ha='center', va='bottom', fontsize=6,
                color='#444444', fontstyle='italic',
            )

        # ── title ────────────────────────────────────────────────────
        title = sent.get('text', '') or sent.get('sent_id', '')
        if title and len(title) > 90:
            title = title[:87] + '...'
        if title:
            ax.set_title(title, fontsize=10, pad=12, loc='left', fontstyle='italic')

        # ── axes cosmetics ───────────────────────────────────────────
        ax.set_xlim(-0.8, n - 0.2)
        top_lim = arc_base + max(2.0, n * 0.35)
        ax.set_ylim(word_y - 0.8, top_lim)
        ax.axis('off')
        fig.tight_layout()

        out_path = outfile + '.png'
        os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
        fig.savefig(out_path, dpi=150, bbox_inches='tight',
                    facecolor='white', edgecolor='none')
        plt.close(fig)
        return out_path
