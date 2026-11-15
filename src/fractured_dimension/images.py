"""Multi-model image generation with reference-conditioned character continuity."""

from __future__ import annotations

import base64
import io
import json
import os
import re
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image

MODEL_IDS = {
    "flux-schnell": "@cf/black-forest-labs/flux-1-schnell",
    "flux-2-dev": "@cf/black-forest-labs/flux-2-dev",
    "flux-2-klein": "@cf/black-forest-labs/flux-2-klein-4b",
    "flux-2-klein-4b": "@cf/black-forest-labs/flux-2-klein-4b",
    "flux-2-klein-9b": "@cf/black-forest-labs/flux-2-klein-9b",
    "sdxl-lightning": "@cf/bytedance/stable-diffusion-xl-lightning",
    "sdxl-base": "@cf/stabilityai/stable-diffusion-xl-base-1.0",
    "dreamshaper": "@cf/lykon/dreamshaper-8-lcm",
}
DEFAULT_MODEL = MODEL_IDS["flux-schnell"]
DEFAULT_REFERENCE_MODEL = MODEL_IDS["flux-2-klein"]
DEFAULT_FALLBACKS = [
    MODEL_IDS["sdxl-lightning"],
    MODEL_IDS["sdxl-base"],
]
REFERENCE_MODELS = {
    MODEL_IDS["flux-2-dev"],
    MODEL_IDS["flux-2-klein"],
    MODEL_IDS["flux-2-klein-9b"],
}


def _resolve_model(value: str) -> str:
    value = value.strip()
    return MODEL_IDS.get(value.lower(), value)


def _model_chain(preferred: str | None = None) -> list[str]:
    primary = _resolve_model(os.getenv("CLOUDFLARE_MODEL") or DEFAULT_MODEL)
    configured = os.getenv("CLOUDFLARE_FALLBACK_MODELS")
    fallbacks = (
        [_resolve_model(item) for item in configured.split(",") if item.strip()]
        if configured is not None
        else DEFAULT_FALLBACKS
    )
    selected = _resolve_model(preferred) if preferred else primary
    chain = [selected]
    if selected != primary:
        chain.append(primary)
    chain.extend(fallbacks)
    return list(dict.fromkeys(chain))


def _reference_model_chain(preferred: str | None = None) -> list[str]:
    """Return only models that can accept character reference images."""
    selected = _resolve_model(
        preferred or os.getenv("CLOUDFLARE_REFERENCE_MODEL") or DEFAULT_REFERENCE_MODEL
    )
    ordered = [
        selected,
        MODEL_IDS["flux-2-dev"],
        MODEL_IDS["flux-2-klein-9b"],
        MODEL_IDS["flux-2-klein"],
    ]
    return list(dict.fromkeys(model for model in ordered if model in REFERENCE_MODELS))


