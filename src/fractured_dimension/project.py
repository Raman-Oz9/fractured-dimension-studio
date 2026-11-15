"""Example project creation and story manifest validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def validate_story(data: dict[str, Any]) -> None:
    if not isinstance(data.get("title"), str) or not data["title"].strip():
        raise ValueError("Story must have a non-empty title")
    shots = data.get("shots")
    if not isinstance(shots, list) or not shots:
        raise ValueError("Story must contain at least one shot")
    for index, shot in enumerate(shots, start=1):
        if not isinstance(shot, dict):
            raise ValueError(f"Shot {index} must be an object")
        for field in ("image", "duration", "camera"):
            if field not in shot:
                raise ValueError(f"Shot {index} is missing '{field}'")
        if not isinstance(shot["duration"], (int, float)) or shot["duration"] <= 0:
            raise ValueError(f"Shot {index} duration must be positive")
        if shot["camera"] not in {"push_in", "pull_out", "pan_left", "pan_right", "hold"}:
            raise ValueError(f"Shot {index} has an unsupported camera move")


def load_story(path: str | Path) -> dict[str, Any]:
    story_path = Path(path)
    data = json.loads(story_path.read_text(encoding="utf-8"))
    validate_story(data)
    data["_project_dir"] = str(story_path.parent)
    return data


def create_example(output: str | Path) -> Path:
    root = Path(output)
    (root / "images").mkdir(parents=True, exist_ok=True)
    story = {
        "title": "The Signal Beneath the City",
        "format": {"width": 1080, "height": 1920, "fps": 30},
        "shots": [
            {
                "image": "images/shot-01.png",
                "duration": 4,
                "camera": "push_in",
                "image_prompt": "Cinematic graphic-novel illustration of a fully clothed adult urban explorer standing in a futuristic city plaza at night, a mysterious bright cyan geometric light glowing from a circular symbol on the pavement, dramatic wide composition, expressive ink outlines, layered paper textures, fractured perspective, atmospheric rain reflections, no violence, no nudity",
            },
            {
                "image": "images/shot-02.png",
                "duration": 4,
                "camera": "pull_out",
                "image_prompt": "Cinematic graphic-novel close-up of a fully clothed adult explorer wearing a dark jacket and protective glove, gloved hand reaching toward a small floating cyan geometric hologram above a clean stone surface, violet and amber city lights, bold ink outlines, textured mixed-media illustration, dramatic depth, no violence, no nudity",
            },
        ],
    }
    validate_story(story)
    (root / "story.json").write_text(json.dumps(story, indent=2), encoding="utf-8")
    return root
