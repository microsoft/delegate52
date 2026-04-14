"""
Dataset export/import utilities.

Provides:
- export_samples(): folder of samples → JSONL file
- import_samples(): JSONL file → folder of samples
- resolve_input_path(): resolve a folder or JSONL path to a samples folder on disk

JSONL schema (one JSON object per line):
{
    "sample_id": "accounting1",
    "sample_type": "accounting",
    "sample_name": "Hack Club Expense Ledger",
    "metadata": { ... all other sample.json fields except "states" ... },
    "states": [ ... ],
    "files": {
        "basic_state/hack_club.ledger": "...",
        "distractor_context/fund_accounting.md": "...",
        ...
    }
}
"""

import json
import os
import glob

# HuggingFace dataset identifier
HF_DATASET_ID = "microsoft/delegate52"
HF_DATASET_FILENAME = "delegate52.jsonl"

# Files and directories to skip during export
_SKIP_DIRS = {"__pycache__"}
_SKIP_FILE_PATTERNS = {".pyc", ".bak."}

# Fields that get promoted to top-level in the JSONL row
_TOP_LEVEL_FIELDS = {"sample_id", "sample_type", "sample_name", "states"}


def _should_skip_file(filename):
    """Check if a file should be excluded from export."""
    for pattern in _SKIP_FILE_PATTERNS:
        if pattern in filename:
            return True
    return False


def _collect_sample_files(sample_dir):
    """Walk a sample directory and collect all files as {relative_path: content}.
    Skips __pycache__, .pyc, .bak.* files, and sample.json itself."""
    files = {}
    for root, dirs, filenames in os.walk(sample_dir):
        # Prune skipped directories
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]

        for fn in filenames:
            if fn == "sample.json":
                continue
            if _should_skip_file(fn):
                continue
            fp = os.path.join(root, fn)
            rel_path = os.path.relpath(fp, sample_dir)
            try:
                with open(fp, "r") as f:
                    files[rel_path] = f.read()
            except UnicodeDecodeError:
                import base64
                with open(fp, "rb") as f:
                    files[rel_path] = "base64:" + base64.b64encode(f.read()).decode("ascii")
    return files


def export_samples(samples_folder, output_path, only_redistributable=True, skip_domains=None):
    """Export samples from a folder into a JSONL file.

    Args:
        samples_folder: Path to the root samples directory (e.g. "samples/").
        output_path: Path for the output JSONL file.
        only_redistributable: If True, only include samples with ok_to_redistribute="yes".
        skip_domains: Set of domain names to exclude (e.g. {"image", "audio"}).
    
    Returns:
        Number of samples exported.
    """
    if skip_domains is None:
        skip_domains = set()

    sample_dirs = sorted(glob.glob(os.path.join(samples_folder, "*", "sample.json")))
    count = 0

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as out_f:
        for sample_json_path in sample_dirs:
            sample_dir = os.path.dirname(sample_json_path)
            sample_id = os.path.basename(sample_dir)

            with open(sample_json_path, "r") as f:
                sample = json.load(f)

            sample_type = sample.get("sample_type", "")

            if sample_type in skip_domains:
                continue

            if only_redistributable and sample.get("ok_to_redistribute") != "yes":
                continue

            # Build JSONL row
            row = {
                "sample_id": sample.get("sample_id", sample_id),
                "sample_type": sample_type,
                "sample_name": sample.get("sample_name", ""),
                "states": sample.get("states", []),
                "metadata": {k: v for k, v in sample.items() if k not in _TOP_LEVEL_FIELDS},
                "files": _collect_sample_files(sample_dir),
            }

            out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1

    return count


