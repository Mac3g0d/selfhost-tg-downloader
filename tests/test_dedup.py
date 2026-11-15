def test_extract_urls_with_spaces() -> None:
    from src.handlers.media import _extract_urls

    # Leading and trailing whitespace is stripped
    assert _extract_urls("  https://www.tiktok.com/@user/video/123  ") == [
        "https://www.tiktok.com/@user/video/123"
    ]

    # Multiple links separated by whitespace
    assert _extract_urls("https://www.instagram.com/reel/456   https://vm.tiktok.com/abc/") == [
        "https://www.instagram.com/reel/456",
        "https://vm.tiktok.com/abc",
    ]
