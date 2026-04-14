from utils_context import stringify_context, build_context_from_folder
# from transformers import AutoModel, AutoTokenizer
# from huggingface_hub import hf_hub_download
from difflib import SequenceMatcher
from model_openai import generate_json
from .domain_base import DomainBase
import os, ujson as json

# import torch
# import torch.nn as nn

# class MBertWQRM(nn.Module):
#     def __init__(self, model_name: str):
#         super().__init__()
#         self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
#         
#         # Load tokenizer and NLU model for both local and online sources
#         self.tokenizer = AutoTokenizer.from_pretrained(model_name)
#         self.nlu = AutoModel.from_pretrained(model_name)
#         hidden_size = self.nlu.config.hidden_size
#         
#         # Create regression head
#         self.regression_head = self._create_regression_head(hidden_size)
#         
#         # Initialize weights
#         self._init_weights(self.regression_head)
#         
#         # Try to load the custom heads from the model
#         self._load_custom_heads(model_name)
#         
#         self.regression_scale = 10.0  # Scale factor for regression output
#         self.to(self.device)
#
#     def _load_custom_heads(self, model_name: str):
#         """Load custom heads from local or online models"""
#         # Check if model_name is a local path or an online model
#         if os.path.exists(model_name):
#             # Local path
#             heads_path = os.path.join(model_name, 'heads.pth')
#             if os.path.exists(heads_path):
#                 heads_state = torch.load(heads_path, map_location=self.device)
#                 self.regression_head.load_state_dict(heads_state['regression_head'])
#         else:
#             try:
#                 # Use huggingface_hub to download with built-in caching
#                 repo_id = model_name
#                 filename = "heads.pth"
#                 
#                 # Download the file (will use cache if available)
#                 cached_file = hf_hub_download(
#                     repo_id=repo_id,
#                     filename=filename,
#                     cache_dir=None,  # Use default HF cache directory
#                     resume_download=True
#                 )
#                 
#                 # Load the heads from the cached path
#                 if os.path.exists(cached_file):
#                     heads_state = torch.load(cached_file, map_location=self.device)
#                     self.regression_head.load_state_dict(heads_state['regression_head'])
#                 else:
#                     print(f"Warning: Could not find custom heads at {cached_file}")
#             except Exception as e:
#                 print(f"Error loading custom heads: {e}")
#
#     def _create_regression_head(self, hidden_size):
#         return nn.Sequential(
#             nn.Dropout(0.1),
#             nn.Linear(hidden_size, hidden_size // 2),
#             nn.GELU(),
#             nn.Linear(hidden_size // 2, 1),
#             nn.Sigmoid(),
#         )
#     
#     def _init_weights(self, module):
#         if isinstance(module, nn.Linear):
#             module.weight.data.normal_(mean=0.0, std=0.02)
#             if module.bias is not None:
#                 module.bias.data.zero_()
#     
#     def forward(self, paragraphs1, paragraphs2, rationales=None):
#         N = len(paragraphs1)
#         if rationales is None:
#             rationales = [""] * N
#
#         SEP_TOKEN_ID = self.tokenizer.sep_token_id
#         
#         # Process each pair of paragraphs
#         all_input_ids, all_attention_masks, all_p1_ranges, all_p2_ranges = [], [], [], []
#         
#         for p1, p2, r in zip(paragraphs1, paragraphs2, rationales):
#             p1_tokens = self.tokenizer(p1, add_special_tokens=False)['input_ids']
#             p2_tokens = self.tokenizer(p2, add_special_tokens=False)['input_ids']
#
#             r_tokens = []
#             if r != "":
#                 r_tokens = self.tokenizer(r, add_special_tokens=False)['input_ids']
#
#             
#             input_ids = p1_tokens + [SEP_TOKEN_ID] + p2_tokens
#             if len(r_tokens) > 0:
#                 input_ids += [SEP_TOKEN_ID] + r_tokens
#
#             attention_mask = [1] * len(input_ids)
#             
#             p1_range = [0, len(p1_tokens)]
#             p2_range = [len(p1_tokens) + 1, len(p1_tokens) + len(p2_tokens) + 1]
#             
#             all_input_ids.append(input_ids)
#             all_attention_masks.append(attention_mask)
#             all_p1_ranges.append(p1_range)
#             all_p2_ranges.append(p2_range)
#         
#         # Pad sequences
#         max_len = max(len(ids) for ids in all_input_ids)
#         padded_input_ids = []
#         padded_attention_masks = []
#         
#         for input_ids, attention_mask in zip(all_input_ids, all_attention_masks):
#             padding_length = max_len - len(input_ids)
#             padded_input_ids.append(input_ids + [self.tokenizer.pad_token_id] * padding_length)
#             padded_attention_masks.append(attention_mask + [0] * padding_length)
#         
#         # Convert to tensors
#         input_ids = torch.tensor(padded_input_ids).to(self.device)
#         attention_mask = torch.tensor(padded_attention_masks).to(self.device)
#         p1_ranges = torch.tensor(all_p1_ranges).to(self.device)
#         p2_ranges = torch.tensor(all_p2_ranges).to(self.device)
#         
#         # Process through model
#         outputs = self.nlu(input_ids=input_ids, attention_mask=attention_mask)
#
#         p1_outputs, p2_outputs = [], []
#         for i in range(N):
#             p1_outputs.append(outputs.last_hidden_state[i, p1_ranges[i][0]:p1_ranges[i][1], :].mean(dim=0).unsqueeze(0))
#             p2_outputs.append(outputs.last_hidden_state[i, p2_ranges[i][0]:p2_ranges[i][1], :].mean(dim=0).unsqueeze(0))
#
#         p1_outputs = torch.cat(p1_outputs, dim=0)
#         p2_outputs = torch.cat(p2_outputs, dim=0)
#
#         reg_logits = self.regression_head(p1_outputs) * self.regression_scale  # Scale to 0-10 range
#         cls_logits = torch.nn.functional.cosine_similarity(p1_outputs, p2_outputs, dim=-1)
#         cls_logits = torch.clamp(cls_logits, min=1e-7, max=1)
#
#         return cls_logits, reg_logits
#     
#     def predict_regression(self, paragraph: str) -> float:
#         self.eval()
#         with torch.no_grad():
#             _, reg_logits = self([paragraph], ["None"])
#             return reg_logits.item()
#     
#     @classmethod
#     def load_model(cls, model_path):
#         model = cls(model_path)
#         return model

