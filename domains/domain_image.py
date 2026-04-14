"""
Domain: Image
Evaluates round-trip image editing using perceptual similarity metrics.

Context format:
    {"image.png": "<base64-encoded PNG data>"}

The domain overrides run_single_step_edit to use the OpenAI images.edit API
(gpt-image-1) instead of the text ChatCompletion endpoint.

Evaluation combines:
    - SSIM (structural similarity)
    - Histogram correlation (color distribution fidelity)
    - Pixel-level MSE (inverted, normalised to [0,1])
"""

import base64, io, os, tempfile
import numpy as np
from domains.domain_base import DomainBase
from utils_context import build_context_from_folder, is_context_complete


# ---------------------------------------------------------------------------
# Image I/O helpers
# ---------------------------------------------------------------------------

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}


def _is_image_file(filename):
    return os.path.splitext(filename)[1].lower() in IMAGE_EXTENSIONS


def load_image_context_from_folder(folder_path):
    """Load image files as base64 strings, text files as text."""
    context = {}
    for filename in sorted(os.listdir(folder_path)):
        file_path = os.path.join(folder_path, filename)
        if os.path.isdir(file_path):
            continue
        if _is_image_file(filename):
            with open(file_path, "rb") as f:
                context[filename] = base64.b64encode(f.read()).decode("ascii")
        else:
            with open(file_path, "r") as f:
                context[filename] = f.read()
    return context


def _b64_to_pil(b64_string):
    from PIL import Image
    return Image.open(io.BytesIO(base64.b64decode(b64_string)))


def _pil_to_np(img, grayscale=False):
    """Convert PIL Image to numpy array, optionally as grayscale float."""
    if grayscale:
        return np.array(img.convert("L"), dtype=np.float64)
    return np.array(img.convert("RGB"), dtype=np.float64)


def _resize_to_match(img, target_size):
    """Resize PIL Image to target (width, height) using high-quality resampling."""
    from PIL import Image
    if img.size != target_size:
        return img.resize(target_size, Image.LANCZOS)
    return img


# ---------------------------------------------------------------------------
# Evaluation metrics
# ---------------------------------------------------------------------------

def compute_ssim(ref_img, gen_img):
    """Structural similarity index (scikit-image) on RGB channels."""
    from skimage.metrics import structural_similarity
    ref_rgb = _pil_to_np(ref_img)
    gen_rgb = _pil_to_np(gen_img)
    score = structural_similarity(ref_rgb, gen_rgb, data_range=255.0, channel_axis=-1)
    return max(0.0, score)


def compute_histogram_similarity(ref_img, gen_img, bins=64):
    """Histogram correlation in HSV space (OpenCV)."""
    import cv2
    ref_hsv = cv2.cvtColor(np.array(ref_img.convert("RGB")), cv2.COLOR_RGB2HSV)
    gen_hsv = cv2.cvtColor(np.array(gen_img.convert("RGB")), cv2.COLOR_RGB2HSV)

    correlations = []
    for ch in range(3):
        ref_hist = cv2.calcHist([ref_hsv], [ch], None, [bins], [0, 256])
        gen_hist = cv2.calcHist([gen_hsv], [ch], None, [bins], [0, 256])
        cv2.normalize(ref_hist, ref_hist)
        cv2.normalize(gen_hist, gen_hist)
        corr = cv2.compareHist(ref_hist, gen_hist, cv2.HISTCMP_CORREL)
        correlations.append(max(0.0, corr))
    return float(np.mean(correlations))


def compute_pixel_similarity(ref_img, gen_img):
    """1 - RMSE*2.5, clamped to [0,1].  More sensitive than raw 1-MSE."""
    ref_arr = _pil_to_np(ref_img) / 255.0
    gen_arr = _pil_to_np(gen_img) / 255.0
    rmse = np.sqrt(np.mean((ref_arr - gen_arr) ** 2))
    return max(0.0, 1.0 - rmse * 2.5)


# ---------------------------------------------------------------------------
# Domain class
# ---------------------------------------------------------------------------

