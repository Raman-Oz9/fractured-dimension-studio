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
MUSIC_RMS = 0.05  # legacy constant
MUSIC_PHONE_RMS = 0.075  # loudness of the bed in the band phone speakers can play (>150 Hz)
SFX_PEAK = 0.26


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


def riser(seconds: float = 1.3) -> np.ndarray:
    """Tension riser: rising glass tone under swelling noise, resolves into the next cut."""
    rng = np.random.default_rng(9)
    t = _t(seconds)
    freq = 220 * (2.0 ** (t / seconds * 2.2))
    tone = np.sin(2 * np.pi * np.cumsum(freq) / RATE)
    hiss = _bandpass_noise(rng, seconds, 1500, 7000)
    env = (t / seconds) ** 2.2
    return ((0.55 * tone + 0.6 * hiss) * env).astype(np.float32)


def stinger(seconds: float = 1.4) -> np.ndarray:
    """Dissonant horror hit: stacked minor seconds with a long metallic tail."""
    t = _t(seconds)
    out = np.zeros_like(t)
    for f, g in ((110, 1.0), (116.5, 0.9), (277, 0.5), (293.7, 0.45), (1244, 0.2)):
        out += g * np.sin(2 * np.pi * f * t)
    return (out * np.exp(-t * 3.2) * 0.35).astype(np.float32) + impact(seconds)[: t.size] * 0.7


def air_pass(seconds: float = 0.9, seed: int = 11) -> np.ndarray:
    """A cold draught moving past: dark, soft and unmistakably not a cartoon whoosh."""
    rng = np.random.default_rng(seed)
    n = _bandpass_noise(rng, seconds, 120, 750)
    return (n * np.sin(np.linspace(0, np.pi, n.size)) ** 2 * 0.8).astype(np.float32)


def sub_hit(seconds: float = 1.5) -> np.ndarray:
    """A deep, rounded boom with a rumbling tail and no bright crack."""
    rng = np.random.default_rng(12)
    t = _t(seconds)
    freq = 34 + 60 * np.exp(-t * 9)
    body = np.sin(2 * np.pi * np.cumsum(freq) / RATE) * np.exp(-t * 3.4)
    harm = np.sin(2 * np.pi * np.cumsum(freq * 2.01) / RATE) * np.exp(-t * 6.0) * 0.6  # audible on phones
    rumble = _bandpass_noise(rng, seconds, 60, 320) * np.exp(-t * 2.6) * 0.5
    return (body + harm + rumble).astype(np.float32)


def dread_swell(seconds: float = 2.4) -> np.ndarray:
    """Dissonant low strings swelling and fading: the sound of something wrong in the room."""
    t = _t(seconds)
    out = np.zeros_like(t)
    for f in (110.0, 116.5, 164.8, 174.6):
        for k in (1, 2, 3, 4):
            out += np.sin(2 * np.pi * f * k * t) / k
    return (out * np.hanning(t.size) * 0.3).astype(np.float32)


def murmur(seconds: float = 3.0, seed: int = 13) -> np.ndarray:
    """Distant whispering voices: band noise chopped into syllable-like bursts."""
    rng = np.random.default_rng(seed)
    base = _bandpass_noise(rng, seconds, 450, 2800)
    gate = np.clip(np.sin(2 * np.pi * rng.uniform(4.5, 6.5) * _t(seconds)[: base.size] + rng.uniform(0, 6.28)), 0, 1) ** 1.5
    return (base * gate * np.sin(np.linspace(0, np.pi, base.size)) * 0.7).astype(np.float32)


def tick(seconds: float = 0.18) -> np.ndarray:
    """A dry wooden tick, like a thumbnail notching a stick."""
    rng = np.random.default_rng(21)
    t = _t(seconds)
    click = _bandpass_noise(rng, seconds, 1100, 3800) * np.exp(-t * 70)
    knock_body = np.sin(2 * np.pi * 740 * t) * np.exp(-t * 55) * 0.6
    return (click + knock_body).astype(np.float32)