# TTCW test categories (14 tests for creative writing evaluation)
TTCW_TEST_CATEGORIES = [
    "Narrative Ending",
    "Understandability and Coherence",
    "Scene vs Summary",
    "Narrative Pacing",
    "Language Proficiency and Literary Devices",
    "Emotional Flexibility",
    "Structural Flexibility",
    "Perspective and Voice Flexibility",
    "Originality in Thought",
    "Originality in Form and Structure",
    "Originality in Theme and Content",
    "Rhetorical Complexity",
    "World Building and Setting",
    "Character Development",
]


class DomainFiction(DomainBase):
    def __init__(self):
        super().__init__("prompts/domain_fiction.txt")
        self.sample_type = "fiction"
        self.summary = "Creative short fiction stories evaluated by LLM judge for quality"
        self.description = "Creative fiction"
        self.file_format = [".txt"]
        self.domain_parser = "custom"
        self.category = "creative"

    def parse_context(self, context):
        text = list(context.values())[0] if context else ""
        return {"text": text}

    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        text = parsed["text"]
        words = len(text.split())
        paragraphs = len([p for p in text.split('\n\n') if p.strip()])
        return {
            "Words": words,
            "Paragraphs": paragraphs,
        }

    
    def prepare_prompt(self, current_context, target_state, edit_operation, **kwargs):
        prompt_populated = super().prepare_prompt(current_context, target_state, edit_operation, **kwargs)
        
        target_length = kwargs.get("target_length", None)
        if target_length is not None:
            import nltk
            context_str = stringify_context(current_context)
            current_length = len(nltk.word_tokenize(context_str))
            prompt_populated = prompt_populated.replace("[[TARGET_LENGTH]]", str(target_length)).replace("[[CURRENT_LENGTH]]", str(current_length))
        
        return prompt_populated
    
    # def load_wrqm_model(self):
    #     if self.wrqm_model is None:
    #         self.wrqm_model = MBertWQRM.load_model("Salesforce/WQRM")
    #     return self.wrqm_model
    
    def count_sentences(self, text):
        import nltk
        return len(nltk.sent_tokenize(text))
    
    def calculate_length_penalty(self, ratio):
        # 1.0 if within [90%, 110%] of target
        # At 200%, penalty = 0.75; at 300%, penalty = 0.56, etc.
        # Symmetric on lower end: at 50%, penalty = 0.75; at 33%, penalty = 0.56, etc.
        if ratio <= 0:
            return 0.0
        if 0.9 <= ratio <= 1.1:
            return 1.0
        elif ratio > 1.1:
            return 0.75 ** (ratio - 1)
        else:  # ratio < 0.9
            return 0.75 ** (1 / ratio - 1)
    
    def compute_and_cache_baseline_scores(self, sample_id):
        """Compute TTCW baseline scores for the original sample and cache them in sample.json."""
        sample_folder = f"{self.samples_folder}{sample_id}/"
        sample_path = os.path.join(sample_folder, "sample.json")
        with open(sample_path, "r") as f:
            sample = json.load(f)

        # Return cached scores if already present
        if "baseline_ttcw" in sample:
            return sample["baseline_ttcw"]

        # Load original fiction from start state
        start_state_id = sample["start_state"]
        start_state = [s for s in sample["states"] if s["state_id"] == start_state_id][0]
        original_context = build_context_from_folder(os.path.join(sample_folder, start_state["solution_folder"]))
        original_fiction = list(original_context.values())[0]

        # # Compute baseline WQRM (commented out to avoid GPU OOM)
        # model = self.load_wrqm_model()
        # baseline_wqrm = model.predict_regression(original_fiction)

        # Compute baseline TTCW
        ttcw_result = self.evaluate_ttcw_aspects(original_fiction)
        baseline_ttcw = ttcw_result["ttcw_normalized_score"]

        # Persist to sample.json
        sample["baseline_ttcw"] = baseline_ttcw
        with open(sample_path, "w") as f:
            json.dump(sample, f, indent=4)

        print(f"\033[92mCached baseline scores for {sample_id}: ttcw={baseline_ttcw:.4f}\033[0m")
        return baseline_ttcw

    def evaluate_ttcw_aspects(self, generated_fiction, model_name="t-gpt-5.2"):
        # Load batched evaluation prompt
        with open("prompts/domain_fiction_eval.txt", "r") as f:
            prompt_template = f.read().strip()
        
        # Populate the prompt
        prompt_populated = prompt_template.replace("[[STORY]]", generated_fiction)
        
        # Generate the batched response
        response = generate_json([{"role": "user", "content": prompt_populated}], model=model_name, max_tokens=16000)
        
        # Parse Likert scale responses (0-5)
        aspect_scores = []
        for i, category in enumerate(TTCW_TEST_CATEGORIES, 1):
            test_key = f"test{i}"
            test_response = response.get(test_key, 0)
            # Ensure score is numeric and in valid range
            try:
                score = int(test_response)
                score = max(0, min(5, score))
            except (ValueError, TypeError):
                score = 0
            aspect_scores.append({"aspect_name": category, "score": score})
        
        # Calculate normalized score (average score / 5 to get 0-1 range)
        avg_score = sum([s["score"] for s in aspect_scores]) / len(aspect_scores)
        normalized_score = avg_score / 5.0
        
        return {"ttcw_normalized_score": normalized_score, "ttcw_aspect_scores": aspect_scores}
    
    def evaluate_context(self, sample_id, generated_context, target_state):
        sample_folder = f"{self.samples_folder}{sample_id}/"
        with open(os.path.join(sample_folder, "sample.json"), "r") as f:
            sample = json.load(f)
        
        start_state_id = sample["start_state"]
        start_state = [state for state in sample["states"] if state["state_id"] == start_state_id][0]
        target_length = sample.get("target_length")
        
        original_context = build_context_from_folder(os.path.join(sample_folder, start_state["solution_folder"]))
        original_fiction = self.parse_context(original_context)["text"]
        generated_fiction = self.parse_context(generated_context)["text"]
        
        # Get baseline scores (cached in sample.json)
        baseline_ttcw = self.compute_and_cache_baseline_scores(sample_id)
        
        # # WQRM eval commented out to avoid GPU OOM
        # model = self.load_wrqm_model()
        # wqrm_raw = model.predict_regression(generated_fiction)
        
        levenshtein_ratio = SequenceMatcher(None, original_fiction, generated_fiction).ratio()
        
        original_word_count = len(original_fiction.split())
        generated_word_count = len(generated_fiction.split())
        
        # Length ratio relative to target_length
        word_count_ratio_pct = (generated_word_count / target_length) * 100 if target_length else (generated_word_count / original_word_count) * 100
        length_penalty = self.calculate_length_penalty(generated_word_count / target_length) if target_length else 1.0
        
        original_sentence_count = self.count_sentences(original_fiction)
        generated_sentence_count = self.count_sentences(generated_fiction)
        sentence_count_ratio_pct = (generated_sentence_count / original_sentence_count) * 100
        
        # # WQRM scoring commented out to avoid GPU OOM
        # wqrm_relative = min(1.0, max(0.0, wqrm_raw / baseline_wqrm)) if baseline_wqrm > 0 else 0.0
        # wqrm_score = min(1.0, max(0.0, wqrm_relative * length_penalty))

        evaluation_result = {"length_penalty": length_penalty, "levenshtein_ratio": levenshtein_ratio, "word_count_ratio_pct": word_count_ratio_pct, "sentence_count_ratio_pct": sentence_count_ratio_pct, "target_length": target_length, "generated_word_count": generated_word_count}
        
        ttcw_results = self.evaluate_ttcw_aspects(generated_fiction)
        # Normalize TTCW relative to baseline and clip to [0, 1]
        ttcw_relative = min(1.0, max(0.0, ttcw_results["ttcw_normalized_score"] / baseline_ttcw)) if baseline_ttcw > 0 else 0.0
        ttcw_results["ttcw_relative"] = ttcw_relative
        ttcw_results["baseline_ttcw"] = baseline_ttcw
        # Main score: relative TTCW penalized by length, clipped to [0, 1]
        ttcw_results["score"] = min(1.0, max(0.0, ttcw_relative * length_penalty))

        # print in blue
        # print(f"\033[94mgenerated_word_count: {generated_word_count}, target_length: {target_length}, length_penalty: {length_penalty}; ttcw_raw: {ttcw_results['ttcw_normalized_score']}, ttcw_relative: {ttcw_relative}, score: {ttcw_results['score']}\033[0m")
        evaluation_result.update(ttcw_results)        
        return evaluation_result

if __name__ == "__main__":
    # Example usage
    domain = DomainFiction()
    sample_id = "fiction1"
    generated_context = {"story": "Once upon a time, in a small village..."}
    target_state = None  # Not used in this example
    evaluation = domain.evaluate_context(sample_id, generated_context, target_state)
    print(json.dumps(evaluation, indent=2))
