"""
Domain: Audio
Evaluates round-trip audio editing using perceptual similarity metrics.

Context format:
    {"clip.wav": "<base64-encoded WAV data>"}

The domain overrides run_single_step_edit to use the generate_audio API
instead of the text ChatCompletion endpoint.

Evaluation combines:
    - Mel-spectrogram SSIM (structural similarity in time-frequency space)
    - Chroma correlation (harmonic / pitch content fidelity)
    - Sample-level RMSE (raw waveform similarity)
"""

import base64, io, os, tempfile
import numpy as np
from domains.domain_base import DomainBase
from utils_context import build_context_from_folder, is_context_complete


# ---------------------------------------------------------------------------
# Audio I/O helpers
# ---------------------------------------------------------------------------

AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg"}


def _is_audio_file(filename):
    return os.path.splitext(filename)[1].lower() in AUDIO_EXTENSIONS


def load_audio_context_from_folder(folder_path):
    """Load audio files as base64 strings, text files as text."""
    context = {}
    for filename in sorted(os.listdir(folder_path)):
        file_path = os.path.join(folder_path, filename)
        if os.path.isdir(file_path):
            continue
        if _is_audio_file(filename):
            with open(file_path, "rb") as f:
                context[filename] = base64.b64encode(f.read()).decode("ascii")
        else:
            with open(file_path, "r") as f:
                context[filename] = f.read()
    return context


def _b64_to_audio(b64_string, sr=22050):
    """Decode base64 audio → (numpy_array, sample_rate) via soundfile."""
    import soundfile as sf
    data, file_sr = sf.read(io.BytesIO(base64.b64decode(b64_string)))
    # Convert stereo to mono by averaging channels
    if data.ndim > 1:
        data = np.mean(data, axis=1)
    return data.astype(np.float64), file_sr


def _match_length(ref, gen):
    """Pad or trim gen to match ref length."""
    if len(gen) >= len(ref):
        return gen[:len(ref)]
    return np.pad(gen, (0, len(ref) - len(gen)), mode="constant")


def _peak_normalize(audio):
    """Peak-normalize to [-1, 1]."""
    peak = np.max(np.abs(audio))
    if peak > 0:
        return audio / peak
    return audio


# ---------------------------------------------------------------------------
# Evaluation metrics
# ---------------------------------------------------------------------------

def compute_mel_ssim(ref_audio, gen_audio, sr):
    """SSIM on log-mel spectrograms (structural similarity in time-frequency)."""
    import librosa
    from skimage.metrics import structural_similarity

    n_fft = 2048
    hop = 512
    n_mels = 128

    ref_mel = librosa.power_to_db(
        librosa.feature.melspectrogram(y=ref_audio, sr=sr, n_fft=n_fft, hop_length=hop, n_mels=n_mels),
        ref=np.max,
    )
    gen_mel = librosa.power_to_db(
        librosa.feature.melspectrogram(y=gen_audio, sr=sr, n_fft=n_fft, hop_length=hop, n_mels=n_mels),
        ref=np.max,
    )

    # Trim to same number of time frames
    min_frames = min(ref_mel.shape[1], gen_mel.shape[1])
    ref_mel = ref_mel[:, :min_frames]
    gen_mel = gen_mel[:, :min_frames]

    data_range = ref_mel.max() - ref_mel.min()
    if data_range == 0:
        return 1.0 if np.array_equal(ref_mel, gen_mel) else 0.0

    # win_size must be odd and ≤ smallest dimension
    min_dim = min(ref_mel.shape[0], ref_mel.shape[1])
    win_size = min(7, min_dim)
    if win_size % 2 == 0:
        win_size -= 1
    if win_size < 3:
        return 1.0 if np.allclose(ref_mel, gen_mel, atol=1e-3) else 0.0

    score = structural_similarity(ref_mel, gen_mel, data_range=data_range, win_size=win_size)
    return max(0.0, float(score))


