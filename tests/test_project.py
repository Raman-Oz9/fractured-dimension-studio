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


def test_valid_custom_camera_path_passes():
    validate_story({
        "title": "Camera path",
        "shots": [{
            "image": "a.png", "duration": 2, "camera": "push_in",
            "camera_path": [
                {"at": 0, "zoom": 1, "x": 0.5, "y": 0.5},
                {"at": 0.5, "zoom": 1.2, "x": 0.6, "y": 0.4},
                {"at": 1, "zoom": 1.1, "x": 0.5, "y": 0.5},
            ],
        }],
    })


def test_camera_path_must_cover_whole_shot():
    with pytest.raises(ValueError, match="start at 0 and end at 1"):
        validate_story({
            "title": "Bad path",
            "shots": [{
                "image": "a.png", "duration": 2, "camera": "push_in",
                "camera_path": [
                    {"at": 0.1, "zoom": 1, "x": 0.5, "y": 0.5},
                    {"at": 1, "zoom": 1.1, "x": 0.5, "y": 0.5},
                ],
            }],
        })
