"""GitHub Actions narration using Kokoro-82M, with optional VoiceStudio API support."""

from __future__ import annotations

import os
from pathlib import Path


def _generate_kokoro(text: str, output: Path) -> Path:
    """Synthesize narration with Kokoro directly on the GitHub runner."""
    try:
        import numpy as np
        import soundfile as sf
        from kokoro import KPipeline
    except ImportError as exc:
        raise RuntimeError(
            "Kokoro dependencies are missing. Install kokoro, torch, numpy and soundfile."
        ) from exc

    voice = os.environ.get("KOKORO_VOICE", "am_adam").strip() or "am_adam"
    speed = float(os.environ.get("KOKORO_SPEED", "0.94"))
    if not 0.5 <= speed <= 2.0:
        raise ValueError("KOKORO_SPEED must be between 0.5 and 2.0")
    language = "b" if voice.startswith("b") else "a"
    pipeline = KPipeline(lang_code=language)
    chunks = []
    for result in pipeline(text, voice=voice, speed=speed, split_pattern=r"\\n+"):
        audio = result.audio
        if audio is None:
            continue
        if hasattr(audio, "detach"):
            audio = audio.detach().cpu().numpy()
        chunks.append(np.asarray(audio).reshape(-1))
    if not chunks:
        raise RuntimeError("Kokoro returned no audio.")
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output), np.concatenate(chunks), 24000)
    return output


def _generate_voicestudio(text: str, output: Path) -> Path:
    """Optional remote VoiceStudio server; used only when explicitly configured."""
    import json
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, urlopen

    base_url = os.environ.get("VOICESTUDIO_BASE_URL", "").strip().rstrip("/")
    api_key = os.environ.get("VOICESTUDIO_API_KEY", "").strip()
    if not base_url or not api_key:
        raise RuntimeError("VoiceStudio remote mode needs VOICESTUDIO_BASE_URL and VOICESTUDIO_API_KEY.")
    voice = os.environ.get("VOICESTUDIO_VOICE", "default").strip() or "default"
    model = os.environ.get("VOICESTUDIO_MODEL", "tts-1").strip() or "tts-1"
    speed = float(os.environ.get("VOICESTUDIO_SPEED", "0.92"))
    request = Request(
        f"{base_url}/audio/speech",
        data=json.dumps({
            "model": model, "voice": voice, "input": text,
            "response_format": "wav", "speed": speed,
            "instruct": "Deep, cinematic male documentary narration; resonant, controlled, clear.",
        }).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=300) as response:
            audio = response.read()
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"VoiceStudio request failed: {exc}") from exc
    if not audio:
        raise RuntimeError("VoiceStudio returned an empty audio file.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(audio)
    return output


def generate_voiceover(text: str, output: str | Path) -> Path:
    """Generate narration; Kokoro is the GitHub-native default."""
    narration = text.strip()
    if not narration:
        raise ValueError("Narration text cannot be empty")
    output_path = Path(output)
    backend = os.environ.get("VOICE_BACKEND", "kokoro").strip().lower()
    if backend == "voicestudio":
        return _generate_voicestudio(narration, output_path)
    if backend != "kokoro":
        raise ValueError("VOICE_BACKEND must be 'kokoro' or 'voicestudio'.")
    return _generate_kokoro(narration, output_path)
