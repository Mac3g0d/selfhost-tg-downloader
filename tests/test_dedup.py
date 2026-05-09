
def test_extract_urls_with_spaces():
    from handlers.media import _extract_urls
    
    # Ссылки с пробелами в начале/конце должны быть обрезаны
    assert _extract_urls("  https://www.tiktok.com/@user/video/123  ") == ["https://www.tiktok.com/@user/video/123"]
    
    # Несколько ссылок с пробелами между ними
    assert _extract_urls("https://www.instagram.com/reel/456   https://vm.tiktok.com/abc/") == [
        "https://www.instagram.com/reel/456",
        "https://vm.tiktok.com/abc/",
    ]
