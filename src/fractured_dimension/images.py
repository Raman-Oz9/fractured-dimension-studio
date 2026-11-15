"""Multi-model image generation and prompt-level character continuity."""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MODEL_IDS = {
    "flux-schnell": "@cf/black-forest-labs/flux-1-schnell",
    "flux-2-dev": "@cf/black-forest-labs/flux-2-dev",
    "sdxl-lightning": "@cf/bytedance/stable-diffusion-xl-lightning",
    "sdxl-base": "@cf/stabilityai/stable-diffusion-xl-base-1.0",
    "dreamshaper": "@cf/lykon/dreamshaper-8-lcm",
}
DEFAULT_MODEL = MODEL_IDS["flux-schnell"]
DEFAULT_FALLBACKS = [
    MODEL_IDS["sdxl-lightning"],
    MODEL_IDS["sdxl-base"],
]


def _resolve_model(value: str) -> str:
    value = value.strip()
    return MODEL_IDS.get(value.lower(), value)


def _model_chain(preferred: str | None = None) -> list[str]:
    primary = _resolve_model(
        preferred or os.getenv("CLOUDFLARE_MODEL") or DEFAULT_MODEL
    )
    configured = os.getenv("CLOUDFLARE_FALLBACK_MODELS")
    fallbacks = (
        [_resolve_model(item) for item in configured.split(",") if item.strip()]
        if configured is not None
        else DEFAULT_FALLBACKS
    )
    return list(dict.fromkeys([primary, *fallbacks]))


def _request_image(prompt: str, destination: Path, model: str) -> Path:
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    api_token = os.getenv("CLOUDFLARE_API_TOKEN")
    if not account_id or not api_token:
        raise RuntimeError(
            "Image generation needs CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN."
        )

    endpoint = (
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
        f"/ai/run/{model}"
    )
    payload = json.dumps({"prompt": prompt}).encode("utf-8")
    request = Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "Accept": "image/*, application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=180) as response:
            body = response.read()
            content_type = response.headers.get("Content-Type", "")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(
            f"Cloudflare image generation failed ({exc.code}): {detail}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            f"Could not reach Cloudflare Workers AI: {exc.reason}"
        ) from exc

    if "json" in content_type.lower() or body.lstrip().startswith(b"{"):
        try:
            result = json.loads(body)
            encoded = result["result"]["image"]
            image_bytes = base64.b64decode(encoded, validate=True)
        except (ValueError, KeyError, TypeError) as exc:
            raise RuntimeError(
                f"Model {model} returned an unexpected image response."
            ) from exc
    else:
        image_bytes = body

    if not image_bytes:
        raise RuntimeError(f"Model {model} returned an empty image.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(image_bytes)
    return destination


def generate_image(
    prompt: str,
    destination: str | Path,
    *,
    account_id: str | None = None,
    api_token: str | None = None,
    model: str | None = None,
) -> Path:
    """Generate one image, trying configured model fallbacks in order."""
    if not prompt or not prompt.strip():
        raise ValueError("Image prompt cannot be empty")
    # Explicit arguments remain supported for callers and tests.
    if account_id:
        os.environ["CLOUDFLARE_ACCOUNT_ID"] = account_id
    if api_token:
        os.environ["CLOUDFLARE_API_TOKEN"] = api_token

    target = Path(destination)
    failures: list[str] = []
    chain = _model_chain(model)
    for index, selected in enumerate(chain):
        try:
            return _request_image(prompt, target, selected)
        except RuntimeError as exc:
            message = str(exc)
            failures.append(f"{selected}: {message}")
            status = re.search(r"failed \((\d{3})\)", message)
            # Bad credentials and exhausted account quota cannot be fixed by
            # switching models; fail immediately rather than burning requests.
            if status and int(status.group(1)) in {401, 403, 429}:
                raise
            if index == len(chain) - 1:
                break
    raise RuntimeError(
        "All configured image models failed:\n" + "\n".join(failures)
    )


def _shot_prompt(story: dict, shot: dict, index: int) -> str:
    prompt = shot["image_prompt"].strip()
    bible = story.get("character_bible", {})
    character_ids = shot.get("character_ids", [])
    continuity: list[str] = []
    for character_id in character_ids:
        profile = bible.get(character_id)
        if profile is None:
            raise ValueError(
                f"Shot {index} references unknown character_id '{character_id}'"
            )
        if isinstance(profile, str):
            description = profile
        else:
            description = profile.get("visual_identity") or profile.get("description")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(
                f"Character '{character_id}' needs visual_identity or description"
            )
        continuity.append(f"{character_id}: {description.strip()}")

    parts = [prompt]
    if continuity:
        parts.append(
            "CHARACTER CONTINUITY LOCK — depict these same established characters "
            "without redesigning their face, age, hairstyle, skin tone, body build, "
            "signature clothing, or distinguishing features: "
            + " | ".join(continuity)
            + ". Change only pose, expression, camera angle, and scene action."
        )
    style_lock = story.get("style_lock")
    if isinstance(style_lock, str) and style_lock.strip():
        parts.append(f"SERIES STYLE LOCK: {style_lock.strip()}")
    return "\n\n".join(parts)


def generate_story_images(story: dict, *, overwrite: bool = False) -> list[Path]:
    """Generate missing shot images with ordered model fallback and continuity locks.

    Writes generation-report.json beside story.json, including the model used
    for each shot. Reference-image conditioning is deliberately not faked:
    FLUX.2 supports multi-reference input, but it needs a separate multipart
    request implementation and is not silently treated as text-only support.
    """
    root = Path(story.get("_project_dir", "."))
    generated: list[Path] = []
    report: list[dict[str, str]] = []
    for index, shot in enumerate(story["shots"], start=1):
        prompt = shot.get("image_prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"Shot {index} is missing a usable image_prompt")
        destination = root / shot["image"]
        if destination.exists() and not overwrite:
            generated.append(destination)
            report.append({"shot": str(index), "image": str(destination), "status": "cached"})
            continue

        full_prompt = _shot_prompt(story, shot, index)
        chain = _model_chain(shot.get("model"))
        failures: list[str] = []
        selected_model = ""
        for model_index, selected in enumerate(chain):
            try:
                _request_image(full_prompt, destination, selected)
                selected_model = selected
                break
            except RuntimeError as exc:
                failures.append(f"{selected}: {exc}")
                status = re.search(r"failed \((\d{3})\)", str(exc))
                if status and int(status.group(1)) in {401, 403, 429}:
                    raise
                if model_index == len(chain) - 1:
                    raise RuntimeError(
                        f"Shot {index}: all image models failed:\n"
                        + "\n".join(failures)
                    ) from exc
        generated.append(destination)
        report.append({
            "shot": str(index),
            "image": str(destination),
            "status": "generated",
            "model": selected_model,
        })
        print(f"Shot {index}: generated with {selected_model}")

    (root / "generation-report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return generated