def knock(seconds: float = 0.4) -> np.ndarray:
    t = _t(seconds)
    body = np.sin(2 * np.pi * 150 * t) * np.exp(-t * 22) + 0.5 * np.sin(2 * np.pi * 300 * t) * np.exp(-t * 30)
    return body.astype(np.float32)


def creak(seconds: float = 1.3) -> np.ndarray:
    """Slow wooden/metal creak: a gliding, stuttering low saw."""
    rng = np.random.default_rng(22)
    t = _t(seconds)
    freq = 170 + 90 * np.sin(np.pi * t / seconds) + 6 * np.sin(2 * np.pi * 23 * t)
    saw = 2 * ((np.cumsum(freq) / RATE) % 1) - 1
    stutter = np.clip(0.5 + 0.5 * np.sin(2 * np.pi * 17 * t + 2 * np.sin(2 * np.pi * 3 * t)), 0, 1) ** 2
    shaped = _lowpass(saw.astype(np.float32) * stutter, 1400)
    return (shaped * np.sin(np.pi * t / seconds) ** 0.8 * 0.9).astype(np.float32)


def whisper(seconds: float = 1.8) -> np.ndarray:
    """A close, breathy whisper: sibilant noise phrased into soft syllables."""
    rng = np.random.default_rng(23)
    breath = _bandpass_noise(rng, seconds, 2200, 7000) * 0.6 + _bandpass_noise(rng, seconds, 600, 2400) * 0.5
    t = _t(seconds)[: breath.size]
    gate = np.clip(np.sin(2 * np.pi * 3.3 * t + 0.6) + 0.35 * np.sin(2 * np.pi * 7.1 * t), 0, 1) ** 1.4
    return (breath * gate * np.sin(np.pi * t / seconds)).astype(np.float32)


def engine_rev(seconds: float = 2.2) -> np.ndarray:
    """A bus engine winding up: rising harmonic-rich growl, audible on phone speakers."""
    rng = np.random.default_rng(24)
    t = _t(seconds)
    freq = 38 + 80 * (t / seconds) ** 1.4
    phase = np.cumsum(freq) / RATE
    out = sum(np.sin(2 * np.pi * phase * k) / k ** 0.7 for k in range(1, 9))
    out = out * (1 + 0.25 * np.sin(2 * np.pi * freq * 0.5 * t))
    out += _bandpass_noise(rng, seconds, 200, 1500) * 0.35 * (t / seconds)
    return (out * np.minimum(1, t / 0.25) * np.minimum(1, (seconds - t) / 0.6) * 0.4).astype(np.float32)


def rain_layer(seconds: float, seed: int = 31) -> np.ndarray:
    """Steady rain on a metal roof with sparse heavy drops."""
    rng = np.random.default_rng(seed)
    out = _bandpass_noise(rng, seconds, 1800, 9000) * 0.8 + _bandpass_noise(rng, seconds, 300, 1400) * 0.5
    swell = 0.8 + 0.2 * np.sin(2 * np.pi * 0.09 * _t(seconds)[: out.size])
    for _ in range(int(seconds * 1.4)):
        drop = _bandpass_noise(rng, 0.05, 700, 3500)
        _place(out, (drop * np.exp(-np.arange(drop.size) / (0.012 * RATE)) * 1.4).astype(np.float32), float(rng.uniform(0, seconds)))
    return (out * swell).astype(np.float32)


AMBIENCE = {"rain": rain_layer}
AMBIENCE_PHONE_RMS = 0.008

SFX["tick"] = tick
SFX["knock"] = knock
def brake(seconds: float = 1.5) -> np.ndarray:
    """Heavy bus air-brake: a short squeal gliding down, then a soft pneumatic hiss."""
    rng = np.random.default_rng(31)
    t = _t(seconds)
    freq = 520 - 230 * np.clip(t / 0.9, 0, 1)
    squeal = np.sin(2 * np.pi * np.cumsum(freq) / RATE) + 0.4 * np.sin(4 * np.pi * np.cumsum(freq) / RATE)
    squeal = _lowpass(squeal.astype(np.float32), 1800) * np.exp(-t / 0.55) * 0.35
    hiss = _bandpass_noise(rng, seconds, 2500, 7500) * np.clip((t - 0.35) / 0.1, 0, 1) * np.exp(-(t - 0.35).clip(0) / 0.5) * 0.5
    thud = np.sin(2 * np.pi * 55 * t) * np.exp(-t / 0.18) * 0.5
    return (squeal + hiss + thud).astype(np.float32)


