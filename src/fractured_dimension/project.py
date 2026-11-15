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
            "Fractured Dimension graphic novel: bold expressive ink outlines, "
            "layered tactile mixed-media textures, dimensional fractured geometry, "
            "cinematic chiaroscuro, deliberate depth and coherent graphic-novel rendering."
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
                    "portrait inset. Graphic-novel concept-art presentation."
                ),
            }
        },
        "shots": [
            {
                "image": "images/shot-01.png",
                "duration": 4,
                "camera": "push_in",
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
