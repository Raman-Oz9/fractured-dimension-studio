"""Offline narration generation using the Piper command-line voice engine."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def generate_voiceover(text: str, output: str | Path) -> Path:
    """Synthesize narration with the configured local Piper ONNX voice."""
    narration = text.strip()
    if not narration:
        raise ValueError("Narration text cannot be empty")

    model = os.environ.get("PIPER_MODEL_PATH", "").strip()
    if not model:
        raise RuntimeError("Narration is configured but PIPER_MODEL_PATH is not set.")
    model_path = Path(model)
    if not model_path.is_file():
        raise FileNotFoundError(f"Piper voice model not found: {model_path}")
    executable = shutil.which("piper")
    if executable is None:
        raise RuntimeError("Piper TTS is not installed. Install the 'audio' extra.")

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [executable, "--model", str(model_path), "--output_file", str(output_path)],
        input=narration,
        text=True,
        check=True,
        capture_output=True,
    )
    return output_path
