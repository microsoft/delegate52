from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import os, re, math, ujson as json
from pydifact.segmentcollection import RawSegmentCollection


# ---------------------------------------------------------------------------
# EDIFACT parsing helpers
# ---------------------------------------------------------------------------

def parse_segments_from_text(text):
    """Parse EDIFACT text into a list of segment dicts using pydifact."""
    try:
        collection = RawSegmentCollection.from_str(text)
        segments = []
        for seg in collection.segments:
            segments.append({
                "tag": seg.tag,
                "elements": [
                    [str(c) for c in el] if isinstance(el, list) else [str(el)]
                    for el in seg.elements
                ],
            })
        return segments
    except Exception as e:
        print(f"\033[91mEDIFACT parsing error: {e}\033[0m")
        return []


def segments_to_raw_lines(segments):
    """Convert parsed segments back to raw EDIFACT lines for comparison."""
    lines = []
    for seg in segments:
        parts = []
        for el in seg["elements"]:
            parts.append(":".join(el))
        lines.append(seg["tag"] + "+" + "+".join(parts) + "'")
    return lines


def extract_messages(segments):
    """Split a segment list into envelope + messages.

    Returns:
        envelope_header: list of segments before first UNH
        messages: list of dicts, each with 'header_segments' and 'line_items'
        envelope_trailer: list of segments after last UNT
    """
    envelope_header = []
    messages = []
    envelope_trailer = []

    current_msg_header = []
    current_items = []
    current_item = []
    in_message = False
    past_last_message = False

    for seg in segments:
        tag = seg["tag"]

        if tag == "UNA":
            envelope_header.append(seg)
            continue

        if tag == "UNH":
            in_message = True
            past_last_message = False
            current_msg_header = [seg]
            current_items = []
            current_item = []
            continue

        if tag == "UNT":
            # Flush current item
            if current_item:
                current_items.append(current_item)
                current_item = []
            messages.append({
                "header_segments": current_msg_header,
                "line_items": current_items,
                "trailer": seg,
            })
            in_message = False
            past_last_message = True
            continue

        if not in_message:
            if past_last_message:
                envelope_trailer.append(seg)
            else:
                envelope_header.append(seg)
            continue

        # Inside a message
        if tag == "LIN":
            # Flush previous item
            if current_item:
                current_items.append(current_item)
            current_item = [seg]
        elif tag in ("BGM", "DTM", "RFF", "NAD", "CUX", "FII", "PAT", "PCD", "TOD"):
            # Message-level header segments (before first LIN)
            if not current_item and not current_items:
                current_msg_header.append(seg)
            elif current_item:
                current_item.append(seg)
            else:
                current_msg_header.append(seg)
        elif tag == "UNS":
            # Section separator — flush item, add to message header
            if current_item:
                current_items.append(current_item)
                current_item = []
            current_msg_header.append(seg)
        elif tag == "CNT":
            # Control total — message-level
            current_msg_header.append(seg)
        else:
            # Line-item-level segment (IMD, QTY, PRI, FTX, PIA, PAC, etc.)
            if current_item:
                current_item.append(seg)
            else:
                current_msg_header.append(seg)

    return envelope_header, messages, envelope_trailer


def parse_line_item(item_segments):
    """Parse a group of segments starting with LIN into a structured line item."""
    item = {
        "line_num": None,
        "action_code": None,
        "ean": None,
        "article_ids": [],
        "description": "",
        "quantities": {},
        "price": None,
        "price_type": None,
        "availability_date": None,
        "availability_code": None,
        "reference": None,
        "raw_segments": item_segments,
    }

    for seg in item_segments:
        tag = seg["tag"]
        els = seg["elements"]

        if tag == "LIN":
            # LIN+linenum+actioncode+ean:qualifier
            if len(els) >= 1:
                item["line_num"] = els[0][0] if els[0][0] else None
            if len(els) >= 2:
                item["action_code"] = els[1][0] if els[1][0] else None
            if len(els) >= 3:
                item["ean"] = els[2][0] if els[2][0] else None

        elif tag == "PIA":
            # PIA+qualifier+articleid:type
            if len(els) >= 2:
                article_id = els[1][0] if els[1] else ""
                article_type = els[1][1] if len(els[1]) > 1 else ""
                item["article_ids"].append({"id": article_id, "type": article_type})

        elif tag == "IMD":
            # IMD+type+attr+:::description
            if len(els) >= 3:
                desc_parts = els[2]
                # Description is typically in component 4+ (after 3 empty components)
                desc = " ".join(p for p in desc_parts if p).strip()
                item["description"] = desc

        elif tag == "QTY":
            # QTY+qualifier:quantity
            if len(els) >= 1 and len(els[0]) >= 2:
                qty_type = els[0][0]
                try:
                    qty_val = float(els[0][1])
                except (ValueError, IndexError):
                    qty_val = 0
                # 21=ordered, 12=dispatched, 85=remaining, 83=backordered
                item["quantities"][qty_type] = qty_val

        elif tag == "PRI":
            # PRI+type:amount::qualifier
            if len(els) >= 1:
                item["price_type"] = els[0][0] if els[0] else ""
                try:
                    item["price"] = float(els[0][1]) if len(els[0]) > 1 else None
                except (ValueError, IndexError):
                    item["price"] = None

        elif tag == "DTM":
            # DTM+qualifier:date:format
            if len(els) >= 1 and len(els[0]) >= 2:
                item["availability_date"] = els[0][1]

        elif tag == "FTX":
            # FTX+qualifier++code:subcode:subcode
            if len(els) >= 3:
                item["availability_code"] = ":".join(els[2]) if els[2] else ""

        elif tag == "RFF":
            # RFF+qualifier:reference
            if len(els) >= 1 and len(els[0]) >= 2:
                item["reference"] = els[0][1]

    return item