def import_samples(dataset_path, output_folder):
    """Import samples from a JSONL file into a folder structure.

    Recreates the original directory layout:
        output_folder/
            sample_id/
                sample.json
                basic_state/...
                distractor_context/...

    Args:
        dataset_path: Path to the JSONL file.
        output_folder: Root folder to write sample directories into.
    
    Returns:
        Number of samples imported.
    """
    count = 0
    with open(dataset_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            sample_id = row["sample_id"]
            sample_dir = os.path.join(output_folder, sample_id)
            os.makedirs(sample_dir, exist_ok=True)

            # Reconstruct sample.json from row
            sample_json = dict(row.get("metadata", {}))
            for field in _TOP_LEVEL_FIELDS:
                if field in row:
                    sample_json[field] = row[field]

            with open(os.path.join(sample_dir, "sample.json"), "w") as sf:
                json.dump(sample_json, sf, indent=4, ensure_ascii=False)

            # Write all files
            for rel_path, content in row.get("files", {}).items():
                fp = os.path.join(sample_dir, rel_path)
                os.makedirs(os.path.dirname(fp), exist_ok=True)
                with open(fp, "w") as wf:
                    wf.write(content)

            count += 1
    return count


def _download_from_huggingface():
    """Download the dataset JSONL from HuggingFace Hub.

    Requires `huggingface_hub` to be installed. For private repos, set the
    HF_TOKEN environment variable to a valid Hugging Face access token.

    Returns:
        Path to the downloaded JSONL file.
    """
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        raise ImportError(
            "huggingface_hub is required to download the dataset. "
            "Install it with: pip install huggingface_hub"
        )

    print(f"Downloading {HF_DATASET_ID} from Hugging Face...")
    local_path = hf_hub_download(
        repo_id=HF_DATASET_ID,
        filename=HF_DATASET_FILENAME,
        repo_type="dataset",
    )
    print(f"Downloaded to: {local_path}")
    return local_path


def resolve_input_path(input_path=None):
    """Resolve an input path (folder, JSONL, or HuggingFace) to a samples folder on disk.

    - If input_path is a directory, returns it as-is.
    - If input_path is a .jsonl file, auto-imports it to .cache/samples_<name>/.
    - If input_path is None or "huggingface", downloads from HuggingFace Hub
      and then imports the JSONL.

    For private HuggingFace repos, set the HF_TOKEN environment variable.

    Returns:
        (samples_folder, was_jsonl) — the folder path and whether import occurred.
    """
    # Download from HuggingFace if no local path provided
    if input_path is None or input_path == "huggingface":
        input_path = _download_from_huggingface()

    if input_path.endswith(".jsonl") and os.path.isfile(input_path):
        cache_name = os.path.splitext(os.path.basename(input_path))[0]
        samples_folder = os.path.join(".cache", f"samples_{cache_name}")
        if os.path.isdir(samples_folder):
            print(f"Using cached import: {samples_folder}")
        else:
            print(f"Importing {input_path} → {samples_folder} ...")
            n = import_samples(input_path, samples_folder)
            print(f"Imported {n} samples")
        return samples_folder, True
    else:
        return input_path, False


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Export/import benchmark samples between folder and JSONL formats.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- export ---
    p_export = subparsers.add_parser("export", help="Export samples from a folder into a JSONL file.")
    p_export.add_argument("--samples_folder", default="samples/", help="Root folder containing sample directories (default: samples/).")
    p_export.add_argument("--output", default="work/dataset.jsonl", help="Output JSONL file path (default: work/dataset.jsonl).")
    p_export.add_argument("--all", action="store_true", help="Include all samples (ignore ok_to_redistribute).")
    p_export.add_argument("--skip_domains", nargs="*", default=["image", "audio"], help="Domain names to exclude (default: image, audio). Use --skip_domains with no args to skip nothing.")

    # --- import ---
    p_import = subparsers.add_parser("import", help="Import samples from a JSONL file into a folder structure.")
    p_import.add_argument("--input", required=True, help="Input JSONL file path.")
    p_import.add_argument("--output_folder", default="samples_imported/", help="Output folder for sample directories (default: samples_imported/).")

    args = parser.parse_args()

    if args.command == "export":
        skip = set(args.skip_domains) if args.skip_domains else set()
        n = export_samples(
            args.samples_folder,
            args.output,
            only_redistributable=not args.all,
            skip_domains=skip,
        )
        print(f"Exported {n} samples → {args.output}")

    elif args.command == "import":
        n = import_samples(args.input, args.output_folder)
        print(f"Imported {n} samples → {args.output_folder}")


if __name__ == "__main__":
    main()
