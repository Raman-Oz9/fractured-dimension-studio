"""Example project creation and story manifest validation."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any


_CLASSIC_MOVES = {"push_in", "pull_out", "pan_left", "pan_right", "hold"}
_MANGA_MOVES = {
    "snap_in", "crash_in", "whip_left", "whip_right", "tilt_up", "tilt_down",
    "shake_hold", "dutch_push", "drift_roll",
}
_FX = {"speed_lines", "focus_lines", "impact", "gloom", "flash"}
_TRANSITIONS = {"cut", "whip", "flash", "dip"}
_EASES = {"smooth", "snap", "linear", "in"}
_SFX = {"whoosh", "whoosh_back", "impact", "chime", "coin", "crowd", "heartbeat"}
ANGLES = {
    "eye": "eye-level medium shot",
    "low": "dramatic low-angle shot looking up, strong foreshortening",
    "high": "high-angle shot looking down",
    "birdseye": "bird's-eye view from directly above, panoramic and graphic",
    "worm": "extreme worm's-eye view from the ground, towering subjects",
    "closeup": "tight close-up on the face and eyes",
    "extreme_closeup": "extreme close-up on a single detail, eyes or hands, filling the frame",
    "wide": "very wide establishing shot with deep layered perspective",
    "over_shoulder": "over-the-shoulder shot with a foreground silhouette",
    "dutch": "tilted dutch-angle composition, unstable and tense",
}


def _validate_manga_shot(index: int, shot: dict[str, Any]) -> None:
    narration = shot.get("narration")
    if not isinstance(narration, str) or not narration.strip():
        raise ValueError(f"Shot {index} needs its own non-empty narration line in manga mode")
    fx = shot.get("fx", [])
    if not isinstance(fx, list) or any(item not in _FX for item in fx):
        raise ValueError(f"Shot {index} fx must be a list drawn from {sorted(_FX)}")
    if shot.get("transition", "cut") not in _TRANSITIONS:
        raise ValueError(f"Shot {index} has an unsupported transition")
    if shot.get("ease", "smooth") not in _EASES:
        raise ValueError(f"Shot {index} has an unsupported ease")
    if shot.get("angle") is not None and shot["angle"] not in ANGLES:
        raise ValueError(f"Shot {index} has an unknown angle; use one of {sorted(ANGLES)}")
    focus = shot.get("focus")
    if focus is not None and (
        not isinstance(focus, (list, tuple)) or len(focus) != 2
        or not all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in focus)
    ):
        raise ValueError(f"Shot {index} focus must be [x, y] between 0 and 1")
    for spec in shot.get("sfx", []):
        if not isinstance(spec, dict) or spec.get("name") not in _SFX:
            raise ValueError(f"Shot {index} sfx entries need a name from {sorted(_SFX)}")
    lettering = shot.get("sfx_text")
    if lettering is not None and (not isinstance(lettering, dict) or not str(lettering.get("text", "")).strip()):
        raise ValueError(f"Shot {index} sfx_text needs a text value")


_STOPWORDS = {
    "the", "and", "that", "with", "from", "into", "onto", "this", "then", "than", "his", "her",
    "its", "their", "they", "them", "was", "were", "has", "had", "have", "for", "but", "not",
    "all", "one", "out", "now", "just", "still", "every", "never", "only", "very", "been",
    "like", "over", "under", "after", "before", "while", "when", "where", "what", "who",
}


def lint_sync(data: dict[str, Any]) -> list[str]:
    """Warn when a shot's picture prompt never mentions things its narration names.

    Narration nouns and verbs should be visible on screen: this flags shots where a word
    the narrator says (e.g. 'broom', 'coins') has no trace in the image prompt.
    """
    warnings: list[str] = []
    for index, shot in enumerate(data.get("shots", []), start=1):
        narration = shot.get("narration")
        prompt = (shot.get("image_prompt") or "").lower()
        if not narration or not prompt:
            continue
        must_show = shot.get("must_show") or [
            w for w in re.findall(r"[a-z']{5,}", narration.lower()) if w not in _STOPWORDS
        ]
        missing = []
        for word in must_show:
            stem = word.lower().rstrip("s").rstrip("'")[:5]
            if stem not in prompt:
                missing.append(word)
        if shot.get("must_show") and missing:
            warnings.append(f"Shot {index}: must_show not in image_prompt: {', '.join(missing)}")
        elif len(missing) > max(1, len(must_show) * 0.5):
            warnings.append(f"Shot {index}: narration words absent from picture: {', '.join(missing[:6])}")
    return warnings


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
        if shot["camera"] not in _CLASSIC_MOVES | _MANGA_MOVES:
            raise ValueError(f"Shot {index} has an unsupported camera move")
        if data.get("render_style") == "manga":
            _validate_manga_shot(index, shot)
        camera_path = shot.get("camera_path")
        if camera_path is not None:
            if not isinstance(camera_path, list) or len(camera_path) < 2:
                raise ValueError(f"Shot {index} camera_path must contain at least two keyframes")
            previous_at = -1.0
            for keyframe in camera_path:
                if (not isinstance(keyframe, dict) or not {"at", "zoom", "x", "y"} <= set(keyframe)
                        or not set(keyframe) <= {"at", "zoom", "x", "y", "roll"}):
                    raise ValueError(
                        f"Shot {index} camera_path keyframes need exactly at, zoom, x and y (plus optional roll)"
                    )
                roll = keyframe.get("roll", 0)
                if not isinstance(roll, (int, float)) or isinstance(roll, bool) or abs(roll) > 12:
                    raise ValueError(f"Shot {index} camera_path roll must be within +/-12 degrees")
                values = [keyframe[name] for name in ("at", "zoom", "x", "y")]
                if any(not isinstance(value, (int, float)) or isinstance(value, bool)
                       or not math.isfinite(value) for value in values):
                    raise ValueError(f"Shot {index} camera_path values must be finite numbers")
                at, zoom, x, y = values
                if not 0 <= at <= 1 or at <= previous_at:
                    raise ValueError(f"Shot {index} camera_path times must increase from 0 to 1")
                if not 1.0 <= zoom <= 2.4 or not 0 <= x <= 1 or not 0 <= y <= 1:
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
        "title": "The Day the Moon Vanished",
        "narration": (
            "Imagine looking up at the night sky—and the Moon is gone. "
            "For a few terrifying minutes, the tides seem to shift and the world holds its breath. "
            "But the Moon has not vanished. A rare celestial alignment has hidden it from view. "
            "The universe can make the impossible look real."
        ),
        "format": {"width": 1080, "height": 1920, "fps": 30},
        "style_lock": (
            "Fractured Dimension signature retro print-comic aesthetic, unmistakably "
            "hand-illustrated rather than clean digital concept art: expressive heavy "
            "ink contours, imperfect hand-drawn linework, visible fine-to-medium 35mm "
            "film grain across the entire image, dense vintage halftone dot shading in "
            "midtones and shadows, subtle paper fibres, worn screen-print texture, "
            "slight ink misregistration and softly distressed edges. Use a restrained "
            "1970s-1980s editorial colour grade: faded teal, tobacco brown, rust, "
            "ochre, muted cream and dusty rose; warm aged-paper undertones, rich but "
            "not neon, with cinematic chiaroscuro and readable faces. Avoid glossy "
            "3D rendering, photorealism, sterile vector art, smooth plastic gradients, "
            "over-sharp digital surfaces and excessive clean cyan. "
            "fractured geometry, cinematic lighting with readable midtones and clear "
            "facial expressions. Keep grain fine and controlled, never blur the subject, "
            "never obscure facial details, and avoid excessive noise or crushed blacks. "
            "Premium illustrated retro editorial look, not photorealism. Compose with distinct foreground, middle ground and background planes, strong visual separation, and enough surrounding image detail for deliberate camera travel."
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
                "image": "images/shot-01.png", "duration": 4, "camera": "push_in",
                "camera_path": [
                    {"at": 0.0, "zoom": 1.0, "x": 0.50, "y": 0.52},
                    {"at": 0.45, "zoom": 1.22, "x": 0.52, "y": 0.43},
                    {"at": 1.0, "zoom": 1.43, "x": 0.50, "y": 0.36}
                ],
                "image_prompt": "A breathtaking retro illustrated graphic-novel view of a quiet modern city at midnight, crowds on rooftops staring upward at a completely moonless deep navy sky, empty circular gap among stars where the full moon should be, dramatic silhouettes, layered rooftops and distant skyline, eerie amber streetlights, no text."
            },
            {
                "image": "images/shot-02.png", "duration": 4, "camera": "pan_left",
                "camera_path": [
                    {"at": 0.0, "zoom": 1.10, "x": 0.88, "y": 0.48},
                    {"at": 0.5, "zoom": 1.22, "x": 0.50, "y": 0.46},
                    {"at": 1.0, "zoom": 1.30, "x": 0.14, "y": 0.44}
                ],
                "image_prompt": "A cinematic retro science-comic illustration of a vast ocean at night under an unnaturally dark sky, powerful waves rolling toward a distant coastal city, tiny lighthouse beam cutting through mist, layered foreground foam and background skyline, moody teal, rust and muted cream palette, no text."
            },
            {
                "image": "images/shot-03.png", "duration": 4, "camera": "push_in",
                "camera_path": [
                    {"at": 0.0, "zoom": 1.0, "x": 0.50, "y": 0.50},
                    {"at": 0.5, "zoom": 1.24, "x": 0.56, "y": 0.43},
                    {"at": 1.0, "zoom": 1.48, "x": 0.60, "y": 0.40}
                ],
                "image_prompt": "A dramatic vintage editorial astronomy illustration: enormous dark silhouette of Earth in space, bright sun and distant planets aligned behind it, the Moon obscured in a rare celestial alignment, intricate star field, luminous amber rim light and faded teal shadows, no labels or text."
            },
            {
                "image": "images/shot-04.png", "duration": 4, "camera": "pull_out",
                "camera_path": [
                    {"at": 0.0, "zoom": 1.50, "x": 0.52, "y": 0.48},
                    {"at": 0.5, "zoom": 1.24, "x": 0.50, "y": 0.50},
                    {"at": 1.0, "zoom": 1.02, "x": 0.50, "y": 0.50}
                ],
                "image_prompt": "A spectacular retro printed-comic view of the Moon reappearing above Earth's curved horizon, glowing pale cream against a deep starry sky, tiny spacecraft silhouette for scale, cinematic reveal, layered atmospheric depth, halftone shading and worn paper texture, no text."
            }
        ],
    }
    validate_story(story)
    (root / "story.json").write_text(json.dumps(story, indent=2), encoding="utf-8")
    return root