def parse_edifact_context(context):
    """Parse all EDIFACT files from a context dict into structured data."""
    all_segments = []
    for filename, content in sorted(context.items()):
        if filename.endswith(('.edi', '.edifact', '.txt')):
            segs = parse_segments_from_text(content)
            all_segments.extend(segs)

    if not all_segments:
        return {"envelope_header": [], "messages": [], "envelope_trailer": []}

    envelope_header, messages, envelope_trailer = extract_messages(all_segments)

    parsed_messages = []
    for msg in messages:
        parsed_items = [parse_line_item(item_segs) for item_segs in msg["line_items"]]

        # Extract message-level metadata
        msg_ref = None
        msg_type = None
        msg_date = None
        order_ref = None
        for seg in msg["header_segments"]:
            if seg["tag"] == "UNH" and len(seg["elements"]) >= 2:
                msg_ref = seg["elements"][0][0]
                msg_type = seg["elements"][1][0] if seg["elements"][1] else None
            elif seg["tag"] == "BGM" and len(seg["elements"]) >= 2:
                pass  # BGM document number
            elif seg["tag"] == "DTM" and len(seg["elements"]) >= 1:
                if len(seg["elements"][0]) >= 2:
                    msg_date = seg["elements"][0][1]
            elif seg["tag"] == "RFF" and len(seg["elements"]) >= 1:
                if len(seg["elements"][0]) >= 2:
                    order_ref = seg["elements"][0][1]

        parsed_messages.append({
            "msg_ref": msg_ref,
            "msg_type": msg_type,
            "msg_date": msg_date,
            "order_ref": order_ref,
            "header_segments": msg["header_segments"],
            "line_items": parsed_items,
            "item_count": len(parsed_items),
        })

    return {
        "envelope_header": envelope_header,
        "messages": parsed_messages,
        "envelope_trailer": envelope_trailer,
    }


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def compute_item_similarity(ref_item, gen_item):
    """Compute similarity between two line items on a [0, 1] scale."""
    scores = {}

    # EAN match (exact)
    if ref_item["ean"] and gen_item["ean"]:
        scores["ean"] = 1.0 if ref_item["ean"] == gen_item["ean"] else 0.0
    elif not ref_item["ean"] and not gen_item["ean"]:
        scores["ean"] = 1.0
    else:
        scores["ean"] = 0.0

    # Description similarity (fuzzy)
    ref_desc = ref_item["description"].lower().strip()
    gen_desc = gen_item["description"].lower().strip()
    if ref_desc and gen_desc:
        scores["description"] = SequenceMatcher(None, ref_desc, gen_desc).ratio()
    elif not ref_desc and not gen_desc:
        scores["description"] = 1.0
    else:
        scores["description"] = 0.0

    # Quantity match
    ref_qty = ref_item["quantities"]
    gen_qty = gen_item["quantities"]
    if ref_qty or gen_qty:
        all_keys = set(ref_qty.keys()) | set(gen_qty.keys())
        qty_matches = sum(
            1 for k in all_keys
            if ref_qty.get(k) == gen_qty.get(k)
        )
        scores["quantities"] = qty_matches / len(all_keys) if all_keys else 1.0
    else:
        scores["quantities"] = 1.0

    # Price match
    ref_price = ref_item["price"]
    gen_price = gen_item["price"]
    if ref_price is not None and gen_price is not None:
        if ref_price == gen_price:
            scores["price"] = 1.0
        elif ref_price == 0 or gen_price == 0:
            scores["price"] = 0.0
        else:
            scores["price"] = min(ref_price, gen_price) / max(ref_price, gen_price)
    elif ref_price is None and gen_price is None:
        scores["price"] = 1.0
    else:
        scores["price"] = 0.0

    # Availability/FTX code
    ref_code = (ref_item.get("availability_code") or "").strip()
    gen_code = (gen_item.get("availability_code") or "").strip()
    scores["avail_code"] = 1.0 if ref_code == gen_code else 0.0

    # Reference
    ref_ref = (ref_item.get("reference") or "").strip()
    gen_ref = (gen_item.get("reference") or "").strip()
    scores["reference"] = 1.0 if ref_ref == gen_ref else 0.0

    # Weighted combination
    weight_sum = 0
    weighted_score = 0
    weights = {
        "ean": 0.20,
        "description": 0.20,
        "quantities": 0.25,
        "price": 0.15,
        "avail_code": 0.10,
        "reference": 0.10,
    }
    for key, w in weights.items():
        weighted_score += w * scores.get(key, 0.0)
        weight_sum += w

    return weighted_score / weight_sum if weight_sum > 0 else 0.0