SFX["brake"] = brake
SFX["creak"] = creak
SFX["whisper"] = whisper
SFX["engine_rev"] = engine_rev
SFX["riser"] = riser
SFX["stinger"] = stinger
SFX["air_pass"] = air_pass
SFX["sub_hit"] = sub_hit
SFX["dread_swell"] = dread_swell
SFX["murmur"] = murmur

# Horror, thriller and scary-documentary stories never use playful sounds: each cartoon-ish
# effect maps to a chilling equivalent (or is dropped) so viewers take the story seriously.
TENSE_SFX_MAP: dict[str, str | None] = {
    "whoosh": None, "whoosh_back": None, "impact": "sub_hit", "chime": "dread_swell", "stinger": "sub_hit",
    "coin": None, "crowd": None, "riser": None, "air_pass": None, "murmur": None,
}
TENSE_SFX_GAIN = 0.7
SPEECH_BAND_SFX = {"brake", "whisper", "creak", "engine_rev", "dread_swell", "murmur", "crowd", "chime"}


# ----------------------------------------------------------------------------- mood beds
# Each bed is synthesized from scratch and mixed far below the narration; the voice
# pocket EQ and ducking in mix_soundtrack keep it from ever masking the words.

def _lowpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    spectrum = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(x.size, 1 / RATE)
    spectrum *= 1.0 / (1.0 + (freqs / cutoff) ** 4)
    return np.fft.irfft(spectrum, x.size)


def _place(out: np.ndarray, sound: np.ndarray, start: float, gain: float = 1.0) -> None:
    begin = int(start * RATE)
    if begin >= out.size:
        return
    end = min(out.size, begin + sound.size)
    out[begin:end] += sound[: end - begin] * gain


def _pluck(freq: float, seconds: float, decay: float, bright: float = 0.3) -> np.ndarray:
    t = _t(seconds)
    tone = np.sin(2 * np.pi * freq * t) + bright * np.sin(2 * np.pi * freq * 2 * t) + bright * 0.4 * np.sin(2 * np.pi * freq * 3 * t)
    return (tone * np.exp(-t * decay)).astype(np.float32)


def _swell(freq: float, seconds: float, harmonics: int = 6) -> np.ndarray:
    """Slow bowed-string style swell: stacked harmonics under a hann envelope."""
    t = _t(seconds)
    tone = sum(np.sin(2 * np.pi * freq * k * t + 0.3 * k) / k for k in range(1, harmonics + 1))
    vibrato = 1 + 0.004 * np.sin(2 * np.pi * 5.2 * t)
    tone = sum(np.sin(2 * np.pi * freq * k * t * vibrato) / k for k in range(1, harmonics + 1))
    return (tone * np.hanning(t.size)).astype(np.float32)


def _wind(seconds: float, rng: np.random.Generator, level: float = 1.0) -> np.ndarray:
    n = _bandpass_noise(rng, seconds, 180, 1100)
    t = _t(seconds)
    gust = 0.35 + 0.65 * (0.5 + 0.5 * np.sin(2 * np.pi * 0.07 * t + rng.uniform(0, 6.28))) ** 2
    return (n * gust * level).astype(np.float32)


