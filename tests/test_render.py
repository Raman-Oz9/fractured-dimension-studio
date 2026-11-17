from fractured_dimension.render import _zoom_filter


def test_zoom_filter_preserves_aspect_ratio_without_stretching():
    video_filter = _zoom_filter("push_in", 120)
    assert "force_original_aspect_ratio=increase" in video_filter
    assert "crop=1080:1920" in video_filter
    assert "scale=2200:-1" not in video_filter
    assert "s=1080x1920" in video_filter


def test_every_camera_preset_uses_a_continuous_eased_path():
    for move in ("push_in", "pull_out", "pan_left", "pan_right", "hold"):
        video_filter = _zoom_filter(move, 120)
        assert "zoompan=" in video_filter
        assert "s=1080x1920" in video_filter
        assert "3-2*" in video_filter
        assert "on/119" in video_filter


def test_custom_camera_path_moves_through_multiple_keyframes():
    path = [
        {"at": 0.0, "zoom": 1.0, "x": 0.5, "y": 0.5},
        {"at": 0.5, "zoom": 1.2, "x": 0.7, "y": 0.4},
        {"at": 1.0, "zoom": 1.1, "x": 0.3, "y": 0.6},
    ]
    video_filter = _zoom_filter("push_in", 61, path)
    assert "lte(min(max(on/60,0),1),0.5)" in video_filter
    assert "0.7" in video_filter
    assert "0.3" in video_filter
    assert "0.6" in video_filter


import shutil
import subprocess
import wave

import pytest

from fractured_dimension import render
from fractured_dimension.render import _fit_durations_to_narration


def test_short_narration_leaves_shot_durations_untouched():
    assert _fit_durations_to_narration([5, 5, 5], 10.0) == [5, 5, 5]


def test_long_narration_stretches_every_shot_proportionally():
    fitted = _fit_durations_to_narration([4, 6], 10.4)
    # 10.4s of speech + 0.6s tail = 11s over 10s of planned picture.
    assert sum(fitted) == pytest.approx(11.0)
    assert fitted[1] / fitted[0] == pytest.approx(1.5)


def test_absurdly_long_narration_is_rejected_instead_of_clipped():
    with pytest.raises(RuntimeError, match="Narration fit QC failed"):
        _fit_durations_to_narration([5, 5], 40.0)


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="FFmpeg is required",
)
def test_render_keeps_whole_narration_when_it_outlasts_the_planned_shots(tmp_path, monkeypatch):
    from PIL import Image

    for name, colour in (("a.png", (120, 40, 40)), ("b.png", (40, 60, 120))):
        Image.new("RGB", (540, 960), colour).save(tmp_path / name)

    def fake_voice(text, destination):
        with wave.open(str(destination), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(24000)
            audio.writeframes(b"\x00\x00" * int(24000 * 1.8))
        return destination

    monkeypatch.setattr(render, "generate_voiceover", fake_voice)
    story = {
        "_project_dir": str(tmp_path),
        "narration": "Two shots, one longer sentence than the picture allows.",
        "shots": [
            {"image": "a.png", "duration": 1, "camera": "push_in"},
            {"image": "b.png", "duration": 1, "camera": "hold"},
        ],
    }
    out = tmp_path / "out" / "short.mp4"
    render.render_story(story, out)

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(out)],
        check=True, capture_output=True, text=True,
    )
    # 1.8s speech + 0.6s tail = 2.4s, not the originally planned 2.0s.
    assert float(probe.stdout) >= 2.3
    assert not [p for p in out.parent.iterdir() if p.name.startswith(".")]
