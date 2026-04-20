from urllib.parse import urlparse, urlunparse


def clean_url(url: str) -> str:
    parsed = urlparse(url)
    # Strip query and fragments for TikTok and Instagram
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
