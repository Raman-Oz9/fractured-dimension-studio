"""Image generation through Cloudflare Workers AI."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_MODEL = "@cf/black-forest-labs/flux-1-schnell"


def generate_image(
    prompt: str,
    destination: str | Path,
    *,
    account_id: str | None = None,
    api_token: str | None = None,
    model: str | None = None,
) -> Path:
    """Generate one image and save it to destination.

    Credentials are read from the environment unless explicitly supplied.
    Cloudflare's image response may be raw image bytes or JSON containing a
    base64-encoded result.image field.
    """
    account_id = account_id or os.getenv("CLOUDFLARE_ACCOUNT_ID")
    api_token = api_token or os.getenv("CLOUDFLARE_API_TOKEN")
    model = model or os.getenv("CLOUDFLARE_MODEL", DEFAULT_MODEL)
    if not account_id or not api_token:
        raise RuntimeError(
            "Image generation needs CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN."
        )
    if not prompt or not prompt.strip():
        raise ValueError("Image prompt cannot be empty")

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
        raise RuntimeError(f"Cloudflare image generation failed ({exc.code}): {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Cloudflare Workers AI: {exc.reason}") from exc

    if "json" in content_type.lower() or body.lstrip().startswith(b"{"):
        try:
            result = json.loads(body)
            encoded = result["result"]["image"]
            image_bytes = base64.b64decode(encoded, validate=True)
        except (ValueError, KeyError, TypeError) as exc:
            raise RuntimeError("Cloudflare returned an unexpected image response.") from exc
    else:
        image_bytes = body

    if not image_bytes:
        raise RuntimeError("Cloudflare returned an empty image.")
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(image_bytes)
    return target


def generate_story_images(story: dict, *, overwrite: bool = False) -> list[Path]:
    """Generate missing shot images for a loaded story manifest."""
    root = Path(story.get("_project_dir", "."))
    generated: list[Path] = []
    for index, shot in enumerate(story["shots"], start=1):
        prompt = shot.get("image_prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"Shot {index} is missing a usable image_prompt")
        destination = root / shot["image"]
        if destination.exists() and not overwrite:
            generated.append(destination)
            continue
        generate_image(prompt, destination)
        generated.append(destination)
    return generated
