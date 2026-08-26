from api.main import _detect_background_type


def test_background_type_uses_file_signature():
    assert _detect_background_type(b"\x89PNG\r\n\x1a\nrest") == "png"
    assert _detect_background_type(b"not an image") is None
