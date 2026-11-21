"""FFmpeg still-image renderer with continuous, keyframed camera choreography."""

from __future__ import annotations

import shutil
import subprocess
import re
import wave
from pathlib import Path
from typing import Any

from .voice import generate_voiceover
from .procedural import render_procedural_story

# Camera anchors describe the visible crop: x=0 is left, x=1 is right;
# y=0 is top, y=1 is bottom. Zoom and crop position move together.
_CAMERA_PRESETS: dict[str, list[dict[str, float]]] = {
    "push_in": [
        {"at": 0.0, "zoom": 1.0, "x": 0.50, "y": 0.50},
        {"at": 0.28, "zoom": 1.06, "x": 0.51, "y": 0.49},
        {"at": 0.72, "zoom": 1.16, "x": 0.52, "y": 0.45},
        {"at": 1.0, "zoom": 1.22, "x": 0.52, "y": 0.44},
    ],
    "pull_out": [
        {"at": 0.0, "zoom": 1.24, "x": 0.50, "y": 0.48},
        {"at": 0.30, "zoom": 1.17, "x": 0.49, "y": 0.49},
        {"at": 0.72, "zoom": 1.08, "x": 0.50, "y": 0.50},
        {"at": 1.0, "zoom": 1.015, "x": 0.50, "y": 0.50},
    ],
    # A pan crosses the illustration while a gentle push adds dimensionality.
    "pan_left": [
        {"at": 0.0, "zoom": 1.10, "x": 0.88, "y": 0.50},
        {"at": 0.45, "zoom": 1.13, "x": 0.52, "y": 0.49},
        {"at": 1.0, "zoom": 1.16, "x": 0.14, "y": 0.48},
    ],
    "pan_right": [
        {"at": 0.0, "zoom": 1.10, "x": 0.12, "y": 0.50},
        {"at": 0.45, "zoom": 1.13, "x": 0.48, "y": 0.49},
        {"at": 1.0, "zoom": 1.16, "x": 0.86, "y": 0.48},
    ],
    # Even a hold has a restrained drift, avoiding a frozen slideshow frame.
    "hold": [
        {"at": 0.0, "zoom": 1.035, "x": 0.49, "y": 0.50},
        {"at": 0.55, "zoom": 1.045, "x": 0.50, "y": 0.495},
        {"at": 1.0, "zoom": 1.055, "x": 0.51, "y": 0.49},
    ],
}


def _number(value: float) -> str:
    return f"{value:.7g}"


def _keyframed_expression(
    keyframes: list[dict[str, float]], field: str, frames: int
) -> str:
    """Build piecewise smoothstep interpolation over the shot's frame range."""
    last_frame = max(frames - 1, 1)
    progress = f"min(max(on/{last_frame},0),1)"
    expression = _number(keyframes[-1][field])
    for start, end in reversed(list(zip(keyframes, keyframes[1:]))):
        span = end["at"] - start["at"]
        local = f"min(max(({progress}-{_number(start['at'])})/{_number(span)},0),1)"
        eased = f"({local}*{local}*(3-2*{local}))"
        a, b = _number(start[field]), _number(end[field])
        segment = f"({a}+({b}-{a})*{eased})"
        expression = f"if(lte({progress},{_number(end['at'])}),{segment},{expression})"
    return expression


def _zoom_filter(
    move: str,
    frames: int,
    camera_path: list[dict[str, float]] | None = None,
) -> str:
    """Create a continuous camera path; custom keyframes override the move preset."""
    keyframes = camera_path or _CAMERA_PRESETS[move]
    zoom = _keyframed_expression(keyframes, "zoom", frames)
    anchor_x = _keyframed_expression(keyframes, "x", frames)
    anchor_y = _keyframed_expression(keyframes, "y", frames)
    # Convert normalized focal anchors into legal zoompan crop coordinates.
    x = f"(iw-iw/zoom)*({anchor_x})"
    y = f"(ih-ih/zoom)*({anchor_y})"
    return (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,setsar=1,"
        f"zoompan=z='{zoom}':x='{x}':y='{y}':"
        f"d={frames}:s=1080x1920:fps=30,setsar=1,format=yuv420p"
    )


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, cs = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{cs:02d}"


def _write_ass_captions(text: str, duration: float, path: Path) -> None:
    """Write stylish, approximate word-timed ASS captions for the narration."""
    words = re.findall(r"\S+", text.strip())
    if not words or duration <= 0:
        return

    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Retro,DejaVu Sans,58,&H00E9E2D2,&H003BC7FF,&H00130F0B,&H990D171F,-1,0,0,0,100,100,0.5,0,3,2.5,1.5,2,90,90,250,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    # Four-word phrases keep each caption readable on a phone screen.
    chunks = [words[i:i + 4] for i in range(0, len(words), 4)]
    weights = [sum(max(len(re.sub(r"\W", "", w)), 1) for w in chunk) for chunk in chunks]
    total_weight = sum(weights)
    cursor = 0.0
    events: list[str] = []
    for chunk, weight in zip(chunks, weights):
        start = cursor
        end = start + duration * weight / total_weight
        chunk_weight = sum(max(len(re.sub(r"\W", "", w)), 1) for w in chunk)
        parts: list[str] = []
        for word in chunk:
            word_weight = max(len(re.sub(r"\W", "", word)), 1)
            karaoke_cs = max(1, round((end - start) * word_weight / chunk_weight * 100))
            safe_word = word.replace("{", r"\{").replace("}", r"\}")
            parts.append(f"{{\\k{karaoke_cs}}}{safe_word}")
        events.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Retro,,0,0,0,,"
            + " ".join(parts)
        )
        cursor = end
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")


