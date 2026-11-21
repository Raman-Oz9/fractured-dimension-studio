"""Procedural sound design for the manga renderer: music bed, SFX and ducked narration mix.

Everything is synthesized with numpy so the GitHub runner needs no sample packs and
nothing here depends on downloads or licences.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

RATE = 24000
VOICE_TARGET_RMS = 0.11
MUSIC_RMS = 0.026  # about 12 dB under narration: felt, never competing with it
SFX_PEAK = 0.38


def read_wav(path: str | Path) -> np.ndarray:
    with wave.open(str(path), "rb") as handle:
        if handle.getframerate() != RATE:
            raise ValueError(f"Expected {RATE} Hz audio, got {handle.getframerate()}")
        raw = handle.readframes(handle.getnframes())
        channels = handle.getnchannels()
    audio = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return audio


def write_wav(path: str | Path, audio: np.ndarray) -> Path:
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(target), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(pcm.tobytes())
    return target


def _t(seconds: float) -> np.ndarray:
    return np.arange(int(seconds * RATE)) / RATE


def _bandpass_noise(rng: np.random.Generator, seconds: float, low: float, high: float) -> np.ndarray:
    n = int(seconds * RATE)
    spectrum = np.fft.rfft(rng.standard_normal(n))
    freqs = np.fft.rfftfreq(n, 1 / RATE)
    spectrum[(freqs < low) | (freqs > high)] = 0
    out = np.fft.irfft(spectrum, n)
    return out / (np.max(np.abs(out)) + 1e-9)


def whoosh(seconds: float = 0.5, rising: bool = True, seed: int = 1) -> np.ndarray:
    """Swept noise: the sound of a camera whip or a fast pass-by."""
    rng = np.random.default_rng(seed)
    slices = 8
    n = int(seconds * RATE)
    out = np.zeros(n, dtype=np.float32)
    window = np.hanning(n // slices * 2)
    for i in range(slices):
        k = i if rising else slices - 1 - i
        centre = 500 * (1.45 ** k)
        band = _bandpass_noise(rng, seconds, centre * 0.6, centre * 1.5)
        start = i * (n // slices)
        end = min(n, start + window.size)
        out[start:end] += (band[start:end] * window[: end - start]).astype(np.float32)
    envelope = np.sin(np.linspace(0, np.pi, n)) ** 1.5
    return out * envelope * 0.9


def impact(seconds: float = 0.7, seed: int = 2) -> np.ndarray:
    """Low thud plus a short noise crack, for impact frames and sound-effect lettering."""
    rng = np.random.default_rng(seed)
    t = _t(seconds)
    freq = 38 + 90 * np.exp(-t * 14)
    body = np.sin(2 * np.pi * np.cumsum(freq) / RATE) * np.exp(-t * 6.5)
    crack = _bandpass_noise(rng, seconds, 900, 5000) * np.exp(-t * 38) * 0.55
    return (body + crack).astype(np.float32)


def chime(seconds: float = 1.6) -> np.ndarray:
    """Glassy bell for reveals; partials follow a struck-metal ratio."""
    t = _t(seconds)
    out = np.zeros_like(t)
    for ratio, gain in ((1, 1.0), (2.76, 0.5), (5.4, 0.25), (8.9, 0.12)):
        out += gain * np.sin(2 * np.pi * 660 * ratio * t) * np.exp(-t * (2.2 + ratio * 0.7))
    return (out * 0.5).astype(np.float32)


def coin(seconds: float = 0.5) -> np.ndarray:
    t = _t(seconds)
    out = np.sin(2 * np.pi * 2400 * t) * np.exp(-t * 18)
    later = np.clip(t - 0.09, 0, None)
    out += 0.8 * np.sin(2 * np.pi * 3300 * later) * np.exp(-later * 16) * (t > 0.09)
    return (out * 0.5).astype(np.float32)


def crowd(seconds: float = 3.0, seed: int = 3) -> np.ndarray:
    """Applause and cheering: band noise with random crackle and a swelling envelope."""
    rng = np.random.default_rng(seed)
    base = _bandpass_noise(rng, seconds, 1200, 5200)
    crackle = np.clip(rng.standard_normal(base.size), 0, None) ** 2
    crackle = np.convolve(crackle, np.ones(180) / 180, mode="same")
    swell = np.sin(np.linspace(0, np.pi, base.size)) ** 0.8
    cheer = _bandpass_noise(rng, seconds, 300, 900) * 0.5
    swell_slow = 0.6 + 0.4 * np.sin(2 * np.pi * 2.3 * _t(seconds)[: base.size])
    return ((base * (0.4 + crackle) + cheer * swell_slow) * swell * 0.55).astype(np.float32)


def heartbeat(seconds: float = 1.4) -> np.ndarray:
    t = _t(seconds)
    beat = np.sin(2 * np.pi * 52 * t) * np.exp(-t * 11)
    second = np.clip(t - 0.28, 0, None)
    beat += 0.7 * np.sin(2 * np.pi * 46 * second) * np.exp(-second * 12) * (t > 0.28)
    return (beat * 0.8).astype(np.float32)


SFX = {
    "whoosh": lambda: whoosh(0.5, True),
    "whoosh_back": lambda: whoosh(0.5, False, seed=5),
    "impact": impact,
    "chime": chime,
    "coin": coin,
    "crowd": crowd,
    "heartbeat": heartbeat,
}


def music_bed(seconds: float, seed: int = 7) -> np.ndarray:
    """A dark, slow ambient pulse: low drone, drifting fifths and a soft ticking clock."""
    rng = np.random.default_rng(seed)
    t = _t(seconds)
    out = np.zeros_like(t)
    # A minor drone with slow tremolo so the bed breathes instead of sitting flat.
    for freq, gain, lfo in ((55.0, 1.0, 0.11), (82.4, 0.7, 0.17), (110.0, 0.5, 0.13), (164.8, 0.28, 0.21)):
        wobble = 0.65 + 0.35 * np.sin(2 * np.pi * lfo * t + rng.uniform(0, 6.28))
        out += gain * wobble * np.sin(2 * np.pi * freq * t + 0.4 * np.sin(2 * np.pi * 0.05 * t))
    # Sparse pentatonic plucks: curious, a little mischievous, never a lullaby.
    notes = (220.0, 261.6, 329.6, 392.0, 440.0)
    step = 0.9
    for i in range(int(seconds / step)):
        if rng.random() < 0.55:
            start = int(i * step * RATE)
            length = int(0.9 * RATE)
            tt = np.arange(length) / RATE
            pluck = np.sin(2 * np.pi * rng.choice(notes) * tt) * np.exp(-tt * 5.5) * 0.35
            end = min(out.size, start + length)
            out[start:end] += pluck[: end - start]
    # Soft clock tick on the beat.
    for i in range(int(seconds / 0.45)):
        start = int(i * 0.45 * RATE)
        length = int(0.03 * RATE)
        end = min(out.size, start + length)
        out[start:end] += (rng.standard_normal(end - start) * np.exp(-np.arange(end - start) / (0.006 * RATE)) * 0.08)
    fade = np.minimum(1.0, np.minimum(t / 1.5, (seconds - t) / 2.0))
    out *= np.clip(fade, 0, 1)
    rms = float(np.sqrt(np.mean(out ** 2))) or 1.0
    return (out / rms * MUSIC_RMS).astype(np.float32)


def normalise_voice(audio: np.ndarray) -> np.ndarray:
    if audio.size == 0:
        return audio
    rms = float(np.sqrt(np.mean(audio ** 2))) or 1.0
    peak = float(np.max(np.abs(audio))) or 1.0
    gain = min(VOICE_TARGET_RMS / rms, 0.92 / peak)
    return audio * gain


def duck_envelope(voice: np.ndarray, floor: float = 0.55) -> np.ndarray:
    """Music gain that dips while someone is speaking and recovers in the gaps."""
    window = int(0.18 * RATE)
    smooth = np.convolve(np.abs(voice), np.ones(window) / window, mode="same")
    activity = np.clip(smooth / 0.04, 0, 1)
    slow = np.convolve(activity, np.ones(int(0.25 * RATE)) / int(0.25 * RATE), mode="same")
    return 1.0 - (1.0 - floor) * slow


def mix_soundtrack(
    total_seconds: float,
    voice_clips: list[tuple[float, np.ndarray]],
    sfx_events: list[tuple[float, str, float]],
    music: bool = True,
) -> np.ndarray:
    """Build the full mix: levelled narration, ducked music bed and timed sound effects."""
    total = int((total_seconds + 0.2) * RATE)
    voice = np.zeros(total, dtype=np.float32)
    for start, clip in voice_clips:
        begin = int(start * RATE)
        end = min(total, begin + clip.size)
        if begin < total:
            voice[begin:end] += normalise_voice(clip)[: end - begin]
    mix = voice.copy()
    if music:
        bed = music_bed(total_seconds + 0.2)[:total]
        mix[: bed.size] += bed * duck_envelope(voice)[: bed.size]
    for when, name, gain in sfx_events:
        if name not in SFX:
            raise ValueError(f"Unknown sound effect '{name}'")
        effect = SFX[name]()
        effect = effect / (np.max(np.abs(effect)) + 1e-9) * SFX_PEAK * gain
        begin = max(0, int(when * RATE))
        end = min(total, begin + effect.size)
        if begin < total:
            mix[begin:end] += effect[: end - begin]
    peak = float(np.max(np.abs(mix))) or 1.0
    if peak > 0.97:
        mix = mix / peak * 0.97
    return mix