def match_items(ref_items, gen_items):
    """Match reference line items to generated items using Hungarian algorithm.

    Returns (coverage, avg_matched_similarity).
    """
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    if not ref_items and not gen_items:
        return 1.0, 1.0
    if not ref_items or not gen_items:
        return 0.0, 0.0

    n_ref = len(ref_items)
    n_gen = len(gen_items)

    sim_matrix = np.zeros((n_ref, n_gen))
    for i, ri in enumerate(ref_items):
        for j, gi in enumerate(gen_items):
            sim_matrix[i, j] = compute_item_similarity(ri, gi)

    row_ind, col_ind = linear_sum_assignment(1 - sim_matrix)

    matched_sims = [sim_matrix[i, j] for i, j in zip(row_ind, col_ind)]
    good_matches = sum(1 for s in matched_sims if s > 0.3)
    coverage = good_matches / n_ref

    good_sims = [s for s in matched_sims if s > 0.3]
    avg_sim = sum(good_sims) / len(good_sims) if good_sims else 0.0

    return coverage, avg_sim


def compare_header_segments(ref_headers, gen_headers):
    """Compare message-level header segments.

    Returns a similarity score [0, 1].
    """
    # Extract key header values for comparison
    def extract_header_keys(headers):
        keys = {}
        for seg in headers:
            tag = seg["tag"]
            if tag == "UNH":
                keys["msg_type"] = seg["elements"][1] if len(seg["elements"]) > 1 else []
            elif tag == "BGM":
                keys["bgm"] = seg["elements"]
            elif tag == "DTM":
                keys["dtm"] = seg["elements"]
            elif tag == "RFF":
                keys["rff"] = seg["elements"]
            elif tag == "NAD":
                keys.setdefault("nad", []).append(seg["elements"])
            elif tag == "CUX":
                keys["cux"] = seg["elements"]
        return keys

    ref_keys = extract_header_keys(ref_headers)
    gen_keys = extract_header_keys(gen_headers)

    scores = []

    # Message type match
    if "msg_type" in ref_keys:
        if ref_keys.get("msg_type") == gen_keys.get("msg_type"):
            scores.append(1.0)
        else:
            scores.append(0.0)

    # Date match
    if "dtm" in ref_keys:
        if ref_keys.get("dtm") == gen_keys.get("dtm"):
            scores.append(1.0)
        else:
            scores.append(0.0)

    # Reference match
    if "rff" in ref_keys:
        if ref_keys.get("rff") == gen_keys.get("rff"):
            scores.append(1.0)
        else:
            scores.append(0.0)

    # NAD parties match
    if "nad" in ref_keys:
        ref_nads = set(str(n) for n in ref_keys.get("nad", []))
        gen_nads = set(str(n) for n in gen_keys.get("nad", []))
        if ref_nads:
            scores.append(len(ref_nads & gen_nads) / len(ref_nads))
        else:
            scores.append(1.0)

    # Currency match
    if "cux" in ref_keys:
        if ref_keys.get("cux") == gen_keys.get("cux"):
            scores.append(1.0)
        else:
            scores.append(0.0)

    return sum(scores) / len(scores) if scores else 1.0