def compute_chroma_similarity(ref_audio, gen_audio, sr):
    """Chroma feature correlation (harmonic / pitch content fidelity)."""
    import librosa

    ref_chroma = librosa.feature.chroma_stft(y=ref_audio, sr=sr, n_fft=2048, hop_length=512)
    gen_chroma = librosa.feature.chroma_stft(y=gen_audio, sr=sr, n_fft=2048, hop_length=512)

    # Trim to same number of time frames
    min_frames = min(ref_chroma.shape[1], gen_chroma.shape[1])
    ref_chroma = ref_chroma[:, :min_frames]
    gen_chroma = gen_chroma[:, :min_frames]

    # Flatten and compute correlation
    ref_flat = ref_chroma.flatten()
    gen_flat = gen_chroma.flatten()

    if np.std(ref_flat) == 0 or np.std(gen_flat) == 0:
        return 1.0 if np.allclose(ref_flat, gen_flat, atol=1e-6) else 0.0

    corr = np.corrcoef(ref_flat, gen_flat)[0, 1]
    return max(0.0, float(corr))


def compute_sample_similarity(ref_audio, gen_audio):
    """1 - RMSE * 2.5, clamped to [0,1]. Mirrors image pixel similarity."""
    ref_norm = _peak_normalize(ref_audio)
    gen_norm = _peak_normalize(gen_audio)
    gen_norm = _match_length(ref_norm, gen_norm)
    rmse = np.sqrt(np.mean((ref_norm - gen_norm) ** 2))
    return max(0.0, 1.0 - rmse * 2.5)


def compute_duration_similarity(ref_audio, gen_audio, sr):
    """Ratio of shorter to longer duration. Penalises cropping and padding."""
    ref_dur = len(ref_audio) / sr
    gen_dur = len(gen_audio) / sr
    if max(ref_dur, gen_dur) == 0:
        return 1.0
    return min(ref_dur, gen_dur) / max(ref_dur, gen_dur)


# ---------------------------------------------------------------------------
# Domain class
# ---------------------------------------------------------------------------