def _multipart_payload(prompt: str, reference_images: list[Path]) -> tuple[bytes, str]:
    boundary = f"----fractured-dimension-{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    def field(name: str, value: bytes, filename: str | None = None) -> None:
        disposition = f'Content-Disposition: form-data; name="{name}"'
        if filename:
            disposition += f'; filename="{filename}"'
        chunks.append(f"--{boundary}\r\n{disposition}\r\n".encode("utf-8"))
        if filename:
            chunks.append(b"Content-Type: image/png\r\n")
        chunks.append(b"\r\n")
        chunks.append(value)
        chunks.append(b"\r\n")

    field("prompt", prompt.encode("utf-8"))
    for index, reference in enumerate(reference_images[:4]):
        if not reference.is_file():
            raise FileNotFoundError(f"Character reference image not found: {reference}")
        with Image.open(reference) as source:
            source.load()
            source.thumbnail((511, 511))
            image = source.convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
        field(f"input_image_{index}", buffer.getvalue(), f"reference-{index}.png")
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _request_image(
    prompt: str,
    destination: Path,
    model: str,
    reference_images: list[Path] | None = None,
) -> Path:
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
    references = reference_images or []
    if model in REFERENCE_MODELS:
        payload, content_type = _multipart_payload(prompt, references)
    else:
        if references:
            print(f"Note: {model} does not accept reference images; using character prompt lock.")
        payload = json.dumps({"prompt": prompt}).encode("utf-8")
        content_type = "application/json"

    request = Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": content_type,
            "Accept": "image/*, application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=240) as response:
            body = response.read()
            response_type = response.headers.get("Content-Type", "")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(
            f"Cloudflare image generation failed ({exc.code}): {detail}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            f"Could not reach Cloudflare Workers AI: {exc.reason}"
        ) from exc

    if "json" in response_type.lower() or body.lstrip().startswith(b"{"):
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
    reference_images: list[str | Path] | None = None,
) -> Path:
    """Generate one image, trying configured model fallbacks in order."""
    if not prompt or not prompt.strip():
        raise ValueError("Image prompt cannot be empty")
    if account_id:
        os.environ["CLOUDFLARE_ACCOUNT_ID"] = account_id
    if api_token:
        os.environ["CLOUDFLARE_API_TOKEN"] = api_token

    target = Path(destination)
    references = [Path(item) for item in (reference_images or [])]
    chain = _model_chain(model)
    failures: list[str] = []
    for index, selected in enumerate(chain):
        try:
            return _request_image(prompt, target, selected, references)
        except RuntimeError as exc:
            message = str(exc)
            failures.append(f"{selected}: {message}")
            status = re.search(r"failed \((\d{3})\)", message)
            if status and int(status.group(1)) in {401, 403, 429}:
                raise
            if index == len(chain) - 1:
                break
    raise RuntimeError(
        "All configured image models failed:\n" + "\n".join(failures)
    )