def match_messages(ref_messages, gen_messages):
    """Match reference messages to generated messages.

    Messages are matched by order reference or message reference number.
    Returns list of (ref_idx, gen_idx, header_sim, item_coverage, item_sim).
    """
    if not ref_messages and not gen_messages:
        return [], 1.0
    if not ref_messages or not gen_messages:
        return [], 0.0

    # Try matching by order reference first, then by position
    matched = []
    used_gen = set()

    for ri, ref_msg in enumerate(ref_messages):
        best_gi = None
        best_score = -1

        for gi, gen_msg in enumerate(gen_messages):
            if gi in used_gen:
                continue

            # Check if order references match
            ref_oref = ref_msg.get("order_ref", "")
            gen_oref = gen_msg.get("order_ref", "")
            if ref_oref and gen_oref and ref_oref == gen_oref:
                score = 2.0  # Strong match
            else:
                # Fall back to item count similarity
                ref_n = ref_msg["item_count"]
                gen_n = gen_msg["item_count"]
                score = 1.0 - abs(ref_n - gen_n) / max(ref_n, gen_n, 1)

            if score > best_score:
                best_score = score
                best_gi = gi

        if best_gi is not None:
            used_gen.add(best_gi)
            matched.append((ri, best_gi))

    msg_coverage = len(matched) / len(ref_messages) if ref_messages else 1.0
    return matched, msg_coverage


# ---------------------------------------------------------------------------
# Main evaluator
# ---------------------------------------------------------------------------

class DomainEdifact(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "edifact"
        self.summary = "UN/EDIFACT supply chain messages (ORDERS, ORDRSP, INVOIC, DESADV, PRICAT)"
        self.description = "UN/EDIFACT trade messages"
        self.file_format = [".edi"]
        self.domain_parser = "pydifact"
        self.category = "records"

    def parse_context(self, context):
        return parse_edifact_context(context)

    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        total_items = sum(m["item_count"] for m in parsed["messages"])
        msg_types = set()
        for m in parsed["messages"]:
            if m.get("msg_type"):
                msg_types.add(m["msg_type"])
        return {
            "Messages": len(parsed["messages"]),
            "Line Items": total_items,
            "Message Types": ", ".join(sorted(msg_types)) if msg_types else "N/A",
        }

    def evaluate_context(self, sample_id, generated_context, target_state, debug=False):
        if target_state["state_id"] != "basic_state":
            return {}

        # Load reference context
        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)

        start_state_id = sample["start_state"]
        start_state = [s for s in sample["states"] if s["state_id"] == start_state_id][0]
        reference_context = build_context_from_folder(
            os.path.join(sample_folder, start_state["solution_folder"])
        )

        # Parse both contexts
        ref_parsed = self.parse_context(reference_context)
        gen_parsed = self.parse_context(generated_context)

        ref_messages = ref_parsed["messages"]
        gen_messages = gen_parsed["messages"]

        if debug:
            print(f"Reference: {len(ref_messages)} messages, Generated: {len(gen_messages)} messages")

        # 1. Message coverage
        matched_pairs, msg_coverage = match_messages(ref_messages, gen_messages)

        # 2. Per-message scoring
        header_scores = []
        item_coverages = []
        item_sims = []

        for ri, gi in matched_pairs:
            ref_msg = ref_messages[ri]
            gen_msg = gen_messages[gi]

            # Header accuracy
            h_score = compare_header_segments(
                ref_msg["header_segments"], gen_msg["header_segments"]
            )
            header_scores.append(h_score)

            # Line item matching
            coverage, avg_sim = match_items(
                ref_msg["line_items"], gen_msg["line_items"]
            )
            item_coverages.append(coverage)
            item_sims.append(avg_sim)

        avg_header = sum(header_scores) / len(header_scores) if header_scores else 0.0
        avg_item_coverage = (
            sum(item_coverages) / len(item_coverages) if item_coverages else 0.0
        )
        avg_item_sim = sum(item_sims) / len(item_sims) if item_sims else 0.0

        # Final weighted score
        # msg_coverage^2 penalizes missing messages strongly
        # item_coverage^1.5 is a multiplicative gate — removing K/N items
        #   drops the score by more than K/N (proportionality rule)
        # Within matched items, detail accuracy and header accuracy matter
        score = (
            (msg_coverage ** 2)
            * (avg_item_coverage ** 1.5)
            * (0.20 * avg_header + 0.80 * avg_item_sim)
        )

        # Clamp to [0, 1]
        score = max(0.0, min(1.0, score))

        eval_obj = {
            "score": score,
            "message_coverage": msg_coverage,
            "header_accuracy": avg_header,
            "item_coverage": avg_item_coverage,
            "item_detail_accuracy": avg_item_sim,
            "ref_message_count": len(ref_messages),
            "gen_message_count": len(gen_messages),
            "ref_total_items": sum(m["item_count"] for m in ref_messages),
            "gen_total_items": sum(m["item_count"] for m in gen_messages),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj
