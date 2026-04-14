from utils_context import build_context_from_folder
from difflib import SequenceMatcher
from .domain_base import DomainBase
import chess.pgn
import io, os, re
import ujson as json


def parse_pgn(pgn_content):
    result = {'moves_uci': [], 'moves_san': [], 'annotations': [], 'headers': {}, 'result': None}
    
    try:
        pgn_io = io.StringIO(pgn_content)
        game = chess.pgn.read_game(pgn_io)
        if game is None:
            return result
        
        # Extract headers
        for key, value in game.headers.items():
            result['headers'][key] = value
        result['result'] = game.headers.get('Result', '*')
        
        # Extract moves and annotations
        board = game.board()
        node = game
        
        while node.variations:
            next_node = node.variation(0)
            move = next_node.move
            
            # Get UCI and SAN representation
            result['moves_uci'].append(move.uci())
            result['moves_san'].append(board.san(move))
            
            # Extract annotations from comment
            comment = next_node.comment
            if comment:
                # Extract eval: [%eval X.XX]
                eval_match = re.search(r'\[%eval\s*([+-]?\d+\.?\d*)\]', comment)
                eval_val = float(eval_match.group(1)) if eval_match else None
                
                # Extract NAGs (move quality markers like ?, !, ??, etc.)
                nags = list(next_node.nags) if next_node.nags else []
                
                result['annotations'].append({'eval': eval_val, 'nags': nags, 'comment': comment})
            else:
                result['annotations'].append({'eval': None, 'nags': list(next_node.nags) if next_node.nags else [], 'comment': ''})
            
            board.push(move)
            node = next_node
    except Exception as e:
        print(f"\033[93mWarning: Failed to parse PGN: {e}\033[0m")
        return result
    
    return result


def compute_move_sequence_score(ref_moves, gen_moves):
    if not ref_moves and not gen_moves:
        return 1.0
    if not ref_moves or not gen_moves:
        return 0.0
    return SequenceMatcher(None, ref_moves, gen_moves).ratio()


def compute_annotation_score(ref_annotations, gen_annotations):
    if not ref_annotations and not gen_annotations:
        return 1.0
    if not ref_annotations or not gen_annotations:
        return 0.0
    
    # Compare evals
    ref_evals = [a['eval'] for a in ref_annotations if a['eval'] is not None]
    gen_evals = [a['eval'] for a in gen_annotations if a['eval'] is not None]
    
    if not ref_evals and not gen_evals:
        eval_score = 1.0
    elif not ref_evals or not gen_evals:
        eval_score = 0.0
    else:
        # Compare eval sequences - allow small tolerance
        matches = 0
        min_len = min(len(ref_evals), len(gen_evals))
        for i in range(min_len):
            if abs(ref_evals[i] - gen_evals[i]) < 0.01:
                matches += 1
        eval_score = matches / max(len(ref_evals), len(gen_evals))
    
    # Compare NAGs (move quality markers)
    ref_nags = [tuple(a['nags']) for a in ref_annotations]
    gen_nags = [tuple(a['nags']) for a in gen_annotations]
    nag_score = SequenceMatcher(None, ref_nags, gen_nags).ratio()
    
    return 0.6 * eval_score + 0.4 * nag_score


def compute_header_score(ref_headers, gen_headers):
    important_fields = ['Event', 'Site', 'White', 'Black', 'WhiteElo', 'BlackElo', 'ECO', 'Opening', 'UTCDate']
    
    matches = 0
    total = 0
    for field in important_fields:
        ref_val = ref_headers.get(field, '')
        gen_val = gen_headers.get(field, '')
        if ref_val or gen_val:
            total += 1
            if str(ref_val).strip().lower() == str(gen_val).strip().lower():
                matches += 1
    
    return matches / total if total > 0 else 1.0


def compute_result_score(ref_result, gen_result):
    if ref_result == gen_result:
        return 1.0
    # Normalize result strings
    ref_norm = ref_result.replace(' ', '').lower() if ref_result else ''
    gen_norm = gen_result.replace(' ', '').lower() if gen_result else ''
    return 1.0 if ref_norm == gen_norm else 0.0


def merge_all_pgn(context):
    merged = ""
    for filename, content in context.items():
        if filename.endswith('.pgn'):
            merged += content + "\n"
    return merged


class DomainChess(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_documents.txt")
        self.sample_type = "chess"
        self.summary = "PGN chess game notation with moves, annotations, and game metadata"
        self.description = "PGN chess games"
        self.file_format = [".pgn"]
        self.domain_parser = "python-chess"
        self.category = "everyday"
    
    def parse_context(self, context):
        """Parse a context dict of filename->content into structured chess data.
        
        Returns a dict with keys:
          - pgn_raw: the merged raw PGN string
          - moves_uci: list of UCI move strings
          - moves_san: list of SAN move strings
          - annotations: list of annotation dicts (eval, nags, comment)
          - headers: dict of PGN header fields
          - result: game result string
        """
        pgn_raw = merge_all_pgn(context)
        parsed = parse_pgn(pgn_raw)
        parsed['pgn_raw'] = pgn_raw
        return parsed

    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        num_annotations = len([a for a in parsed['annotations'] if a['eval'] is not None])
        return {
            "Moves": len(parsed['moves_uci']),
            "Annotations": num_annotations,
            "Headers": len(parsed['headers']),
            "Result": parsed.get('result', '?'),
        }
    
    def evaluate_context(self, sample_id, generated_context, target_state):
        if target_state["state_id"] != "basic_state":
            return {}
        
        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)
        
        start_state_id = sample["start_state"]
        start_state = [state for state in sample["states"] if state["state_id"] == start_state_id][0]
        reference_context = build_context_from_folder(os.path.join(sample_folder, start_state["solution_folder"]))
        
        # Parse contexts
        ref_parsed = self.parse_context(reference_context)
        gen_parsed = self.parse_context(generated_context)
        
        # Compute component scores
        move_score = compute_move_sequence_score(ref_parsed['moves_uci'], gen_parsed['moves_uci'])
        annotation_score = compute_annotation_score(ref_parsed['annotations'], gen_parsed['annotations'])
        header_score = compute_header_score(ref_parsed['headers'], gen_parsed['headers'])
        result_score = compute_result_score(ref_parsed['result'], gen_parsed['result'])
        
        # Weighted aggregate: 70% moves, 10% each for others
        score = 0.70 * move_score + 0.10 * annotation_score + 0.10 * header_score + 0.10 * result_score
        
        eval_obj = {
            "score": score,
            "move_sequence_score": move_score,
            "annotation_score": annotation_score,
            "header_score": header_score,
            "result_score": result_score,
            "ref_move_count": len(ref_parsed['moves_uci']),
            "gen_move_count": len(gen_parsed['moves_uci']),
            "ref_annotation_count": len([a for a in ref_parsed['annotations'] if a['eval'] is not None]),
            "gen_annotation_count": len([a for a in gen_parsed['annotations'] if a['eval'] is not None]),
        }
        print(f"\033[94m{eval_obj}\033[0m")
        return eval_obj