class DomainAudio(DomainBase):
    supports_visual = True

    def __init__(self):
        super().__init__("prompts/domain_audio.txt")
        self.sample_type = "audio"
        self.description = "audio editing"
        self.file_format = [".wav", ".mp3"]
        self.domain_parser = "librosa"
        self.category = "audio"

    # ------------------------------------------------------------------
    # Context helpers
    # ------------------------------------------------------------------

    def parse_context(self, context):
        """Parse context dict → dict of {filename: (np_array, sample_rate)}."""
        audios = {}
        for filename, content in context.items():
            if _is_audio_file(filename):
                audios[filename] = _b64_to_audio(content)
        return audios

    def compute_domain_statistics(self, context):
        parsed = self.parse_context(context)
        stats = {"num_audio_files": len(parsed)}
        for fname, (audio, sr) in parsed.items():
            duration = len(audio) / sr
            stats[f"{fname}_duration"] = f"{duration:.2f}s"
            stats[f"{fname}_sample_rate"] = sr
            stats[f"{fname}_rms"] = f"{np.sqrt(np.mean(audio ** 2)):.4f}"
        return stats

    def render_context_visual(self, context, outfile):
        """Render the first audio file as a waveform + spectrogram plot."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import librosa
        import librosa.display

        parsed = self.parse_context(context)
        if not parsed:
            return None
        fname = next(iter(parsed))
        audio, sr = parsed[fname]

        fig, axes = plt.subplots(2, 1, figsize=(10, 6))

        # Waveform
        librosa.display.waveshow(audio, sr=sr, ax=axes[0])
        axes[0].set_title(f"Waveform — {fname}")

        # Mel spectrogram
        mel = librosa.power_to_db(
            librosa.feature.melspectrogram(y=audio, sr=sr, n_fft=2048, hop_length=512, n_mels=128),
            ref=np.max,
        )
        librosa.display.specshow(mel, sr=sr, hop_length=512, x_axis="time", y_axis="mel", ax=axes[1])
        axes[1].set_title("Mel Spectrogram")

        plt.tight_layout()
        out_path = outfile + ".png"
        fig.savefig(out_path, dpi=100)
        plt.close(fig)
        return out_path

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate_context(self, sample_id, generated_context, target_state):
        """Compare generated audio against reference audio from solution folder."""
        if "solution_folder" not in target_state:
            return {}
        solution_folder = os.path.join("samples", sample_id, target_state["solution_folder"])
        reference_context = load_audio_context_from_folder(solution_folder)

        # Find audio files in both contexts
        ref_audios = {f: _b64_to_audio(c) for f, c in reference_context.items() if _is_audio_file(f)}
        gen_audios = {f: _b64_to_audio(c) for f, c in generated_context.items() if _is_audio_file(f)}

        if not ref_audios or not gen_audios:
            return {"error": "no_audio", "score": 0.0}

        # Match by filename; fall back to first file if names differ
        ref_fname = next(iter(ref_audios))
        ref_audio, ref_sr = ref_audios[ref_fname]

        gen_fname = ref_fname if ref_fname in gen_audios else next(iter(gen_audios))
        gen_audio, gen_sr = gen_audios[gen_fname]

        # Resample generated to match reference sample rate
        if gen_sr != ref_sr:
            import librosa
            gen_audio = librosa.resample(gen_audio, orig_sr=gen_sr, target_sr=ref_sr)
            gen_sr = ref_sr

        # Match lengths for sample-level comparison
        gen_audio_matched = _match_length(ref_audio, gen_audio)

        mel_ssim = compute_mel_ssim(ref_audio, gen_audio_matched, ref_sr)
        chroma = compute_chroma_similarity(ref_audio, gen_audio_matched, ref_sr)
        sample = compute_sample_similarity(ref_audio, gen_audio_matched)
        duration = compute_duration_similarity(ref_audio, gen_audio, ref_sr)

        raw_score = 0.50 * mel_ssim + 0.25 * chroma + 0.25 * sample
        score = raw_score * duration

        ref_dur = len(ref_audio) / ref_sr
        gen_dur = len(gen_audio) / gen_sr  # use original gen_audio length

        return {
            "score": float(score),
            "raw_score": float(raw_score),
            "mel_ssim": float(mel_ssim),
            "chroma_similarity": float(chroma),
            "sample_similarity": float(sample),
            "duration_similarity": float(duration),
            "ref_duration": f"{ref_dur:.2f}s",
            "gen_duration": f"{gen_dur:.2f}s",
            "ref_sample_rate": ref_sr,
            "error": "no_error",
        }

    # ------------------------------------------------------------------
    # LLM execution  (overrides base class)
    # ------------------------------------------------------------------

    def run_single_step_edit(self, sample_id, model_name, current_context, target_state,
                             edit_operation, printing=True, trapi_instance=None, **kwargs):
        """Use the generate_audio API instead of text chat completion.

        Flow:
            1. Write input audio to a temp file.
            2. Call generate_audio with the audio + edit prompt.
            3. Read the output audio, wrap it back into a context dict as base64.
            4. Run evaluate_context against the reference.
        """
        raise NotImplementedError("Audio domain requires a generate_audio() provider not included in this release")

        # --- extract input audio and write to temp file ---
        audio_filenames = [f for f in current_context if _is_audio_file(f)]
        if not audio_filenames:
            return "", {"error": "no_input_audio", "score": 0.0}, {}
        input_filename = audio_filenames[0]
        input_b64 = current_context[input_filename]

        with tempfile.TemporaryDirectory() as tmpdir:
            # Write input audio to disk for generate_audio
            input_path = os.path.join(tmpdir, "input.wav")
            with open(input_path, "wb") as f:
                f.write(base64.b64decode(input_b64))

            # Build multimodal message
            messages = [{"role": "user", "content": [
                {"type": "audio", "path": input_path},
                {"type": "text", "text": edit_operation},
            ]}]

            output = generate_audio(
                messages,
                model=model_name,
                return_metadata=True,
                output_dir=tmpdir,
            )

            # Read the generated audio back as base64
            if not output.get("audio_files"):
                return "", {"error": "no_output_audio", "score": 0.0}, {}

            out_path = output["audio_files"][0]
            with open(out_path, "rb") as f:
                output_b64 = base64.b64encode(f.read()).decode("ascii")

        # --- determine target filename ---
        target_filenames = target_state["context"]
        target_audio_files = [f for f in target_filenames if _is_audio_file(f)]
        output_filename = target_audio_files[0] if target_audio_files else input_filename

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
            print(f"  [audio] edit completed in {elapsed:.1f}s")

        # --- evaluate ---
        target_context = target_state["context"]
        if not is_context_complete(generated_context, target_context):
            evaluation_result = {"error": "context_mismatch",
                                 "detailed_error": "One or more files are missing from the generated context."}
        else:
            evaluation_result = self.evaluate_context(sample_id, generated_context, target_state)

        return llm_response, evaluation_result, llm_metadata
