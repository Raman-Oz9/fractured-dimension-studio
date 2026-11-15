import pytest

from fractured_dimension.project import validate_story


def test_valid_story_passes():
    validate_story({
        "title": "Test",
        "shots": [{"image": "a.png", "duration": 2, "camera": "push_in"}],
    })


def test_empty_shots_rejected():
    with pytest.raises(ValueError, match="at least one shot"):
        validate_story({"title": "Test", "shots": []})


def test_unknown_camera_move_rejected():
    with pytest.raises(ValueError, match="unsupported camera"):
        validate_story({
            "title": "Test",
            "shots": [{"image": "a.png", "duration": 2, "camera": "random"}],
        })
