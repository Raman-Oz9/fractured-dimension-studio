import base64
import json

import pytest

from fractured_dimension.images import generate_image, generate_story_images


class FakeResponse:
    def __init__(self, body, content_type="image/png"):
        self.body = body
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


def test_generate_image_saves_binary_response(tmp_path, monkeypatch):
    import fractured_dimension.images as images

    def fake_urlopen(request, timeout):
        assert request.get_header("Authorization") == "Bearer token"
        assert timeout == 180
        return FakeResponse(b"fake-image-bytes")

    monkeypatch.setattr(images, "urlopen", fake_urlopen)
    target = generate_image(
        "A cinematic fractured city",
        tmp_path / "nested" / "shot.png",
        account_id="account",
        api_token="token",
    )
    assert target.read_bytes() == b"fake-image-bytes"


def test_generate_image_decodes_json_base64(tmp_path, monkeypatch):
    import fractured_dimension.images as images

    encoded = base64.b64encode(b"png-data").decode("ascii")
    payload = json.dumps({"result": {"image": encoded}}).encode()
    monkeypatch.setattr(
        images, "urlopen", lambda request, timeout: FakeResponse(payload, "application/json")
    )
    target = generate_image(
        "A cinematic portrait", tmp_path / "shot.png",
        account_id="account", api_token="token"
    )
    assert target.read_bytes() == b"png-data"


def test_missing_credentials_are_reported(tmp_path, monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="CLOUDFLARE_ACCOUNT_ID"):
        generate_image("A prompt", tmp_path / "shot.png")


def test_generate_image_falls_back_to_second_model(tmp_path, monkeypatch):
    import fractured_dimension.images as images

    calls = []

    def fake_request(prompt, destination, model):
        calls.append(model)
        if len(calls) == 1:
            raise RuntimeError("Cloudflare image generation failed (404): model unavailable")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"fallback-image")
        return destination

    monkeypatch.setattr(images, "_request_image", fake_request)
    target = generate_image(
        "A cinematic scene", tmp_path / "shot.png",
        account_id="account", api_token="token", model="flux-schnell"
    )
    assert target.read_bytes() == b"fallback-image"
    assert calls == [
        "@cf/black-forest-labs/flux-1-schnell",
        "@cf/bytedance/stable-diffusion-xl-lightning",
    ]


def test_story_generation_injects_character_and_style_locks(tmp_path, monkeypatch):
    import fractured_dimension.images as images

    captured = []

    def fake_request(prompt, destination, model):
        captured.append((prompt, model))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"image")
        return destination

    monkeypatch.setattr(images, "_request_image", fake_request)
    story = {
        "_project_dir": str(tmp_path),
        "style_lock": "bold ink graphic novel",
        "character_bible": {
            "MARA": {"visual_identity": "short black bob, olive jacket, amber stripe"}
        },
        "shots": [{
            "image": "images/shot.png",
            "image_prompt": "Mara reaches toward a hologram",
            "character_ids": ["MARA"],
        }],
    }
    result = generate_story_images(story)
    assert result[0].read_bytes() == b"image"
    assert "short black bob, olive jacket, amber stripe" in captured[0][0]
    assert "bold ink graphic novel" in captured[0][0]
    report = json.loads((tmp_path / "generation-report.json").read_text())
    assert report[0]["model"] == captured[0][1]


def test_story_generation_rejects_unknown_character(tmp_path):
    story = {
        "_project_dir": str(tmp_path),
        "character_bible": {},
        "shots": [{
            "image": "shot.png",
            "image_prompt": "A scene",
            "character_ids": ["UNKNOWN"],
        }],
    }
    with pytest.raises(ValueError, match="unknown character_id"):
        generate_story_images(story)


def test_flux2_request_sends_multipart_reference_image(tmp_path, monkeypatch):
    import fractured_dimension.images as images
    from PIL import Image

    reference = tmp_path / "character.png"
    Image.new("RGB", (900, 700), "white").save(reference)
    captured = {}

    def fake_urlopen(request, timeout):
        captured["content_type"] = request.get_header("Content-type")
        captured["body"] = request.data
        return FakeResponse(b"generated-image")

    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token")
    monkeypatch.setattr(images, "urlopen", fake_urlopen)
    destination = tmp_path / "out.png"
    images._request_image(
        "Mara in a city", destination, images.MODEL_IDS["flux-2-klein"], [reference]
    )

    assert "multipart/form-data; boundary=" in captured["content_type"]
    assert b'name="prompt"' in captured["body"]
    assert b'name="input_image_0"' in captured["body"]
    assert b"reference-0.png" in captured["body"]
    assert destination.read_bytes() == b"generated-image"


def test_story_generation_creates_character_sheet_and_reuses_it(tmp_path, monkeypatch):
    import fractured_dimension.images as images

    calls = []

    def fake_request(prompt, destination, model, reference_images=None):
        refs = list(reference_images or [])
        calls.append((prompt, destination, model, refs))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"image")
        return destination

    monkeypatch.setattr(images, "_request_image", fake_request)
    story = {
        "_project_dir": str(tmp_path),
        "style_lock": "fractured graphic novel",
        "character_bible": {
            "MARA": {
                "visual_identity": "short black bob, olive jacket",
                "reference_image": "images/mara-sheet.png",
                "reference_prompt": "Character turnaround sheet",
            }
        },
        "shots": [{
            "image": "images/shot-01.png",
            "image_prompt": "Mara reaches toward a hologram",
            "character_ids": ["MARA"],
        }],
    }
    generate_story_images(story)
    assert len(calls) == 2
    assert calls[0][2] == images.DEFAULT_REFERENCE_MODEL
    assert calls[1][2] == images.DEFAULT_REFERENCE_MODEL
    assert calls[1][3] == [tmp_path / "images/mara-sheet.png"]
    report = json.loads((tmp_path / "generation-report.json").read_text())
    assert report[0]["status"] == "reference-generated"
    assert report[1]["reference_images_used"] == "true"
