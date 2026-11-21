"""Manga renderer: ink-and-screentone look, directed camera, effects and narration-locked cuts.

Every shot owns one narration line. The shot is exactly as long as that line takes to
speak (plus a short visual lead-in and a beat of silence), so the picture always shows
what the narrator is saying at the moment he says it.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

from . import audio as sound
from .voice import generate_voice_lines

W, H = 1080, 1920
FPS = 30
CANVAS_H = 2880  # source panels are upscaled so deep push-ins stay crisp
FRAME_MARGIN = 16
FRAME_LINE = 6
PAPER = (252, 250, 244)
INK = (12, 12, 16)
FIRST_LEAD = 0.5
SENTENCE_GAP = 0.16  # narration flows: lines run nearly back to back
CLAUSE_GAP = 0.07
FINAL_TAIL = 1.4

# keyframes: at, zoom, x, y [, roll degrees]. x/y anchor the crop inside the panel
# (0 = left/top edge visible, 1 = right/bottom edge visible).
CAMERA_PRESETS: dict[str, dict[str, Any]] = {
    "push_in": {"path": [(0, 1.0, .50, .50), (.3, 1.07, .51, .49), (.72, 1.20, .52, .45), (1, 1.30, .52, .43)]},
    "pull_out": {"path": [(0, 1.32, .50, .47), (.3, 1.22, .49, .49), (.72, 1.08, .50, .50), (1, 1.0, .50, .50)]},
    "pan_left": {"path": [(0, 1.18, .92, .50), (.5, 1.22, .50, .49), (1, 1.28, .08, .48)]},
    "pan_right": {"path": [(0, 1.18, .08, .50), (.5, 1.22, .50, .49), (1, 1.28, .92, .48)]},
    "hold": {"path": [(0, 1.04, .49, .50), (.55, 1.06, .50, .495), (1, 1.08, .51, .49)]},
    # Manga-specific moves ----------------------------------------------------------
    "snap_in": {"path": [(0, 1.08, .50, .50), (.22, 1.75, .50, .42), (1, 1.92, .50, .40)], "ease": "snap"},
    "crash_in": {"path": [(0, 1.0, .50, .52), (.25, 1.55, .50, .44, -2.5), (1, 1.72, .50, .42, -3.5)],
                 "ease": "snap", "shake": 16},
    "whip_left": {"path": [(0, 1.25, .97, .50), (.28, 1.25, .30, .50), (1, 1.34, .20, .48)], "ease": "snap"},
    "whip_right": {"path": [(0, 1.25, .03, .50), (.28, 1.25, .70, .50), (1, 1.34, .80, .48)], "ease": "snap"},
    "tilt_up": {"path": [(0, 1.20, .50, .95), (.55, 1.24, .50, .50), (1, 1.30, .50, .08)]},
    "tilt_down": {"path": [(0, 1.20, .50, .05), (.55, 1.24, .50, .50), (1, 1.30, .50, .92)]},
    "shake_hold": {"path": [(0, 1.18, .50, .48), (1, 1.26, .50, .46)], "shake": 12},
    "dutch_push": {"path": [(0, 1.14, .50, .50, 4.0), (1, 1.50, .50, .44, 5.5)]},
    "drift_roll": {"path": [(0, 1.12, .48, .50, -1.4), (.5, 1.16, .50, .49, 1.2), (1, 1.20, .52, .48, -0.8)]},
}
CAMERA_MOVES = frozenset(CAMERA_PRESETS)
FX_NAMES = frozenset({"speed_lines", "focus_lines", "impact", "gloom", "flash"})
TRANSITIONS = frozenset({"cut", "whip", "flash", "dip"})
EASES = frozenset({"smooth", "snap", "linear", "in"})
SFX_NAMES = frozenset(sound.SFX)


# --------------------------------------------------------------------------- camera

def _ease(name: str, u: float) -> float:
    u = min(max(u, 0.0), 1.0)
    if name == "snap":
        return 1 - (1 - u) ** 4
    if name == "linear":
        return u
    if name == "in":
        return u ** 2.2
    return u * u * (3 - 2 * u)


def _keyframes(shot: dict[str, Any]) -> list[tuple[float, float, float, float, float]]:
    raw = shot.get("camera_path")
    if raw:
        return [(k["at"], k["zoom"], k["x"], k["y"], k.get("roll", 0.0)) for k in raw]
    preset = CAMERA_PRESETS[shot["camera"]]["path"]
    return [(*k, 0.0) if len(k) == 4 else k for k in preset]


def sample_camera(shot: dict[str, Any], u: float) -> tuple[float, float, float, float]:
    """Return (zoom, x, y, roll_degrees) at normalised shot time u."""
    ease = shot.get("ease") or CAMERA_PRESETS.get(shot.get("camera", ""), {}).get("ease", "smooth")
    frames = _keyframes(shot)
    u = min(max(u, 0.0), 1.0)
    for a, b in zip(frames, frames[1:]):
        if u <= b[0] or b is frames[-1]:
            span = max(b[0] - a[0], 1e-6)
            k = _ease(ease, (u - a[0]) / span)
            return tuple(a[i] + (b[i] - a[i]) * k for i in range(1, 5))  # type: ignore[return-value]
    last = frames[-1]
    return last[1], last[2], last[3], last[4]


def shake_offset(shot: dict[str, Any], t: float, seed: int) -> tuple[float, float, float]:
    """Hand-held rattle in output pixels with exponential decay; returns (dx, dy, roll_deg)."""
    amp = float(shot.get("shake", CAMERA_PRESETS.get(shot.get("camera", ""), {}).get("shake", 0)))
    if amp <= 0:
        return 0.0, 0.0, 0.0
    decay = float(shot.get("shake_decay", 0.7))
    fall = math.exp(-t / decay) if decay > 0 else 1.0
    p = seed * 1.7
    dx = amp * fall * (math.sin(t * 61 + p) + 0.5 * math.sin(t * 97 + 2 * p))
    dy = amp * fall * (math.sin(t * 73 + 3 * p) + 0.5 * math.sin(t * 109 + p))
    roll = 0.12 * amp * fall * math.sin(t * 53 + p)
    return dx, dy, roll


# --------------------------------------------------------------------------- panels

def _halftone(gray: np.ndarray, pitch: float = 10.0) -> np.ndarray:
    """Convert greys to 45-degree manga screentone dots; solid blacks and whites stay clean."""
    h, w = gray.shape
    y, x = np.indices((h, w), dtype=np.float32)
    u = ((x + y) / (pitch * 1.4142) % 1.0) - 0.5
    v = ((x - y) / (pitch * 1.4142) % 1.0) - 0.5
    dist = np.sqrt(u * u + v * v)
    tone = np.clip(gray, 0.18, 1.0)
    radius = np.sqrt((1.0 - tone) / math.pi)
    coverage = np.clip((radius - dist) * pitch + 0.5, 0, 1)
    dots = 1.0 - coverage
    weight = np.clip((gray - 0.14) / 0.14, 0, 1) * np.clip((0.96 - gray) / 0.06, 0, 1)
    return gray * (1 - weight) + dots * weight


def prepare_panel(path: Path, tone: bool = True) -> Image.Image:
    """Load an illustration and give it the printed-manga treatment (greyscale 'L' panel)."""
    source = Image.open(path)
    source.load()
    gray = source.convert("L")
    # Keep the 9:16 window fully inside the canvas: scale so the shorter side fits.
    aspect = gray.width / gray.height
    if aspect >= 9 / 16:
        size = (round(CANVAS_H * aspect), CANVAS_H)
    else:
        size = (round(CANVAS_H * 9 / 16), round(CANVAS_H * 9 / 16 / aspect))
    gray = gray.resize(size, Image.Resampling.LANCZOS)
    arr = np.asarray(gray, dtype=np.float32) / 255.0
    arr = np.clip((arr - 0.07) / (0.93 - 0.07), 0, 1)  # ink levels
    arr = arr * 0.55 + (arr * arr * (3 - 2 * arr)) * 0.45  # push contrast toward print
    if tone:
        arr = _halftone(arr)
    return Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8), "L")


def mean_brightness(panel: Image.Image) -> float:
    small = panel.resize((90, 160), Image.Resampling.BILINEAR)
    return float(np.asarray(small, dtype=np.float32).mean())


def render_view(panel: Image.Image, zoom: float, ax: float, ay: float, roll: float,
                dx: float = 0.0, dy: float = 0.0) -> Image.Image:
    """Sample the panel through a virtual camera with sub-pixel accuracy (no zoompan jitter)."""
    cw, ch = panel.size
    bw = min(cw, ch * 9 / 16)
    bh = bw * 16 / 9
    theta = math.radians(roll)
    cos, sin = math.cos(theta), math.sin(theta)
    zoom = max(zoom, 1.0)
    # Zoom in just enough that a rolled frame never shows beyond the panel.
    for _ in range(2):
        vw, vh = bw / zoom, bh / zoom
        hx = (vw * abs(cos) + vh * abs(sin)) / 2
        hy = (vw * abs(sin) + vh * abs(cos)) / 2
        grow = max(hx / (cw / 2), hy / (ch / 2), 1.0)
        zoom *= grow
    vw, vh = bw / zoom, bh / zoom
    hx = (vw * abs(cos) + vh * abs(sin)) / 2
    hy = (vw * abs(sin) + vh * abs(cos)) / 2
    cx = (cw - vw) * ax + vw / 2 + dx * vw / W
    cy = (ch - vh) * ay + vh / 2 + dy * vh / H
    cx = min(max(cx, hx), cw - hx)
    cy = min(max(cy, hy), ch - hy)
    s = vw / W
    a, b = s * cos, -s * sin
    d, e = s * sin, s * cos
    c = cx - a * W / 2 - b * H / 2
    f = cy - d * W / 2 - e * H / 2
    return panel.transform((W, H), Image.Transform.AFFINE, (a, b, c, d, e, f),
                           resample=Image.Resampling.BICUBIC)


# --------------------------------------------------------------------------- effects

def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def line_mask(kind: str, variant: int, focus: tuple[float, float]) -> Image.Image:
    """White-on-black mask of manga effect lines; variants flicker at 15 fps."""
    rng = np.random.default_rng(1000 + variant * 31 + (7 if kind == "focus_lines" else 0))
    big = Image.new("L", (W, H), 0)
    draw = ImageDraw.Draw(big)
    fx, fy = focus[0] * W, focus[1] * H
    if kind == "focus_lines":
        inner = H * 0.17
        count = 110
        for i in range(count):
            ang = (i + rng.uniform(-0.35, 0.35)) / count * 2 * math.pi
            half = rng.uniform(0.004, 0.012)
            reach = H * rng.uniform(0.62, 1.1)
            start = inner * rng.uniform(1.0, 1.7)
            p1 = (fx + math.cos(ang) * start, fy + math.sin(ang) * start)
            p2 = (fx + math.cos(ang - half) * reach, fy + math.sin(ang - half) * reach)
            p3 = (fx + math.cos(ang + half) * reach, fy + math.sin(ang + half) * reach)
            draw.polygon([p1, p2, p3], fill=255)
    elif kind == "speed_lines":
        for _ in range(70):
            y = rng.uniform(-80, H + 80)
            edge = abs(y / H - focus[1]) * 2  # denser away from the focus band
            if rng.random() > 0.25 + 0.75 * min(edge, 1):
                continue
            length = rng.uniform(W * 0.35, W * 1.2)
            x0 = rng.uniform(-W * 0.2, W)
            thick = rng.uniform(2, 11)
            tilt = rng.uniform(-0.03, 0.03) * length
            draw.polygon([(x0, y), (x0 + length, y + tilt - thick / 2), (x0 + length, y + tilt + thick / 2)], fill=255)
    elif kind == "gloom":
        for _ in range(60):
            x = rng.uniform(0, W)
            length = rng.uniform(H * 0.12, H * 0.42)
            thick = rng.uniform(3, 14)
            draw.polygon([(x - thick / 2, -5), (x + thick / 2, -5), (x, length)], fill=255)
    return big


def motion_blur(img: Image.Image, pixels: int) -> Image.Image:
    if pixels < 2:
        return img
    arr = np.asarray(img, dtype=np.float32)
    acc = np.zeros_like(arr)
    shifts = np.linspace(-pixels, pixels, 7).astype(int)
    for s in shifts:
        acc += np.roll(arr, int(s), axis=1)
    return Image.fromarray((acc / len(shifts)).astype(np.uint8), "L")


def make_frame_overlay() -> tuple[Image.Image, Image.Image]:
    """The page border: white gutter plus a black panel line. Returns (pixels, mask)."""
    pixels = Image.new("L", (W, H), 255)
    mask = Image.new("L", (W, H), 255)
    ImageDraw.Draw(mask).rectangle(
        (FRAME_MARGIN + FRAME_LINE, FRAME_MARGIN + FRAME_LINE, W - FRAME_MARGIN - FRAME_LINE - 1,
         H - FRAME_MARGIN - FRAME_LINE - 1), fill=0)
    d = ImageDraw.Draw(pixels)
    d.rectangle((FRAME_MARGIN, FRAME_MARGIN, W - FRAME_MARGIN - 1, H - FRAME_MARGIN - 1), outline=0, width=FRAME_LINE)
    return pixels, mask


def make_grain(seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 1, (H // 2, W // 2)).astype(np.float32)
    img = Image.fromarray(np.clip(250 + noise * 3, 220, 255).astype(np.uint8), "L")
    return img.resize((W, H), Image.Resampling.NEAREST)


class SfxText:
    """Hand-lettered onomatopoeia that pops onto the page, like THUD! or SHHK!"""

    def __init__(self, spec: dict[str, Any]):
        self.text = str(spec["text"]).upper()
        self.at = float(spec.get("at", 0.0))
        self.hold = float(spec.get("hold", 1.1))
        self.x = float(spec.get("x", 0.5))
        self.y = float(spec.get("y", 0.3))
        self.rot = float(spec.get("rot", -8))
        size = int(spec.get("size", 230))
        self.black = spec.get("color", "black") == "black"
        font = _font(size)
        pad = 40
        probe = ImageDraw.Draw(Image.new("L", (10, 10)))
        box = probe.textbbox((0, 0), self.text, font=font, stroke_width=14)
        layer = Image.new("LA", (box[2] - box[0] + pad * 2, box[3] - box[1] + pad * 2), (0, 0))
        fill, stroke = ((0, 255), (255, 255)) if self.black else ((255, 255), (0, 255))
        ImageDraw.Draw(layer).text((pad - box[0], pad - box[1]), self.text, font=font,
                                   fill=fill, stroke_width=14, stroke_fill=stroke)
        self.layer = layer.rotate(self.rot, expand=True, resample=Image.Resampling.BICUBIC)

    def apply(self, img: Image.Image, t: float) -> Image.Image:
        local = t - self.at
        if local < 0 or local > self.hold:
            return img
        pop = 0.16
        if local < pop:
            scale = 0.25 + 0.95 * (local / pop)
        else:
            scale = 1.0 + 0.16 * math.exp(-(local - pop) * 9) * math.cos((local - pop) * 28)
        fade = 1.0 if local < self.hold - 0.15 else max(0.0, (self.hold - local) / 0.15)
        size = (max(2, int(self.layer.width * scale)), max(2, int(self.layer.height * scale)))
        layer = self.layer.resize(size, Image.Resampling.BILINEAR)
        gray, alpha = layer.split()
        if fade < 1.0:
            alpha = alpha.point(lambda a: int(a * fade))
        jitter = (math.sin(local * 70) * 3, math.cos(local * 83) * 3) if local < 0.5 else (0, 0)
        px = int(min(max(self.x * W - size[0] / 2 + jitter[0], 28), max(28, W - size[0] - 28)))
        py = int(min(max(self.y * H - size[1] / 2 + jitter[1], 28), max(28, H - size[1] - 28)))
        out = img.copy()
        out.paste(gray, (px, py), alpha)
        return out


# --------------------------------------------------------------------------- timing / captions

def _ass_time(seconds: float) -> str:
    cs = max(0, round(seconds * 100))
    hours, rem = divmod(cs, 360000)
    minutes, rem = divmod(rem, 6000)
    secs, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _caption_chunks(text: str, limit: int = 4) -> list[list[str]]:
    """Split a line into short caption phrases, preferring punctuation breaks."""
    words = text.split()
    chunks: list[list[str]] = []
    current: list[str] = []
    for word in words:
        current.append(word)
        if (len(current) >= limit) or (len(current) >= 3 and re.search(r"[,.;:!?—-]$", word)):
            chunks.append(current)
            current = []
    if current:
        if chunks and len(current) == 1 and len(chunks[-1]) < limit:
            chunks[-1].extend(current)
        else:
            chunks.append(current)
    return chunks


def write_captions(timeline: list[dict[str, Any]], path: Path) -> None:
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Manga,DejaVu Sans,54,&H002020D8,&H00101010,&H00FAFAFA,&H00000000,-1,0,0,0,100,100,1,0,3,16,0,2,110,110,190,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    for entry in timeline:
        chunks = _caption_chunks(entry["narration"])
        weights = [sum(max(len(re.sub(r"\W", "", w)), 1) for w in chunk) + 1 for chunk in chunks]
        total = sum(weights)
        cursor = entry["speech_start"]
        for chunk, weight in zip(chunks, weights):
            end = cursor + entry["speech"] * weight / total
            parts = []
            chunk_w = sum(max(len(re.sub(r"\W", "", w)), 1) for w in chunk)
            for word in chunk:
                ww = max(len(re.sub(r"\W", "", word)), 1)
                cs = max(1, round((end - cursor) * ww / chunk_w * 100))
                safe = word.upper().replace("{", r"\{").replace("}", r"\}")
                parts.append(f"{{\\k{cs}}}{safe}")
            events.append(f"Dialogue: 0,{_ass_time(cursor)},{_ass_time(end)},Manga,,0,0,0,,{' '.join(parts)}")
            cursor = end
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")


def plan_timeline(story: dict[str, Any], speeches: list[float]) -> list[dict[str, Any]]:
    """Cut each shot to its own narration line: lead-in, speech, then a beat of silence."""
    timeline: list[dict[str, Any]] = []
    cursor = 0.0
    shots = story["shots"]
    for index, (shot, speech) in enumerate(zip(shots, speeches)):
        lead = float(shot.get("lead", FIRST_LEAD if index == 0 else 0.0))
        ends_sentence = str(shot["narration"]).rstrip().endswith((".", "!", "?"))
        flow_gap = SENTENCE_GAP if ends_sentence else CLAUSE_GAP
        tail = float(shot.get("pause", FINAL_TAIL if index == len(shots) - 1 else flow_gap))
        duration = max(float(shot.get("min_duration", 0)), lead + speech + tail)
        timeline.append({
            "index": index + 1, "start": cursor, "duration": duration, "lead": lead,
            "speech": speech, "speech_start": cursor + lead, "narration": shot["narration"],
        })
        cursor += duration
    return timeline


def resolve_mood(story: dict[str, Any]) -> str:
    """STORY_MOOD env > story['mood'] > keyword detection from the narration."""
    import os

    choice = (os.environ.get("STORY_MOOD") or story.get("mood") or "auto").strip().lower()
    if choice in ("", "auto"):
        text = " ".join(str(s.get("narration", "")) for s in story["shots"])
        return sound.detect_mood(text)
    if choice not in sound.MOODS:
        raise ValueError(f"Unknown mood '{choice}'. Choose from {', '.join(sound.MOODS)}")
    return choice


def build_sfx(story: dict[str, Any], timeline: list[dict[str, Any]], mood: str = "mystery") -> list[tuple[float, str, float]]:
    events: list[tuple[float, str, float]] = []
    for shot, entry in zip(story["shots"], timeline):
        start = entry["start"]
        fx = set(shot.get("fx", []))
        transition = shot.get("transition", "cut")
        if transition == "whip" or shot.get("camera", "").startswith("whip"):
            events.append((max(0.0, start - 0.08), "whoosh", 0.8))
        if "impact" in fx:
            if mood in sound.TENSE_MOODS and start >= 1.2:
                events.append((start - 1.2, "riser", 0.55))  # tension builds into the hit
            events.append((start, "stinger" if mood == "horror" else "impact", 1.0))
        for spec in shot.get("sfx", []):
            events.append((start + float(spec.get("at", 0.0)), spec["name"], float(spec.get("gain", 1.0))))
        fx_text = shot.get("sfx_text")
        if fx_text and not any(s.get("name") in {"impact", "crowd", "coin", "chime"} for s in shot.get("sfx", [])) and "impact" not in fx:
            events.append((start + float(fx_text.get("at", 0.0)), "impact", 0.7))
    return events


# --------------------------------------------------------------------------- main render

def _blend_white(img: Image.Image, amount: float) -> Image.Image:
    return Image.blend(img, Image.new("L", img.size, 255), max(0.0, min(1.0, amount)))


def _frame_image(panel: Image.Image, shot: dict[str, Any], entry: dict[str, Any], frame: int,
                 masks: dict[str, list[Image.Image]], light: bool, sfx_text: SfxText | None) -> Image.Image:
    t = frame / FPS
    u = t / entry["duration"]
    zoom, ax, ay, roll = sample_camera(shot, u)
    sdx, sdy, sroll = shake_offset(shot, t, entry["index"])
    img = render_view(panel, zoom, ax, ay, roll + sroll, sdx, sdy)

    transition = shot.get("transition", "cut")
    if transition == "whip" and frame < 7:
        img = motion_blur(img, int(90 * (1 - frame / 7) ** 2))

    fx = shot.get("fx", [])
    flicker = (frame // 2) % 4
    focus = tuple(shot.get("focus", (0.5, 0.45)))
    envelope = min(1.0, t / 0.18) * (1.0 if u < 0.85 else max(0.0, (1 - u) / 0.15))
    for name in ("speed_lines", "focus_lines", "gloom"):
        if name in fx:
            mask = masks[name][flicker]
            if name == "gloom":
                mask = mask.point(lambda v: int(v * 0.95 * envelope))
            elif envelope < 1.0:
                mask = mask.point(lambda v: int(v * envelope))
            img.paste(0 if light else 255, mask=mask)

    if sfx_text is not None:
        img = sfx_text.apply(img, t)

    if "impact" in fx and frame < 5:
        img = ImageOps.invert(img) if frame < 2 else _blend_white(img, 0.75 * (1 - (frame - 2) / 3))
    if "flash" in fx and frame < 4:
        img = _blend_white(img, 0.8 * (1 - frame / 4))
    if transition == "flash" and frame < 4:
        img = _blend_white(img, 0.8 * (1 - frame / 4))
    if transition == "dip" and frame < 9:
        img = Image.blend(img, Image.new("L", img.size, 0), 1 - frame / 9)
    # Soft fade to black on the last shot's final half second.
    if entry.get("fade_out") and entry["duration"] - t < 0.6:
        img = Image.blend(img, Image.new("L", img.size, 255), 1 - (entry["duration"] - t) / 0.6)
    return img


def render_manga_story(story: dict[str, Any], output: str | Path) -> Path:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("FFmpeg was not found. Install FFmpeg and make sure it is on PATH.")
    project_dir = Path(story["_project_dir"])
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    shots = story["shots"]
    options = story.get("manga", {})

    for shot in shots:
        if not (project_dir / shot["image"]).is_file():
            raise FileNotFoundError(f"Missing shot image: {project_dir / shot['image']}")
        if not str(shot.get("narration", "")).strip():
            raise ValueError("Manga mode needs a narration line on every shot")

    with tempfile.TemporaryDirectory(prefix="manga-") as tmp_name:
        tmp = Path(tmp_name)
        voice_paths = generate_voice_lines([s["narration"] for s in shots], tmp, "voice")
        clips = [sound.read_wav(p) for p in voice_paths]
        speeches = [clip.size / sound.RATE for clip in clips]
        timeline = plan_timeline(story, speeches)
        mood = resolve_mood(story)
        print(f"Soundtrack mood: {mood}")
        timeline[-1]["fade_out"] = bool(options.get("fade_out", True))
        total = timeline[-1]["start"] + timeline[-1]["duration"]
        print(f"Manga timeline: {len(shots)} shots, {total:.1f}s, speech {sum(speeches):.1f}s")

        mix = sound.mix_soundtrack(
            total,
            [(e["speech_start"], c) for e, c in zip(timeline, clips)],
            build_sfx(story, timeline, mood),
            music=bool(options.get("music", True)),
            mood=mood,
        )
        mix_path = sound.write_wav(tmp / "mix.wav", mix)
        caption_path = tmp / "captions.ass"
        write_captions(timeline, caption_path)

        pixels_frame, mask_frame = make_frame_overlay()
        grains = [make_grain(11 + i) for i in range(3)] if options.get("grain", True) else []
        escaped = caption_path.resolve().as_posix().replace(":", r"\:").replace("'", r"\'")
        lut_r = [round(INK[0] + (PAPER[0] - INK[0]) * i / 255) for i in range(256)]
        lut_g = [round(INK[1] + (PAPER[1] - INK[1]) * i / 255) for i in range(256)]
        lut_b = [round(INK[2] + (PAPER[2] - INK[2]) * i / 255) for i in range(256)]
        command = [
            "ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
            "-i", str(mix_path),
            "-vf", f"subtitles='{escaped}'",
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-maxrate", "8M", "-bufsize", "16M", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-af", "highpass=f=60,loudnorm=I=-16:TP=-1.5:LRA=11",
            "-t", f"{total:.3f}", "-movflags", "+faststart", str(out),
        ]
        command[1:1] = ["-loglevel", "error"]
        log_path = tmp / "ffmpeg.log"
        log_file = log_path.open("wb")
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log_file)
        frame_counter = 0
        try:
            for shot, entry in zip(shots, timeline):
                panel = prepare_panel(project_dir / shot["image"], tone=bool(options.get("tone", True)))
                light = mean_brightness(panel) > 120  # black lines on light art, white on dark
                lettering = SfxText(shot["sfx_text"]) if shot.get("sfx_text") else None
                focus = tuple(shot.get("focus", (0.5, 0.45)))
                masks = {
                    kind: [line_mask(kind, v, focus) for v in range(4)]
                    for kind in ("speed_lines", "focus_lines", "gloom") if kind in shot.get("fx", [])
                }
                for local in range(max(1, round(entry["duration"] * FPS))):
                    img = _frame_image(panel, shot, entry, local, masks, light, lettering)
                    if grains:
                        img = ImageChops.multiply(img, grains[(frame_counter // 3) % 3])
                    img.paste(pixels_frame, mask=mask_frame)
                    rgb = Image.merge("RGB", (img.point(lut_r), img.point(lut_g), img.point(lut_b)))
                    proc.stdin.write(rgb.tobytes())
                    frame_counter += 1
            proc.stdin.close()
            proc.wait()
            log_file.close()
            if proc.returncode:
                raise RuntimeError("FFmpeg manga render failed:\n" + log_path.read_text(errors="replace")[-1500:])
        except Exception:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            raise

    report = [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in e.items() if k != "fade_out"} for e in timeline]
    out.with_suffix(".timeline.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return out
