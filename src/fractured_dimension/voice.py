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
    for result in pipeline(text, voice=voice, speed=speed, split_pattern=r"\n+"):
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


def _trim_silence(audio, rate: int = 24000, threshold: float = 0.012, pad: float = 0.04):
    """Trim leading/trailing silence so each narration line starts and ends tightly."""
    import numpy as np

    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    loud = np.flatnonzero(np.abs(audio) > threshold)
    if loud.size == 0:
        return audio
    start = max(0, int(loud[0]) - int(pad * rate))
    end = min(audio.size, int(loud[-1]) + int(pad * rate))
    return audio[start:end]


def _write_wav(path: Path, audio, rate: int = 24000) -> Path:
    import wave

    import numpy as np

    pcm = (np.clip(np.asarray(audio, dtype=np.float32), -1, 1) * 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())
    return path


def _test_tone_line(text: str, output: Path) -> Path:
    """Offline stand-in for speech used by tests and local previews (VOICE_BACKEND=test-tone)."""
    import numpy as np

    words = max(1, len(text.split()))
    rate = 24000
    parts = []
    for index in range(words):
        t = np.arange(int(rate * 0.26)) / rate
        parts.append(0.25 * np.sin(2 * np.pi * (180 + 12 * (index % 5)) * t) * np.hanning(t.size))
        parts.append(np.zeros(int(rate * 0.07), dtype=np.float32))
    return _write_wav(output, np.concatenate(parts), rate)


def deepen_voice(path: Path, semitones: float) -> Path:
    """Lower the narrator's pitch and formants, add chest warmth and gentle compression.

    Resampling down makes the voice sound bigger (a longer vocal tract); atempo restores the
    original pacing so the line keeps its length.
    """
    import shutil
    import subprocess

    if semitones <= 0 or shutil.which("ffmpeg") is None:
        return path
    factor = 2 ** (-semitones / 12)
    tmp = path.with_suffix(".deep.wav")
    chain = (
        f"asetrate=24000*{factor:.5f},aresample=24000,atempo={1 / factor:.5f},"
        "equalizer=f=105:t=h:w=160:g=4,equalizer=f=250:t=q:w=1:g=1.5,equalizer=f=7500:t=h:w=2000:g=-3,"
        "acompressor=threshold=-21dB:ratio=3:attack=6:release=90:makeup=2"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(path), "-af", chain, "-ac", "1", "-ar", "24000",
         "-c:a", "pcm_s16le", str(tmp)],
        check=True, capture_output=True,
    )
    tmp.replace(path)
    return path


def generate_voice_lines(lines: list[str], out_dir: str | Path, prefix: str = "line") -> list[Path]:
    """Synthesize one WAV per narration line, reusing a single Kokoro pipeline.

    Per-line audio is what lets every shot be cut to the exact length of the words
    spoken over it, so picture and narration can never drift apart.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    texts = [line.strip() for line in lines]
    if any(not t for t in texts):
        raise ValueError("Every shot needs a non-empty narration line")
    backend = os.environ.get("VOICE_BACKEND", "kokoro").strip().lower()
    paths = [out / f"{prefix}-{i:03d}.wav" for i in range(1, len(texts) + 1)]
    if backend == "test-tone":
        return [_test_tone_line(t, p) for t, p in zip(texts, paths)]
    if backend == "voicestudio":
        return [_generate_voicestudio(t, p) for t, p in zip(texts, paths)]
    if backend != "kokoro":
        raise ValueError("VOICE_BACKEND must be 'kokoro', 'voicestudio' or 'test-tone'.")
    try:
        import numpy as np
        from kokoro import KPipeline
    except ImportError as exc:
        raise RuntimeError(
            "Kokoro dependencies are missing. Install kokoro, torch, numpy and soundfile."
        ) from exc
    voice = os.environ.get("KOKORO_VOICE", "am_adam").strip() or "am_adam"
    speed = float(os.environ.get("KOKORO_SPEED", "0.94"))
    if not 0.5 <= speed <= 2.0:
        raise ValueError("KOKORO_SPEED must be between 0.5 and 2.0")
    pipeline = KPipeline(lang_code="b" if voice.startswith("b") else "a")
    for text, path in zip(texts, paths):
        chunks = []
        for result in pipeline(text, voice=voice, speed=speed, split_pattern=r"\n+"):
            audio = result.audio
            if audio is None:
                continue
            if hasattr(audio, "detach"):
                audio = audio.detach().cpu().numpy()
            chunks.append(np.asarray(audio).reshape(-1))
        if not chunks:
            raise RuntimeError(f"Kokoro returned no audio for line: {text[:60]!r}")
        _write_wav(path, _trim_silence(np.concatenate(chunks)))
        deepen_voice(path, float(os.environ.get("VOICE_DEPTH", "0") or 0))
    return paths


def generate_voiceover(text: str, output: str | Path) -> Path:
    """Generate narration; Kokoro is the GitHub-native default."""
    narration = text.strip()
    if not narration:
        raise ValueError("Narration text cannot be empty")
    output_path = Path(output)
    backend = os.environ.get("VOICE_BACKEND", "kokoro").strip().lower()
    if backend == "voicestudio":
        return _generate_voicestudio(narration, output_path)
    if backend == "test-tone":
        return _test_tone_line(narration, output_path)
    if backend != "kokoro":
        raise ValueError("VOICE_BACKEND must be 'kokoro' or 'voicestudio'.")
    return _generate_kokoro(narration, output_path)