class DomainImage(DomainBase):
    supports_visual = True

    def __init__(self):
        super().__init__("prompts/domain_image.txt")
        self.sample_type = "image"
        self.description = "image editing"
        self.file_format = [".png", ".jpg"]
        self.domain_parser = "pillow"
        self.category = "visual"

    # ------------------------------------------------------------------
    # Context helpers
    # ------------------------------------------------------------------

    def parse_context(self, context):
        """Parse context dict → list of PIL Images."""
        from PIL import Image
        images = {}
        for filename, content in context.items():
            if _is_image_file(filename):
                images[filename] = _b64_to_pil(content)
        return images

    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        stats = {"num_images": len(parsed)}
        for fname, img in parsed.items():
            stats[f"{fname}_size"] = f"{img.width}x{img.height}"
        return stats

    def render_context_visual(self, context, outfile):
        """Save the first image in the context to outfile.png."""
        parsed = self.parse_context(context)
        if not parsed:
            return None
        img = next(iter(parsed.values()))
        out_path = outfile + ".png"
        img.save(out_path)
        return out_path

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate_context(self, sample_id, generated_context, target_state):
        """Compare generated image against reference image from solution folder."""
        if "solution_folder" not in target_state:
            return {}
        solution_folder = os.path.join("samples", sample_id, target_state["solution_folder"])
        reference_context = load_image_context_from_folder(solution_folder)

        # Find the image file in both contexts
        ref_images = {f: _b64_to_pil(c) for f, c in reference_context.items() if _is_image_file(f)}
        gen_images = {f: _b64_to_pil(c) for f, c in generated_context.items() if _is_image_file(f)}

        if not ref_images or not gen_images:
            return {"error": "no_images", "score": 0.0}

        # Match by filename; fall back to first image if names differ
        ref_fname = next(iter(ref_images))
        ref_img = ref_images[ref_fname]

        gen_fname = ref_fname if ref_fname in gen_images else next(iter(gen_images))
        gen_img = gen_images[gen_fname]

        # Resize generated to match reference dimensions
        gen_img = _resize_to_match(gen_img, ref_img.size)

        ssim = compute_ssim(ref_img, gen_img)
        histogram = compute_histogram_similarity(ref_img, gen_img)
        pixel = compute_pixel_similarity(ref_img, gen_img)

        score = 0.50 * ssim + 0.25 * histogram + 0.25 * pixel

        return {
            "score": float(score),
            "ssim": float(ssim),
            "histogram_similarity": float(histogram),
            "pixel_similarity": float(pixel),
            "ref_size": f"{ref_img.width}x{ref_img.height}",
            "gen_size": f"{gen_img.width}x{gen_img.height}",
            "error": "no_error",
        }

    # ------------------------------------------------------------------
    # LLM execution  (overrides base class)
    # ------------------------------------------------------------------

    def run_single_step_edit(self, sample_id, model_name, current_context, target_state,
                             edit_operation, printing=True, trapi_instance=None, **kwargs):
        """Use the generate_image API instead of text chat completion.

        Flow:
            1. Write input image to a temp file.
            2. Call generate_image with the image + edit prompt.
            3. Read the output image, wrap it back into a context dict as base64.
            4. Run evaluate_context against the reference.
        """
        raise NotImplementedError("Image domain requires a generate_image() provider not included in this release")
        from PIL import Image

        # --- extract input image and write to temp file ---
        image_filenames = [f for f in current_context if _is_image_file(f)]
        if not image_filenames:
            return "", {"error": "no_input_image", "score": 0.0}, {}
        input_filename = image_filenames[0]
        input_b64 = current_context[input_filename]

        with tempfile.TemporaryDirectory() as tmpdir:
            # Write input image to disk for generate_image
            input_path = os.path.join(tmpdir, "input.png")
            with open(input_path, "wb") as f:
                f.write(base64.b64decode(input_b64))

            # Build multimodal message
            messages = [{"role": "user", "content": [
                {"type": "image", "path": input_path},
                {"type": "text", "text": edit_operation},
            ]}]

            output = generate_image(
                messages,
                model=model_name,
                return_metadata=True,
                output_dir=tmpdir,
            )

            # Read the generated image back as base64
            if not output.get("images"):
                return "", {"error": "no_output_image", "score": 0.0}, {}

            out_path = output["images"][0]
            with open(out_path, "rb") as f:
                output_b64 = base64.b64encode(f.read()).decode("ascii")

        # --- determine target filename ---
        target_filenames = target_state["context"]
        target_image_files = [f for f in target_filenames if _is_image_file(f)]
        output_filename = target_image_files[0] if target_image_files else input_filename

        # Build context dict and a text representation for the result log
        generated_context = {output_filename: output_b64}
        llm_response = f"```{output_filename}\n{output_b64}```"

        llm_metadata = {
            "latency": output.get("elapsed_time"),
            "prompt_tokens": output.get("prompt_tokens"),
            "completion_tokens": output.get("completion_tokens"),
            "reasoning_tokens": None,
            "total_tokens": output.get("total_tokens"),
            "total_usd": output.get("total_usd"),
        }

        if printing:
            elapsed = output.get("elapsed_time", 0)
            print(f"  [image] edit completed in {elapsed:.1f}s")

        # --- evaluate ---
        target_context = target_state["context"]
        if not is_context_complete(generated_context, target_context):
            evaluation_result = {"error": "context_mismatch",
                                 "detailed_error": "One or more files are missing from the generated context."}
        else:
            evaluation_result = self.evaluate_context(sample_id, generated_context, target_state)
            # print the score in blue
            score = evaluation_result.get("score", 0.0)
            print(f"  [image] evaluation score: \033[94m{score:.2f}\033[0m")


        return llm_response, evaluation_result, llm_metadata