FPS = 30
# Narration is never clipped: when speech is longer than the planned picture, every
# shot is stretched proportionally (camera paths are normalised, so they simply play
# slower). Beyond this ratio the script needs shortening rather than a sluggish edit.
MAX_PICTURE_STRETCH = 1.5
NARRATION_TAIL_SECONDS = 0.6


def _fit_durations_to_narration(
    durations: list[float], speech_seconds: float
) -> list[float]:
    """Return shot durations long enough to hold the whole narration plus a short tail."""
    picture = sum(durations)
    needed = speech_seconds + NARRATION_TAIL_SECONDS
    if needed <= picture:
        return list(durations)
    factor = needed / picture
    if factor > MAX_PICTURE_STRETCH:
        raise RuntimeError(
            f"Narration fit QC failed: {speech_seconds:.1f}s of speech needs {needed:.1f}s "
            f"of picture but the shots total {picture:.1f}s (x{factor:.2f}, limit "
            f"x{MAX_PICTURE_STRETCH}). Shorten the narration or lengthen the shots."
        )
    return [duration * factor for duration in durations]


def _wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as audio:
        return audio.getnframes() / float(audio.getframerate())


def render_story(story: dict[str, Any], output: str | Path) -> Path:
    if story.get("render_style") == "manga":
        from .manga import render_manga_story

        return render_manga_story(story, output)
    if story.get("render_mode") == "procedural":
        return render_procedural_story(story, output)
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("FFmpeg was not found. Install FFmpeg and make sure it is on PATH.")
    project_dir = Path(story["_project_dir"])
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stem = output_path.stem
    segment_paths: list[Path] = []
    concat_file = output_path.parent / f".{stem}-concat.txt"
    silent_output = output_path.parent / f".{stem}-silent.mp4"
    voice_path = output_path.parent / f".{stem}-voice.wav"
    caption_path = output_path.parent / f".{stem}-captions.ass"

    # Fail fast on missing art before spending time on narration.
    for shot in story["shots"]:
        image_path = project_dir / shot["image"]
        if not image_path.is_file():
            raise FileNotFoundError(f"Missing shot image: {image_path}")

    durations = [float(shot["duration"]) for shot in story["shots"]]
    narration = story.get("narration")
    speech_seconds = 0.0
    try:
        if narration:
            generate_voiceover(str(narration), voice_path)
            speech_seconds = _wav_seconds(voice_path)
            planned = sum(durations)
            durations = _fit_durations_to_narration(durations, speech_seconds)
            print(
                f"Narration {speech_seconds:.1f}s, planned picture {planned:.1f}s, "
                f"final picture {sum(durations):.1f}s"
            )

        frame_counts = [max(1, round(d * FPS)) for d in durations]
        for index, (shot, frames) in enumerate(zip(story["shots"], frame_counts), start=1):
            segment = output_path.parent / f".{stem}-segment-{index:03d}.mp4"
            segment_paths.append(segment)
            command = [
                "ffmpeg", "-y", "-loop", "1", "-i", str(project_dir / shot["image"]),
                "-vf", _zoom_filter(shot["camera"], frames, shot.get("camera_path")),
                "-frames:v", str(frames), "-an", "-c:v", "libx264",
                "-preset", "veryfast", "-crf", "20", str(segment),
            ]
            subprocess.run(command, check=True, capture_output=True, text=True)

        concat_file.write_text(
            "".join(f"file '{p.resolve().as_posix()}'\n" for p in segment_paths),
            encoding="utf-8",
        )
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
             "-c", "copy", str(silent_output)],
            check=True, capture_output=True, text=True,
        )
        if narration:
            picture_seconds = sum(frame_counts) / FPS
            _write_ass_captions(str(narration), speech_seconds, caption_path)
            escaped_caption_path = caption_path.resolve().as_posix().replace(":", r"\:").replace("'", r"\'")
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(silent_output), "-i", str(voice_path),
                    "-vf", f"subtitles='{escaped_caption_path}'",
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "19",
                    "-c:a", "aac", "-b:a", "192k", "-af", "apad",
                    "-t", f"{picture_seconds:.3f}", "-movflags", "+faststart",
                    str(output_path),
                ],
                check=True, capture_output=True, text=True,
            )
        else:
            silent_output.replace(output_path)
    finally:
        for leftover in (concat_file, silent_output, voice_path, caption_path, *segment_paths):
            leftover.unlink(missing_ok=True)
    return output_path
