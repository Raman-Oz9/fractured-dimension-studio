"""Multi-model image generation with reference-conditioned character continuity."""

from __future__ import annotations

import base64
import io
import json
import os
import re
import uuid
import time
import urllib.parse
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
# Story shots are generated natively at 9:16 (multiples of 16, inside FLUX.2's
# 256-1920 range) so the vertical crop never cuts characters or action out of the frame.
SHOT_WIDTH = 768
SHOT_HEIGHT = 1344
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


def _multipart_payload(
    prompt: str,
    reference_images: list[Path],
    size: tuple[int, int] | None = None,
) -> tuple[bytes, str]:
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
    if size:
        field("width", str(size[0]).encode("ascii"))
        field("height", str(size[1]).encode("ascii"))
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

    # Cloudflare Workers AI rejects prompts above 2,048 characters.
    # Preserve both the scene opening and the continuity/style ending within the limit.
    if len(prompt) > 1900:
        prompt = prompt[:1500].rstrip() + "\n\n" + prompt[-350:].lstrip()

    endpoint = (
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
        f"/ai/run/{model}"
    )
    references = reference_images or []
    if model in REFERENCE_MODELS:
        # Reference-conditioned requests are story shots: render them in portrait.
        size = (SHOT_WIDTH, SHOT_HEIGHT) if references else None
        payload, content_type = _multipart_payload(prompt, references, size)
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



def _save_image_response(response, destination: Path, provider: str) -> tuple[Path, str]:
    body = response.read()
    content_type = response.headers.get("Content-Type", "")
    if not body or (content_type and not content_type.startswith("image/")):
        raise RuntimeError(f"{provider} did not return an image.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(body)
    return destination, provider


def _pollinations_image(prompt: str, destination: Path) -> tuple[Path, str]:
    """Public FLUX image endpoint; no API key, subject to availability and rate limits."""
    url = (
        "https://image.pollinations.ai/prompt/"
        + urllib.parse.quote(prompt[:900])
        + "?width=768&height=1344&nologo=true&model=flux&seed="
        + str(uuid.uuid4().int % 1_000_000)
    )
    try:
        with urlopen(Request(url, headers={"User-Agent": "FracturedDimension/1.0"}), timeout=180) as response:
            return _save_image_response(response, destination, "pollinations-flux")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Pollinations FLUX unavailable: {exc}") from exc


def _ovh_image(prompt: str, destination: Path) -> tuple[Path, str]:
    """OVHcloud public SDXL endpoint; anonymous access is rate-limited."""
    endpoint = "https://stable-diffusion-xl.endpoints.kepler.ai.cloud.ovh.net/api/text2image"
    headers = {"Content-Type": "application/json", "Accept": "application/octet-stream"}
    token = os.getenv("OVH_AI_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = json.dumps({
        "prompt": prompt[:1400] + ", cinematic lighting, intricate details, sharp focus",
        "negative_prompt": "text, watermark, logo, blurry, deformed, distorted, extra limbs, low quality",
    }).encode("utf-8")
    try:
        with urlopen(Request(endpoint, data=payload, headers=headers, method="POST"), timeout=180) as response:
            return _save_image_response(response, destination, "ovh-stable-diffusion-xl")
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"OVH SDXL unavailable: {exc}") from exc


def _horde_image(prompt: str, destination: Path) -> tuple[Path, str]:
    """AI Horde crowdsourced generation; free, but queue times vary."""
    base = "https://aihorde.net/api/v2/"
    headers = {
        "apikey": os.getenv("HORDE_API_KEY", "").strip() or "0000000000",
        "Client-Agent": "fractured-dimension:1.0:github.com/Raman-Oz9/fractured-dimension-studio",
        "Content-Type": "application/json",
    }
    payload = json.dumps({
        "prompt": prompt[:900] + " ### text, watermark, blurry, deformed",
        "params": {"width": 576, "height": 1024, "steps": 25, "n": 1},
        "nsfw": False, "censor_nsfw": True, "r2": True,
    }).encode("utf-8")
    try:
        with urlopen(Request(base + "generate/async", data=payload, headers=headers, method="POST"), timeout=60) as response:
            job_id = json.loads(response.read())["id"]
        deadline = time.time() + 240
        while time.time() < deadline:
            time.sleep(5)
            with urlopen(Request(base + f"generate/check/{job_id}", headers=headers), timeout=30) as response:
                status = json.loads(response.read())
            if status.get("faulted"):
                raise RuntimeError("AI Horde generation job faulted.")
            if status.get("done"):
                with urlopen(Request(base + f"generate/status/{job_id}", headers=headers), timeout=30) as response:
                    result = json.loads(response.read())
                generations = result.get("generations") or []
                if not generations or generations[0].get("censored"):
                    raise RuntimeError("AI Horde returned no usable image.")
                with urlopen(Request(generations[0]["img"]), timeout=90) as response:
                    return _save_image_response(response, destination, "ai-horde")
        raise RuntimeError("AI Horde queue timed out after 4 minutes.")
    except (HTTPError, URLError, TimeoutError, KeyError, ValueError) as exc:
        raise RuntimeError(f"AI Horde unavailable: {exc}") from exc


