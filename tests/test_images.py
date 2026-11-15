import base64
import io
import json

import pytest

from fractured_dimension.images import generate_image


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
