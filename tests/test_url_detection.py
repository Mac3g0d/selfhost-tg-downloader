import pytest

from handlers.media import _extract_urls


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://www.tiktok.com/@user/video/12345", ["https://www.tiktok.com/@user/video/12345"]),
        ("https://vm.tiktok.com/ZMF8abc/", ["https://vm.tiktok.com/ZMF8abc/"]),
        ("https://vt.tiktok.com/ZS2abc/", ["https://vt.tiktok.com/ZS2abc/"]),
        ("https://www.instagram.com/reel/ABC123/", ["https://www.instagram.com/reel/ABC123/"]),
        ("https://instagram.com/p/XYZ789/", ["https://instagram.com/p/XYZ789/"]),
        ("https://instagr.am/p/ABC123/", ["https://instagr.am/p/ABC123/"]),
        (
            "Смотри видео https://vm.tiktok.com/abc/ огонь 🔥",
            ["https://vm.tiktok.com/abc/"],
        ),
        (
            "https://tiktok.com/@a/video/1 and https://instagram.com/reel/X/",
            ["https://tiktok.com/@a/video/1", "https://instagram.com/reel/X/"],
        ),
        ("Just a normal message", []),
        ("https://youtube.com/watch?v=abc", []),
        ("", []),
        ("http://www.tiktok.com/@user/video/1", ["http://www.tiktok.com/@user/video/1"]),
        ("HTTPS://WWW.TIKTOK.COM/@a/video/1", ["HTTPS://WWW.TIKTOK.COM/@a/video/1"]),
        ("https://twitter.com/post/123", []),
        ("https://tiktok.com", []),
        ("check https://instagram.com/reel/A/ and https://instagram.com/reel/B/ out", [
            "https://instagram.com/reel/A/",
            "https://instagram.com/reel/B/",
        ]),
    ],
)
def test_extract_urls(text: str, expected: list[str]) -> None:
    assert _extract_urls(text) == expected