def _drone(t: np.ndarray, freqs: tuple[tuple[float, float, float], ...], rng: np.random.Generator) -> np.ndarray:
    """Slowly breathing drones. Upper harmonics are stacked on every note because phone
    speakers cannot reproduce deep bass: the harmonics are what make the dread audible."""
    out = np.zeros_like(t)
    for freq, gain, lfo in freqs:
        wobble = 0.65 + 0.35 * np.sin(2 * np.pi * lfo * t + rng.uniform(0, 6.28))
        drift = 0.4 * np.sin(2 * np.pi * 0.05 * t)
        for harmonic, weight in ((1, 1.0), (2, 0.8), (3, 0.6), (4, 0.4), (5, 0.28), (6, 0.18)):
            out += gain * weight * wobble * np.sin(2 * np.pi * freq * harmonic * t + drift * harmonic)
    return out


def _bed_mystery(seconds: float, rng: np.random.Generator) -> np.ndarray:
    t = _t(seconds)
    out = _drone(t, ((55.0, 1.0, 0.11), (82.4, 0.7, 0.17), (110.0, 0.5, 0.13), (164.8, 0.28, 0.21)), rng)
    notes = (220.0, 261.6, 329.6, 392.0, 440.0)
    for i in range(int(seconds / 0.9)):
        if rng.random() < 0.55:
            _place(out, _pluck(float(rng.choice(notes)), 0.9, 5.5, 0.0) * 0.35, i * 0.9)
    for i in range(int(seconds / 0.45)):
        _place(out, rng.standard_normal(int(0.03 * RATE)).astype(np.float32) * np.exp(-np.arange(int(0.03 * RATE)) / (0.006 * RATE)) * 0.08, i * 0.45)
    return out


def _bed_horror(seconds: float, rng: np.random.Generator) -> np.ndarray:
    """Cold dissonant sub drone, slow heartbeat, glassy whistles, wind and distant scrapes."""
    t = _t(seconds)
    out = _drone(t, ((41.2, 1.0, 0.05), (43.65, 0.9, 0.07), (65.4, 0.45, 0.09), (69.3, 0.4, 0.06)), rng) * 1.2
    out += _wind(seconds, rng, 0.9)
    beat = heartbeat()
    for i in range(int(seconds / 1.15)):
        _place(out, beat, i * 1.15, 0.55)
    cursor = 2.0
    while cursor < seconds - 2:
        length = rng.uniform(2.0, 3.6)
        tt = _t(length)
        base = float(rng.choice((1865.0, 2093.0, 2489.0)))
        glass = (np.sin(2 * np.pi * base * tt) + np.sin(2 * np.pi * base * 1.0595 * tt)) * np.hanning(tt.size)
        glass *= 0.5 + 0.5 * np.sin(2 * np.pi * 6.0 * tt)
        _place(out, glass.astype(np.float32), cursor, 0.03)
        cursor += rng.uniform(4.0, 7.5)
    return out


def _bed_documentary_dark(seconds: float, rng: np.random.Generator) -> np.ndarray:
    """Chilling documentary: sustained low strings, sparse minor piano and cold air."""
    t = _t(seconds)
    out = _drone(t, ((36.7, 1.0, 0.04), (55.0, 0.8, 0.06), (73.4, 0.5, 0.08)), rng) * 1.0
    out += _wind(seconds, rng, 0.55)
    roots = (73.4, 87.3, 98.0, 65.4)  # D2 F2 G2 C2: slow, unresolved
    cursor, idx = 0.0, 0
    while cursor < seconds:
        length = rng.uniform(6.5, 9.0)
        root = roots[idx % len(roots)]
        _place(out, _swell(root, length) * 1.1, cursor)
        _place(out, _swell(root * 1.5, length * 0.9, 4) * 0.55, cursor + 0.6)
        cursor += length * 0.7
        idx += 1
    for note in (293.7, 349.2, 440.0, 523.3, 587.3):
        pass
    cursor = 3.0
    while cursor < seconds - 2:
        note = float(rng.choice((293.7, 349.2, 440.0, 523.3, 587.3)))
        _place(out, _pluck(note, 3.0, 1.6, 0.5) * 0.28, cursor)
        cursor += rng.uniform(2.4, 5.5)
    beat = heartbeat()
    for i in range(int(seconds / 3.4)):
        _place(out, beat, 1.0 + i * 3.4, 0.4)
    return out


