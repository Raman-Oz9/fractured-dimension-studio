"""FFmpeg still-image renderer with controlled cinematic camera movement."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any


def _zoom_filter(move: str, frames: int) -> str:
    # Fit by cropping excess width/height, never by stretching the source.
    # The zoompan input and output therefore share the exact 9:16 aspect ratio.
    if move == "push_in":
        zoom = "min(zoom+0.0015,1.18)"
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif move == "pull_out":
        zoom = "if(eq(on,1),1.18,max(zoom-0.0015,1.0))"
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif move == "pan_left":
        zoom = "1.12"
        x, y = "max(0,(iw-iw/zoom)*(1-on/{frames}))".format(frames=max(frames - 1, 1)), "ih/2-(ih/zoom/2)"
    elif move == "pan_right":
        zoom = "1.12"
        x, y = "min(iw-iw/zoom,(iw-iw/zoom)*(on/{frames}))".format(frames=max(frames - 1, 1)), "ih/2-(ih/zoom/2)"
    else:
        zoom = "1.04"
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    return (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,setsar=1,"
        f"zoompan=z='{zoom}':x='{x}':y='{y}':"
        f"d={frames}:s=1080x1920:fps=30,setsar=1,format=yuv420p"
    )


def render_story(story: dict[str, Any], output: str | Path) -> Path:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("FFmpeg was not found. Install FFmpeg and make sure it is on PATH.")
    project_dir = Path(story["_project_dir"])
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    segment_paths: list[Path] = []

    for index, shot in enumerate(story["shots"], start=1):
        image_path = project_dir / shot["image"]
        if not image_path.is_file():
            raise FileNotFoundError(f"Missing shot image: {image_path}")
        frames = max(1, round(float(shot["duration"]) * 30))
        segment = output_path.parent / f".{output_path.stem}-segment-{index:03d}.mp4"
        command = [
            "ffmpeg", "-y", "-loop", "1", "-i", str(image_path),
            "-vf", _zoom_filter(shot["camera"], frames),
            "-frames:v", str(frames), "-an", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "20", str(segment),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)
        segment_paths.append(segment)

    concat_file = output_path.parent / f".{output_path.stem}-concat.txt"
    concat_file.write_text(
        "".join(f"file '{p.resolve().as_posix()}'\n" for p in segment_paths),
        encoding="utf-8",
    )
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
             "-c", "copy", str(output_path)],
            check=True, capture_output=True, text=True,
        )
    finally:
        concat_file.unlink(missing_ok=True)
        for segment in segment_paths:
            segment.unlink(missing_ok=True)
    return output_path
