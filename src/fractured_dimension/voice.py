"""VoiceStudio.sh narration client for GitHub Actions and hosted runners."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _request(url: str, api_key: str, *, payload: dict | None = None) -> bytes:
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urlopen(request, timeout=300) as response:
            return response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(
            f"VoiceStudio API returned HTTP {exc.code}: {detail or exc.reason}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach VoiceStudio API: {exc.reason}") from exc


def _resolve_voice(base_url: str, api_key: str, requested: str) -> str:
    """Resolve a visible voice name to its saved profile ID when possible."""
    raw = _request(f"{base_url}/audio/voices", api_key)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("VoiceStudio returned an invalid voice catalogue.") from exc

    voices = data.get("voices", []) if isinstance(data, dict) else []
    wanted = requested.strip().casefold()
    for item in voices:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        voice_id = str(item.get("voice_id") or item.get("id") or "").strip()
        if voice_id and (name.casefold() == wanted or voice_id.casefold() == wanted):
            return voice_id
    # VoiceStudio also accepts engine presets and the default alias.
    return requested


def generate_voiceover(text: str, output: str | Path) -> Path:
    """Generate WAV narration through the configured VoiceStudio.sh API."""
    narration = text.strip()
    if not narration:
        raise ValueError("Narration text cannot be empty")

    base_url = os.environ.get("VOICESTUDIO_BASE_URL", "").strip().rstrip("/")
    api_key = os.environ.get("VOICESTUDIO_API_KEY", "").strip()
    if not base_url or not api_key:
        raise RuntimeError(
            "VoiceStudio narration needs VOICESTUDIO_BASE_URL and "
            "VOICESTUDIO_API_KEY configured as GitHub Actions secrets."
        )

    voice = os.environ.get("VOICESTUDIO_VOICE", "George").strip() or "George"
    model = os.environ.get("VOICESTUDIO_MODEL", "tts-1").strip() or "tts-1"
    speed = float(os.environ.get("VOICESTUDIO_SPEED", "0.92"))
    if not 0.25 <= speed <= 4.0:
        raise ValueError("VOICESTUDIO_SPEED must be between 0.25 and 4.0")

    voice_id = _resolve_voice(base_url, api_key, voice)
    audio = _request(
        f"{base_url}/audio/speech",
        api_key,
        payload={
            "model": model,
            "voice": voice_id,
            "input": narration,
            "response_format": "wav",
            "speed": speed,
            "instruct": "Deep, cinematic male documentary narration. Controlled, resonant, confident delivery; natural pauses; clear articulation. Avoid exaggerated theatrical acting.",
        },
    )
    if not audio:
        raise RuntimeError("VoiceStudio returned an empty audio file.")

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio)
    return output_path