def _bed_thriller(seconds: float, rng: np.random.Generator) -> np.ndarray:
    """Driving low ostinato that tightens over time, ticking hats and rising tension."""
    t = _t(seconds)
    step = 0.25
    out = np.zeros_like(t)
    pattern = (55.0, 55.0, 65.4, 55.0, 55.0, 73.4, 55.0, 61.7)
    progress = np.linspace(0, 1, t.size)
    for i in range(int(seconds / step)):
        f = pattern[i % len(pattern)]
        length = int(0.22 * RATE)
        tt = np.arange(length) / RATE
        saw = 2 * ((f * tt) % 1) - 1
        note = _lowpass(saw.astype(np.float32), 500 + 2200 * min(1.0, i * step / seconds)) * np.exp(-tt * 9)
        _place(out, note.astype(np.float32), i * step, 0.9)
        if i % 2 == 1:
            hat = rng.standard_normal(int(0.04 * RATE)).astype(np.float32)
            _place(out, hat * np.exp(-np.arange(hat.size) / (0.008 * RATE)) * 0.12 * (0.5 + progress[min(t.size - 1, int(i * step * RATE))]), i * step)
    cursor = 14.0
    while cursor < seconds - 2:
        _place(out, riser(2.0) * 0.4, cursor - 2.0)
        _place(out, impact(0.9) * 0.4, cursor)
        cursor += 16.0
    out += _drone(t, ((55.0, 0.6, 0.1),), rng)
    return out


def _bed_dark_comedy(seconds: float, rng: np.random.Generator) -> np.ndarray:
    """Sneaky pizzicato walking bass and mischievous plucks over a low drone."""
    t = _t(seconds)
    out = _drone(t, ((55.0, 0.5, 0.1),), rng)
    beat = 0.6
    walk = (110.0, 130.8, 146.8, 164.8, 146.8, 130.8, 123.5, 110.0)
    for i in range(int(seconds / beat)):
        _place(out, _pluck(walk[i % len(walk)], 0.5, 7.0, 0.5) * 0.9, i * beat)
        if rng.random() < 0.55:
            _place(out, _pluck(float(rng.choice((440.0, 523.3, 622.3, 659.3))), 0.4, 9.0, 0.2) * 0.35, i * beat + beat / 2)
    for i in range(int(seconds / 2.4)):
        _place(out, rng.standard_normal(int(0.03 * RATE)).astype(np.float32) * np.exp(-np.arange(int(0.03 * RATE)) / (0.006 * RATE)) * 0.1, i * 2.4 + 1.2)
    return out


