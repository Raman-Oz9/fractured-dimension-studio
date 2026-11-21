import shutil
import subprocess

import pytest
from PIL import Image

from fractured_dimension import audio, manga
from fractured_dimension.project import lint_sync, validate_story


def _shot(**extra):
    base = {"image": "a.png", "duration": 2, "camera": "snap_in", "narration": "Boro bows."}
    base.update(extra)
    return base


def test_manga_story_requires_narration_on_every_shot():
    with pytest.raises(ValueError, match="narration line"):
        validate_story({"title": "T", "render_style": "manga", "shots": [_shot(narration="")]})


def test_manga_fx_and_transitions_are_validated():
    validate_story({"title": "T", "render_style": "manga",
                    "shots": [_shot(fx=["speed_lines", "impact"], transition="whip", angle="low")]})
    with pytest.raises(ValueError, match="fx"):
        validate_story({"title": "T", "render_style": "manga", "shots": [_shot(fx=["lens_flare"])]})


def test_every_manga_camera_move_is_valid_and_matches_validator():
    for move in manga.CAMERA_MOVES:
        validate_story({"title": "T", "shots": [{"image": "a.png", "duration": 2, "camera": move}]})


def test_camera_sampling_hits_keyframes_and_supports_roll():
    shot = {"camera": "crash_in"}
    z0, _, _, r0 = manga.sample_camera(shot, 0.0)
    z1, _, _, r1 = manga.sample_camera(shot, 1.0)
    assert z0 == pytest.approx(1.0) and r0 == 0
    assert z1 > 1.6 and r1 < -3


def test_timeline_cuts_each_shot_to_its_own_line():
    story = {"shots": [{"narration": "a", "lead": 0.3, "pause": 0.4}, {"narration": "b", "lead": 0.3, "pause": 0.4}]}
    timeline = manga.plan_timeline(story, [2.0, 1.0])
    assert timeline[0]["duration"] == pytest.approx(2.7)
    assert timeline[1]["start"] == pytest.approx(2.7)
    assert timeline[1]["speech_start"] == pytest.approx(3.0)


def test_caption_chunks_stay_short():
    chunks = manga._caption_chunks("At two thirteen in the morning, the shadow stepped away.")
    assert all(len(c) <= 5 for c in chunks)
    assert sum(len(c) for c in chunks) == 10


def test_lint_flags_narration_missing_from_picture():
    story = {"shots": [{"narration": "Boro picks up the broom.", "image_prompt": "A man stands in a market."}]}
    assert lint_sync(story)
    story["shots"][0]["image_prompt"] = "Boro lifts a wooden broom."
    assert not lint_sync(story)


def test_soundtrack_mix_is_bounded_and_ducks_music():
    import numpy as np

    voice = np.sin(np.linspace(0, 400, audio.RATE * 2)).astype("float32") * 0.3
    mix = audio.mix_soundtrack(3.0, [(0.5, voice)], [(0.0, "impact", 1.0), (1.0, "coin", 1.0)])
    assert mix.size >= 3 * audio.RATE
    assert np.max(np.abs(mix)) <= 0.98


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="FFmpeg required")
def test_manga_render_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICE_BACKEND", "test-tone")
    for name in ("a.png", "b.png"):
        Image.new("RGB", (270, 480), (120, 120, 120)).save(tmp_path / name)
    story = {
        "_project_dir": str(tmp_path), "render_style": "manga", "manga": {"music": True},
        "shots": [
            _shot(image="a.png", narration="One two three.", fx=["speed_lines"], sfx_text={"text": "boom"}),
            _shot(image="b.png", camera="whip_left", narration="Four five.", transition="whip"),
        ],
    }
    from fractured_dimension.render import render_story

    out = render_story(story, tmp_path / "out.mp4")
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(out)],
                           check=True, capture_output=True, text=True)
    assert float(probe.stdout) > 3.0


def test_every_mood_bed_is_levelled_under_narration():
    import numpy as np

    for mood in audio.MOODS:
        bed = audio.music_bed(6.0, mood)
        freqs = np.fft.rfftfreq(bed.size, 1 / audio.RATE)
        audible = np.fft.irfft(np.fft.rfft(bed) * (freqs > 150), bed.size)
        assert 0.035 < float(np.sqrt(np.mean(audible ** 2))) < 0.07, mood
        assert float(np.sqrt(np.mean(bed ** 2))) < 0.11, mood  # no bass hogging the loudness headroom


def test_mood_detection_reads_the_script():
    assert audio.detect_mood("A cursed ghost haunts the grave in a terrifying nightmare.") == "horror"
    assert audio.detect_mood("Nothing special here.") == "mystery"


def test_narration_flows_without_long_gaps():
    story = {"shots": [{"narration": "One, two"}, {"narration": "three."}, {"narration": "Four."}]}
    timeline = manga.plan_timeline(story, [1.0, 1.0, 1.0])
    gaps = [timeline[i]["duration"] - 1.0 for i in (1,)]
    assert gaps[0] <= 0.35


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg required")
def test_deepen_voice_keeps_length_and_lowers_pitch(tmp_path):
    import numpy as np

    from fractured_dimension.voice import _write_wav, deepen_voice

    t = np.arange(24000) / 24000
    path = _write_wav(tmp_path / "v.wav", 0.4 * np.sin(2 * np.pi * 200 * t))
    deepen_voice(path, 3.0)
    data = audio.read_wav(path)
    assert abs(data.size - 24000) < 600
    spectrum = np.abs(np.fft.rfft(data))
    assert np.argmax(spectrum) * 24000 / data.size < 190
