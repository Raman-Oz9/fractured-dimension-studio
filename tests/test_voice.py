from fractured_dimension import voice


def test_generate_voiceover_uses_kokoro_pipeline(monkeypatch, tmp_path):
    import sys
    import types
    import numpy as np

    class FakePipeline:
        def __init__(self, lang_code):
            assert lang_code == "a"

        def __call__(self, text, voice, speed, split_pattern):
            assert text == "A story begins."
            assert voice == "am_adam"
            assert speed == 0.94
            yield types.SimpleNamespace(audio=np.array([0.0, 0.1, -0.1]))

    fake_kokoro = types.ModuleType("kokoro")
    fake_kokoro.KPipeline = FakePipeline
    monkeypatch.setitem(sys.modules, "kokoro", fake_kokoro)
    monkeypatch.setenv("KOKORO_VOICE", "am_adam")
    monkeypatch.setenv("KOKORO_SPEED", "0.94")

    output = tmp_path / "voice.wav"
    result = voice.generate_voiceover("A story begins.", output)
    assert result == output
    assert output.exists()
    assert output.stat().st_size > 44


def test_generate_voiceover_rejects_empty_text(tmp_path):
    try:
        voice.generate_voiceover("  ", tmp_path / "voice.wav")
    except ValueError as exc:
        assert "cannot be empty" in str(exc)
    else:
        raise AssertionError("Expected empty narration to fail")


def test_generate_voiceover_rejects_unknown_backend(monkeypatch, tmp_path):
    monkeypatch.setenv("VOICE_BACKEND", "unknown")
    try:
        voice.generate_voiceover("A story begins.", tmp_path / "voice.wav")
    except ValueError as exc:
        assert "VOICE_BACKEND" in str(exc)
    else:
        raise AssertionError("Expected unknown backend to fail")
