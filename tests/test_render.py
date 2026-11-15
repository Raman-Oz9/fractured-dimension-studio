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
