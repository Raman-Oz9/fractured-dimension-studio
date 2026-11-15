"""Example project creation and story manifest validation."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def validate_story(data: dict[str, Any]) -> None:
    if not isinstance(data.get("title"), str) or not data["title"].strip():
        raise ValueError("Story must have a non-empty title")
    shots = data.get("shots")
    if not isinstance(shots, list) or not shots:
        raise ValueError("Story must contain at least one shot")
    narration = data.get("narration")
    if narration is not None and not isinstance(narration, str):
        raise ValueError("narration must be a string when provided")
    bible = data.get("character_bible", {})
    if not isinstance(bible, dict):
        raise ValueError("character_bible must be an object")
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
        camera_path = shot.get("camera_path")
        if camera_path is not None:
            if not isinstance(camera_path, list) or len(camera_path) < 2:
                raise ValueError(f"Shot {index} camera_path must contain at least two keyframes")
            previous_at = -1.0
            for keyframe in camera_path:
                if not isinstance(keyframe, dict) or set(keyframe) != {"at", "zoom", "x", "y"}:
                    raise ValueError(
                        f"Shot {index} camera_path keyframes need exactly at, zoom, x and y"
                    )
                values = [keyframe[name] for name in ("at", "zoom", "x", "y")]
                if any(not isinstance(value, (int, float)) or isinstance(value, bool)
                       or not math.isfinite(value) for value in values):
                    raise ValueError(f"Shot {index} camera_path values must be finite numbers")
                at, zoom, x, y = values
                if not 0 <= at <= 1 or at <= previous_at:
                    raise ValueError(f"Shot {index} camera_path times must increase from 0 to 1")
                if not 1.0 <= zoom <= 1.6 or not 0 <= x <= 1 or not 0 <= y <= 1:
                    raise ValueError(f"Shot {index} camera_path zoom/anchors are out of range")
                previous_at = at
            if camera_path[0]["at"] != 0 or camera_path[-1]["at"] != 1:
                raise ValueError(f"Shot {index} camera_path must start at 0 and end at 1")
        character_ids = shot.get("character_ids", [])
        if not isinstance(character_ids, list) or not all(
            isinstance(item, str) for item in character_ids
        ):
            raise ValueError(f"Shot {index} character_ids must be a list of strings")
        for character_id in character_ids:
            if character_id not in bible:
                raise ValueError(
                    f"Shot {index} references unknown character_id '{character_id}'"
                )


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
        "narration": (
            "Beneath the city, a hidden signal awakens. "
            "Mara reaches toward the light—and something answers."
        ),
        "format": {"width": 1080, "height": 1920, "fps": 30},
        "style_lock": (
            "Fractured Dimension retro-cinematic graphic novel: bold expressive ink "
            "outlines, subtle 35mm film grain, fine halftone print shading, tactile "
            "aged-paper and screen-print texture, slightly faded vintage colour palette "
            "with restrained teal, rust, ochre and dusty rose accents, dimensional "
            "fractured geometry, cinematic lighting with readable midtones and clear "
            "facial expressions. Keep grain fine and controlled, never blur the subject, "
            "never obscure facial details, and avoid excessive noise or crushed blacks. "
            "Premium illustrated retro editorial look, not photorealism."
        ),
        "character_bible": {
            "MARA": {
                "visual_identity": (
                    "Mara is the same adult woman in every shot, with a short "
                    "asymmetrical black bob haircut, a small silver ear cuff on her "
                    "left ear, warm brown eyes, an olive utility jacket with a "
                    "distinctive amber shoulder stripe, charcoal shirt, and black gloves. "
                    "Keep her face, haircut, jacket and proportions unchanged."
                ),
                "reference_image": "images/character-mara-reference.png",
                "reference_prompt": (
                    "Design a polished recurring-character reference image for Mara. "
                    "Use a neutral muted-grey studio background, clear silhouette, "
                    "front three-quarter full-body pose and a separate readable face "
                    "portrait inset as a clearly separated reference-sheet panel. The "
                    "portrait inset is intentional only on this reference sheet; do not "
                    "duplicate the head in normal story shots. Correct human anatomy, "
                    "one head attached naturally to one neck and torso. Retro printed "
                    "graphic-novel concept-art presentation with subtle film grain and "
                    "fine halftone texture."
                ),
            }
        },
        "shots": [
            {
                "image": "images/shot-01.png",
                "duration": 4,
                "camera": "push_in",
                "camera_path": [
                    {"at": 0.0, "zoom": 1.0, "x": 0.50, "y": 0.50},
                    {"at": 0.30, "zoom": 1.07, "x": 0.51, "y": 0.49},
                    {"at": 0.72, "zoom": 1.17, "x": 0.53, "y": 0.44},
                    {"at": 1.0, "zoom": 1.24, "x": 0.53, "y": 0.42},
                ],
                "character_ids": ["MARA"],
                "image_prompt": (
                    "Cinematic graphic-novel wide shot of an adult urban explorer "
                    "standing in a futuristic city plaza at night, a mysterious bright "
                    "cyan geometric light glowing from a circular symbol on the pavement. "
                    "Show her full body and the surrounding architecture, dramatic "
                    "wide composition, rain reflections."
                ),
            },
            {
                "image": "images/shot-02.png",
                "duration": 4,
                "camera": "pull_out",
                "camera_path": [
                    {"at": 0.0, "zoom": 1.26, "x": 0.54, "y": 0.43},
                    {"at": 0.32, "zoom": 1.18, "x": 0.52, "y": 0.46},
                    {"at": 0.72, "zoom": 1.08, "x": 0.50, "y": 0.49},
                    {"at": 1.0, "zoom": 1.015, "x": 0.50, "y": 0.50},
                ],
                "character_ids": ["MARA"],
                "image_prompt": (
                    "Cinematic graphic-novel close-up of the same explorer's gloved "
                    "hand reaching toward a small floating cyan geometric hologram. "
                    "Begin tight on her hand and the hologram, with part of her sleeve "
                    "and face entering the composition, violet and amber city lights."
                ),
            },
        ],
    }
    validate_story(story)
    (root / "story.json").write_text(json.dumps(story, indent=2), encoding="utf-8")
    return root
