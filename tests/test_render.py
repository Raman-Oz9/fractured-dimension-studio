from fractured_dimension.render import _zoom_filter


def test_zoom_filter_preserves_aspect_ratio_without_stretching():
    video_filter = _zoom_filter("push_in", 120)
    assert "force_original_aspect_ratio=increase" in video_filter
    assert "crop=1080:1920" in video_filter
    assert "scale=2200:-1" not in video_filter
    assert "s=1080x1920" in video_filter


def test_zoom_filter_keeps_camera_moves_and_vertical_output():
    for move in ("push_in", "pull_out", "pan_left", "pan_right", "hold"):
        video_filter = _zoom_filter(move, 120)
        assert "zoompan=" in video_filter
        assert "s=1080x1920" in video_filter