def _bed_comedy(seconds: float, rng: np.random.Generator) -> np.ndarray:
    t = _t(seconds)
    out = np.zeros_like(t)
    beat = 0.3
    scale = (261.6, 293.7, 329.6, 392.0, 440.0, 523.3)
    bass = (130.8, 130.8, 196.0, 174.6)
    for i in range(int(seconds / beat)):
        if i % 2 == 0:
            _place(out, _pluck(bass[(i // 2) % 4], 0.35, 8.0, 0.4) * 0.8, i * beat)
        if rng.random() < 0.6:
            _place(out, _pluck(float(rng.choice(scale)), 0.3, 11.0, 0.2) * 0.45, i * beat)
    return out


def _bed_epic(seconds: float, rng: np.random.Generator) -> np.ndarray:
    t = _t(seconds)
    out = _drone(t, ((36.7, 1.0, 0.05), (73.4, 0.6, 0.07)), rng)
    for i in range(int(seconds / 1.2)):
        _place(out, impact(0.8) * (0.9 if i % 4 == 0 else 0.45), i * 1.2)
    cursor, chords = 0.0, ((146.8, 220.0), (130.8, 196.0), (116.5, 174.6), (130.8, 196.0))
    idx = 0
    while cursor < seconds:
        for note in chords[idx % 4]:
            _place(out, _swell(note, 5.0, 8) * 0.55, cursor)
        cursor += 4.2
        idx += 1
    return out


def _bed_sad(seconds: float, rng: np.random.Generator) -> np.ndarray:
    t = _t(seconds)
    out = _drone(t, ((110.0, 0.8, 0.06), (164.8, 0.6, 0.08), (220.0, 0.4, 0.05), (329.6, 0.25, 0.07)), rng) * 0.8
    cursor = 1.0
    notes = (440.0, 523.3, 392.0, 349.2, 329.6)
    while cursor < seconds - 1:
        _place(out, _pluck(float(rng.choice(notes)), 3.5, 1.4, 0.35) * 0.5, cursor)
        cursor += rng.uniform(1.8, 3.2)
    return out


def _bed_wonder(seconds: float, rng: np.random.Generator) -> np.ndarray:
    t = _t(seconds)
    out = _drone(t, ((110.0, 0.7, 0.05), (220.0, 0.6, 0.07), (329.6, 0.5, 0.09), (493.9, 0.35, 0.06), (740.0, 0.2, 0.11)), rng)
    out += _wind(seconds, rng, 0.2)
    cursor = 0.5
    arp = (659.3, 784.0, 987.8, 1174.7, 1318.5)
    while cursor < seconds - 1:
        _place(out, _pluck(float(rng.choice(arp)), 2.0, 2.6, 0.15) * 0.3, cursor)
        cursor += rng.uniform(0.5, 1.4)
    return out


BEDS = {
    "mystery": _bed_mystery, "horror": _bed_horror, "documentary_dark": _bed_documentary_dark,
    "thriller": _bed_thriller, "dark_comedy": _bed_dark_comedy, "comedy": _bed_comedy,
    "epic": _bed_epic, "sad": _bed_sad, "wonder": _bed_wonder,
}
MOODS = tuple(BEDS)
# Relative loudness per mood (horror stays near-subliminal; lively beds sit a touch lower).
MOOD_GAIN = {"horror": 1.0, "documentary_dark": 1.05, "thriller": 0.95, "mystery": 1.0, "dark_comedy": 0.9,
             "comedy": 0.8, "epic": 1.05, "sad": 0.95, "wonder": 0.95}
TENSE_MOODS = {"horror", "thriller", "documentary_dark"}

_MOOD_WORDS = {
    "horror": ("ghost", "haunt", "blood", "scream", "corpse", "demon", "curse", "nightmare", "terrif", "scary",
               "horror", "creep", "grave", "evil", "murder", "killer", "monster", "sinister", "eerie", "possessed", "cursed"),
    "thriller": ("chase", "escape", "heist", "hunt", "spy", "explosion", "trap", "danger", "countdown", "panic", "fled", "pursuit", "assassin"),
    "documentary_dark": ("mystery", "mysteries", "unexplained", "abyss", "deep sea", "unknown", "disappear", "vanish", "ancient",
                         "investigat", "unsolved", "cold case", "void", "dark side", "lost"),
    "dark_comedy": ("magician", "trick", "shadow", "assistant", "punchline"),
    "comedy": ("funny", "joke", "clown", "silly", "laugh", "prank", "hilarious"),
    "epic": ("war", "battle", "empire", "legend", "hero", "kingdom", "army", "conquer"),
    "sad": ("grief", "lonely", "tears", "farewell", "funeral", "heartbreak", "orphan", "lost love"),
    "wonder": ("galaxy", "universe", "stars", "ocean", "wonder", "planet", "nebula", "aurora", "coral"),
}


def detect_mood(text: str) -> str:
    """Pick a soundtrack mood from the script's wording; defaults to a curious 'mystery' bed."""
    lowered = text.lower()
    scores = {m: sum(lowered.count(w) for w in words) for m, words in _MOOD_WORDS.items()}
    best = max(scores, key=lambda m: scores[m])
    return best if scores[best] >= 2 else "mystery"


def _carve_voice_pocket(bed: np.ndarray) -> np.ndarray:
    """Dip the bed 6 dB across the speech band so narration always sits on top of it."""
    spectrum = np.fft.rfft(bed)
    freqs = np.fft.rfftfreq(bed.size, 1 / RATE)
    # Sub-bass is trimmed too: phones cannot play it, and it would only eat loudness headroom.
    gain = np.interp(freqs, [0, 60, 110, 150, 280, 3200, 5200, RATE / 2], [0.15, 0.3, 0.7, 1.0, 0.6, 0.6, 1.0, 0.8])
    return np.fft.irfft(spectrum * gain, bed.size).astype(np.float32)


def music_bed(seconds: float, mood: str = "mystery", seed: int = 7) -> np.ndarray:
    """Synthesize the mood's background bed, voice-pocketed and levelled well under narration."""
    if mood not in BEDS:
        raise ValueError(f"Unknown mood '{mood}'. Choose from {', '.join(MOODS)}")
    rng = np.random.default_rng(seed)
    out = BEDS[mood](seconds, rng).astype(np.float32)
    t = _t(seconds)[: out.size]
    fade = np.minimum(1.0, np.minimum(t / 2.0, (seconds - t) / 2.5))
    out = _carve_voice_pocket(out * np.clip(fade, 0, 1))
    # Level by what a phone can actually play (above 150 Hz), not by inaudible sub-bass.
    spectrum = np.fft.rfft(out)
    freqs = np.fft.rfftfreq(out.size, 1 / RATE)
    audible = np.fft.irfft(spectrum * (freqs > 150), out.size)
    rms = float(np.sqrt(np.mean(audible ** 2))) or 1.0
    return (out / rms * MUSIC_PHONE_RMS * MOOD_GAIN[mood]).astype(np.float32)


def normalise_voice(audio: np.ndarray) -> np.ndarray:
    if audio.size == 0:
        return audio
    rms = float(np.sqrt(np.mean(audio ** 2))) or 1.0
    peak = float(np.max(np.abs(audio))) or 1.0
    gain = min(VOICE_TARGET_RMS / rms, 0.92 / peak)
    return audio * gain


def duck_envelope(voice: np.ndarray, floor: float = 0.7) -> np.ndarray:
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
    mood: str = "mystery",
    ambience: tuple[str, ...] = (),
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
        bed = music_bed(total_seconds + 0.2, mood)[:total]
        mix[: bed.size] += bed * duck_envelope(voice)[: bed.size]
    for layer in ambience:
        if layer not in AMBIENCE:
            raise ValueError(f"Unknown ambience '{layer}'")
        bed = AMBIENCE[layer](total_seconds + 0.2)[:total]
        spectrum = np.fft.rfft(bed)
        freqs = np.fft.rfftfreq(bed.size, 1 / RATE)
        rms = float(np.sqrt(np.mean(np.fft.irfft(spectrum * (freqs > 150), bed.size) ** 2))) or 1.0
        fade = np.minimum(1.0, np.minimum(np.arange(bed.size) / (2 * RATE), (bed.size - np.arange(bed.size)) / (2.5 * RATE)))
        mix[: bed.size] += (bed / rms * AMBIENCE_PHONE_RMS * fade * duck_envelope(voice)[: bed.size] ** 0.5).astype(np.float32)
    for when, name, gain in sfx_events:
        if name not in SFX:
            raise ValueError(f"Unknown sound effect '{name}'")
        if mood in TENSE_MOODS and name in TENSE_SFX_MAP:
            name = TENSE_SFX_MAP[name]
            if name is None:
                continue
            gain *= TENSE_SFX_GAIN
        effect = SFX[name]()
        effect = effect / (np.max(np.abs(effect)) + 1e-9) * SFX_PEAK * gain
        begin = max(0, int(when * RATE))
        end = min(total, begin + effect.size)
        if begin < total:
            segment = effect[: end - begin]
            if name in SPEECH_BAND_SFX:
                # Effects that live in the speech band get out of the narrator's way.
                segment = segment * duck_envelope(voice, floor=0.3)[begin:end]
            mix[begin:end] += segment
    peak = float(np.max(np.abs(mix))) or 1.0
    if peak > 0.97:
        mix = mix / peak * 0.97
    return mix