def _replicate_request(
    prompt: str, destination: Path, reference_images: list[Path] | None = None
) -> Path:
    """Generate with Replicate; use Kontext when a character reference is supplied."""
    token = os.getenv("REPLICATE_API_TOKEN")
    if not token:
        raise RuntimeError("Replicate fallback needs REPLICATE_API_TOKEN.")

    references = reference_images or []
    if references:
        model = "black-forest-labs/flux-kontext-pro"
        reference = references[0]
        if not reference.is_file():
            raise FileNotFoundError(f"Character reference image not found: {reference}")
        with Image.open(reference) as source:
            source.load()
            source.thumbnail((384, 384))
            buffer = io.BytesIO()
            source.convert("RGB").save(buffer, format="JPEG", quality=65, optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        image_input = f"data:image/jpeg;base64,{encoded}"
        if len(image_input) > 256 * 1024:
            raise RuntimeError(
                "Compressed character reference exceeds Replicate's data-URL limit."
            )
        inputs = {
            "prompt": prompt,
            "input_image": image_input,
            "aspect_ratio": "match_input_image",
            "output_format": "png",
            "safety_tolerance": 2,
            "prompt_upsampling": False,
        }
        if len(references) > 1:
            print("Replicate FLUX Kontext accepts one reference here; using the first character reference.")
    else:
        model = "black-forest-labs/flux-schnell"
        inputs = {
            "prompt": prompt,
            "aspect_ratio": "9:16",
            "output_format": "png",
            "num_outputs": 1,
        }

    endpoint = f"https://api.replicate.com/v1/models/{model}/predictions"
    payload = json.dumps({"input": inputs}).encode("utf-8")
    request = Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Prefer": "wait=60",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=240) as response:
            prediction = json.loads(response.read())
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1200]
        raise RuntimeError(f"Replicate image generation failed ({exc.code}): {detail}") from exc
    except (URLError, ValueError) as exc:
        raise RuntimeError(f"Could not complete Replicate image request: {exc}") from exc

    # Replicate may return a still-running prediction after the synchronous wait.
    for _ in range(60):
        status = prediction.get("status")
        if status in {"succeeded", "failed", "canceled"}:
            break
        poll_url = (prediction.get("urls") or {}).get("get")
        if not poll_url:
            raise RuntimeError("Replicate returned a pending prediction without a polling URL.")
        import time
        time.sleep(2)
        poll = Request(
            poll_url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        try:
            with urlopen(poll, timeout=120) as response:
                prediction = json.loads(response.read())
        except (HTTPError, URLError, ValueError) as exc:
            raise RuntimeError(f"Could not poll Replicate prediction: {exc}") from exc
    else:
        raise RuntimeError("Replicate prediction did not finish within the polling limit.")

    if prediction.get("status") != "succeeded":
        raise RuntimeError(
            "Replicate prediction "
            + str(prediction.get("status"))
            + ": "
            + str(prediction.get("error") or "no error detail")
        )
    output = prediction.get("output")
    output_url = output[0] if isinstance(output, list) and output else output
    if not isinstance(output_url, str) or not output_url.startswith("https://"):
        raise RuntimeError("Replicate returned no valid image URL.")
    try:
        with urlopen(Request(output_url), timeout=240) as response:
            image_bytes = response.read()
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"Could not download Replicate image output: {exc}") from exc
    if not image_bytes:
        raise RuntimeError("Replicate returned an empty image.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(image_bytes)
    return destination


def _request_image_with_fallback(
    prompt: str,
    destination: Path,
    model: str,
    reference_images: list[Path] | None = None,
) -> tuple[Path, str, str]:
    """Try Cloudflare first, then Replicate on quota/auth failures."""
    try:
        result = _request_image(prompt, destination, model, reference_images)
        return result, "cloudflare", model
    except RuntimeError as exc:
        status = re.search(r"failed \((\d{3})\)", str(exc))
        if not status or int(status.group(1)) not in {401, 403, 429}:
            raise
        if not os.getenv("REPLICATE_API_TOKEN"):
            raise RuntimeError(
                f"{exc}\nReplicate fallback is not configured. Add REPLICATE_API_TOKEN "
                "to GitHub Actions secrets to enable the independent provider."
            ) from exc
        print(f"Cloudflare returned HTTP {status.group(1)}; switching to Replicate.")
        result = _replicate_request(prompt, destination, reference_images)
        replicate_model = (
            "black-forest-labs/flux-kontext-pro"
            if reference_images else "black-forest-labs/flux-schnell"
        )
        return result, "replicate", replicate_model

def _character_profile(story: dict, character_id: str) -> dict:
    profile = story.get("character_bible", {}).get(character_id)
    if isinstance(profile, str):
        return {"visual_identity": profile}
    return profile or {}


def _character_prompt(character_id: str, profile: dict, style_lock: str = "") -> str:
    identity = profile.get("visual_identity") or profile.get("description")
    if not isinstance(identity, str) or not identity.strip():
        raise ValueError(
            f"Character '{character_id}' needs visual_identity or description"
        )
    parts = [
        "Create a clean character reference sheet for a recurring graphic-novel character. "
        "Show one consistent person in a full-body three-quarter view and a clear face "
        "portrait inset, on a simple neutral background. No labels, lettering, props "
        "that obscure the outfit, or extra people.",
        f"LOCKED CHARACTER IDENTITY: {identity.strip()}",
    ]
    if style_lock:
        parts.append(f"SERIES STYLE LOCK: {style_lock}")
    parts.append(
        "The face, hairstyle, clothing design, signature colours, body proportions "
        "and distinguishing details must be clearly visible and easy to reuse."
    )
    return "\n\n".join(parts)


def _prepare_character_references(
    story: dict, root: Path, overwrite: bool, report: list[dict[str, str]]
) -> dict[str, Path]:
    references: dict[str, Path] = {}
    bible = story.get("character_bible", {})
    reference_model = _resolve_model(
        os.getenv("CLOUDFLARE_REFERENCE_MODEL") or DEFAULT_REFERENCE_MODEL
    )
    for character_id, raw_profile in bible.items():
        profile = raw_profile if isinstance(raw_profile, dict) else {
            "visual_identity": raw_profile
        }
        reference_name = profile.get("reference_image")
        if not reference_name:
            continue
        destination = root / reference_name
        if destination.exists() and not overwrite:
            references[character_id] = destination
            report.append({
                "shot": f"character:{character_id}",
                "image": str(destination),
                "status": "reference-cached",
            })
            continue
        reference_prompt = profile.get("reference_prompt")
        if not reference_prompt:
            raise ValueError(
                f"Character '{character_id}' reference_image is missing and "
                "no reference_prompt was supplied."
            )
        prompt = _character_prompt(
            character_id, profile, story.get("style_lock", "")
        )
        prompt = f"{reference_prompt.strip()}\n\n{prompt}"
        failures: list[str] = []
        chain = _model_chain(reference_model)
        for model_index, selected in enumerate(chain):
            try:
                _, provider, actual_model = _request_image_with_fallback(
                    prompt, destination, selected
                )
                references[character_id] = destination
                report.append({
                    "shot": f"character:{character_id}",
                    "image": str(destination),
                    "status": "reference-generated",
                    "provider": provider,
                    "model": actual_model,
                })
                print(f"Character reference {character_id}: generated with {provider}/{actual_model}")
                break
            except RuntimeError as exc:
                failures.append(f"{selected}: {exc}")
                status = re.search(r"failed \((\d{3})\)", str(exc))
                if status and int(status.group(1)) in {401, 403, 429}:
                    raise
                if model_index == len(chain) - 1:
                    raise RuntimeError(
                        f"Character reference {character_id}: all models failed:\n"
                        + "\n".join(failures)
                    ) from exc
    return references


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

    parts = [
        prompt,
        "ANATOMY AND SINGLE-SUBJECT QUALITY RULES: each depicted person has exactly "
        "one head, one face, one neck, one torso, two arms and two legs where visible. "
        "The head is naturally attached to the neck and shoulders. Keep facial features "
        "correctly aligned to the same skull and viewing angle. Show one coherent head "
        "only: no duplicate head, floating head, detached face, side-face overlay, "
        "second face, extra facial features, merged bodies, extra limbs, malformed "
        "hands, or mirrored anatomy. Do not show alternate views of the same character "
        "in a single story frame. Keep the full head inside the frame unless intentionally cropped.",
    ]
    if continuity:
        parts.append(
            "CHARACTER CONTINUITY LOCK — depict these same established characters "
            "without redesigning their face, age, hairstyle, skin tone, body build, "
            "signature clothing, or distinguishing features: "
            + " | ".join(continuity)
            + ". Change only pose, expression, camera angle, and scene action. Do not reinterpret the character or add another version of them."
        )
    style_lock = story.get("style_lock")
    if isinstance(style_lock, str) and style_lock.strip():
        parts.append(f"SERIES STYLE LOCK: {style_lock.strip()}")
    return "\n\n".join(parts)


def generate_story_images(story: dict, *, overwrite: bool = False) -> list[Path]:
    """Generate character sheets and shots with model fallback and reference conditioning."""
    root = Path(story.get("_project_dir", "."))
    generated: list[Path] = []
    report: list[dict[str, str]] = []
    character_references = _prepare_character_references(
        story, root, overwrite, report
    )

    for index, shot in enumerate(story["shots"], start=1):
        prompt = shot.get("image_prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"Shot {index} is missing a usable image_prompt")
        destination = root / shot["image"]
        if destination.exists() and not overwrite:
            generated.append(destination)
            report.append({
                "shot": str(index), "image": str(destination), "status": "cached"
            })
            continue

        full_prompt = _shot_prompt(story, shot, index)
        character_ids = shot.get("character_ids", [])
        references = [
            character_references[character_id]
            for character_id in character_ids
            if character_id in character_references
        ][:4]
        preferred_model = shot.get("model")
        # Never silently drop to a text-only model for a character shot: that
        # would break visual-reference continuity across scenes.
        chain = (
            _reference_model_chain(preferred_model)
            if references
            else _model_chain(preferred_model)
        )
        failures: list[str] = []
        selected_model = ""
        for model_index, selected in enumerate(chain):
            try:
                _, selected_provider, selected_model = _request_image_with_fallback(
                    full_prompt, destination, selected, references
                )
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
            "provider": selected_provider,
            "model": selected_model,
            "reference_images_used": str(
                bool(references and selected_model in REFERENCE_MODELS)
            ).lower(),
        })
        print(f"Shot {index}: generated with {selected_model}")

    (root / "generation-report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return generated
