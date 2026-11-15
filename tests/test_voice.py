import json
from urllib.request import Request

from fractured_dimension import voice


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.body


def test_generate_voiceover_resolves_named_voice_and_requests_wav(monkeypatch, tmp_path):
    calls = []

    def fake_urlopen(request, timeout):
        assert isinstance(request, Request)
        calls.append(request)
        if request.full_url.endswith("/audio/voices"):
            return FakeResponse(json.dumps({
                "voices": [
                    {"name": "George", "voice_id": "profile-george", "type": "profile"}
                ]
            }).encode())
        return FakeResponse(b"RIFF-test-wav")

    monkeypatch.setenv("VOICESTUDIO_BASE_URL", "https://voice.example/v1/")
    monkeypatch.setenv("VOICESTUDIO_API_KEY", "test-key")
    monkeypatch.setenv("VOICESTUDIO_VOICE", "George")
    monkeypatch.setenv("VOICESTUDIO_SPEED", "0.92")
    monkeypatch.setattr(voice, "urlopen", fake_urlopen)

    output = tmp_path / "voice.wav"
    result = voice.generate_voiceover("A story begins.", output)

    assert result == output
    assert output.read_bytes() == b"RIFF-test-wav"
    assert calls[0].full_url == "https://voice.example/v1/audio/voices"
    assert calls[1].full_url == "https://voice.example/v1/audio/speech"
    payload = json.loads(calls[1].data.decode())
    assert payload["voice"] == "profile-george"
    assert payload["response_format"] == "wav"
    assert payload["input"] == "A story begins."
    assert payload["speed"] == 0.92
    assert calls[1].get_header("Authorization") == "Bearer test-key"


def test_generate_voiceover_requires_api_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv("VOICESTUDIO_BASE_URL", raising=False)
    monkeypatch.delenv("VOICESTUDIO_API_KEY", raising=False)
    try:
        voice.generate_voiceover("A story begins.", tmp_path / "voice.wav")
    except RuntimeError as exc:
        assert "VOICESTUDIO_BASE_URL" in str(exc)
    else:
        raise AssertionError("Expected missing VoiceStudio credentials to fail")


def test_generate_voiceover_rejects_invalid_speed(monkeypatch, tmp_path):
    monkeypatch.setenv("VOICESTUDIO_BASE_URL", "https://voice.example/v1")
    monkeypatch.setenv("VOICESTUDIO_API_KEY", "test-key")
    monkeypatch.setenv("VOICESTUDIO_SPEED", "9")
    try:
        voice.generate_voiceover("A story begins.", tmp_path / "voice.wav")
    except ValueError as exc:
        assert "between 0.25 and 4.0" in str(exc)
    else:
        raise AssertionError("Expected invalid speed to fail")
