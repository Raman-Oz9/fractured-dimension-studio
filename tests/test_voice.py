from pathlib import Path

import pytest

from fractured_dimension import voice


def test_generate_voiceover_requires_configured_model(monkeypatch, tmp_path):
    monkeypatch.delenv("PIPER_MODEL_PATH", raising=False)
    with pytest.raises(RuntimeError, match="PIPER_MODEL_PATH"):
        voice.generate_voiceover("A story begins.", tmp_path / "voice.wav")


def test_generate_voiceover_invokes_piper(monkeypatch, tmp_path):
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"model")
    output = tmp_path / "voice.wav"
    calls = {}

    monkeypatch.setenv("PIPER_MODEL_PATH", str(model))
    monkeypatch.setattr(voice.shutil, "which", lambda name: "/usr/bin/piper")

    def fake_run(command, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs
        output.write_bytes(b"wav")

    monkeypatch.setattr(voice.subprocess, "run", fake_run)
    result = voice.generate_voiceover("A story begins.", output)

    assert result == output
    assert calls["command"] == [
        "/usr/bin/piper", "--model", str(model), "--output_file", str(output)
    ]
    assert calls["kwargs"]["input"] == "A story begins."
    assert calls["kwargs"]["check"] is True


def test_generate_voiceover_rejects_missing_model_file(monkeypatch, tmp_path):
    monkeypatch.setenv("PIPER_MODEL_PATH", str(tmp_path / "missing.onnx"))
    with pytest.raises(FileNotFoundError, match="Piper voice model not found"):
        voice.generate_voiceover("A story begins.", tmp_path / "voice.wav")