def _free_provider_fallback(
    prompt: str, destination: Path
) -> tuple[Path, str, str]:
    failures = []
    for provider, generate in (
        ("ovh-stable-diffusion-xl", _ovh_image),
        ("ai-horde", _horde_image),
        ("pollinations-flux", _pollinations_image),
    ):
        try:
            path, actual_provider = generate(prompt, destination)
            return path, actual_provider, actual_provider
        except Exception as exc:
            failures.append(f"{provider}: {exc}")
            print(f"Free image provider {provider} failed: {exc}")
    raise RuntimeError("All public free image providers failed: " + " | ".join(failures))


def _request_image_with_fallback(
    prompt: str,
    destination: Path,
    model: str,
    reference_images: list[Path] | None = None,
) -> tuple[Path, str, str]:
    """Prefer Cloudflare first; use public free providers only as automatic backups.

    Cloudflare quota/rate-limit failures fall through to public providers. The public
    providers are text-to-image only and cannot condition on reference image files.
    """
    has_cloudflare = bool(
        os.getenv("CLOUDFLARE_ACCOUNT_ID") and os.getenv("CLOUDFLARE_API_TOKEN")
    )

    references = reference_images or []
    if references:
        if not has_cloudflare:
            raise RuntimeError(
                "Character continuity requires Cloudflare reference-image support; "
                "refusing text-only fallback that could redesign the character."
            )
        try:
            result = _request_image(prompt, destination, model, references)
            return result, "cloudflare", model
        except RuntimeError as exc:
            raise RuntimeError(
                "Reference-conditioned image generation failed; refusing an "
                f"unconditioned fallback to protect character continuity: {exc}"
            ) from exc

    if has_cloudflare:
        try:
            result = _request_image(prompt, destination, model, [])
            return result, "cloudflare", model
        except RuntimeError as exc:
            print(
                "Cloudflare image generation unavailable (possibly daily quota); "
                f"trying free backup providers: {exc}"
            )

    try:
        return _free_provider_fallback(prompt, destination)
    except RuntimeError as backup_error:
        if not has_cloudflare:
            raise RuntimeError(
                f"{backup_error}\nCloudflare credentials are not configured. "
                "Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN to enable "
                "the preferred default image provider."
            ) from backup_error
        raise RuntimeError(
            f"Cloudflare and all free backup image providers failed. "
            f"Backups: {backup_error}"
        ) from backup_error



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
    if profile.get("kind") == "location":
        parts = [
            "Create a clean environment reference plate for a recurring story location: one "
            "establishing view showing its architecture, key props, lighting and mood. No "
            "people, no lettering.",
            f"LOCKED LOCATION DESIGN: {identity.strip()}",
        ]
        if style_lock:
            parts.append(f"SERIES STYLE LOCK: {style_lock}")
        return "\n\n".join(parts)
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


PROMPT_LIMIT = 1850  # Cloudflare rejects prompts above 2,048 characters; keep headroom.

_SINGLE_SCENE_RULES = (
    "ONE finished story scene, not a character sheet, collage, split panel, inset or text. "
    "Each person has exactly one head, one face, two arms and two legs: no duplicate head, "
    "floating head, merged bodies or extra limbs. Use the reference only for identity, never its layout."
)


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    boundary = max(cut.rfind(". "), cut.rfind("; "), cut.rfind(", "))
    return (cut[: boundary + 1] if boundary > limit * 0.6 else cut).rstrip()


def _shot_prompt(story: dict, shot: dict, index: int) -> str:
    from .project import ANGLES

    scene = shot["image_prompt"].strip()
    angle = shot.get("angle")
    if angle in ANGLES:
        scene = f"{ANGLES[angle][0].upper()}{ANGLES[angle][1:]}. {scene}"
    bible = story.get("character_bible", {})
    continuity: list[str] = []
    for character_id in shot.get("character_ids", []):
        profile = bible.get(character_id)
        if profile is None:
            raise ValueError(
                f"Shot {index} references unknown character_id '{character_id}'"
            )
        if isinstance(profile, str):
            description = profile
        else:
            description = (
                profile.get("prompt_tag")
                or profile.get("visual_identity")
                or profile.get("description")
            )
        if not isinstance(description, str) or not description.strip():
            raise ValueError(
                f"Character '{character_id}' needs visual_identity or description"
            )
        continuity.append(f"{character_id}: {description.strip()}")

    tail: list[str] = []
    if continuity:
        tail.append(
            "CHARACTER CONTINUITY LOCK, same design in every panel (change only pose, expression, "
            "angle, action): " + " | ".join(continuity)
        )
    style_lock = story.get("style_lock")
    if isinstance(style_lock, str) and style_lock.strip():
        tail.append(f"SERIES STYLE LOCK: {style_lock.strip()}")
    tail.append(_SINGLE_SCENE_RULES)
    # The scene is the one part allowed to shrink: locks must survive intact.
    reserved = sum(len(part) + 2 for part in tail)
    budget = max(350, PROMPT_LIMIT - reserved)
    return "\n\n".join([_shorten(scene, budget), *tail])


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
                bool(references and selected_provider == "cloudflare" and selected_model in REFERENCE_MODELS)
            ).lower(),
        })
        print(f"Shot {index}: generated with {selected_model}")

    (root / "generation-report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return generated
