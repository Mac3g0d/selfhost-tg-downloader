# flake8: noqa: WPS100
from urllib.parse import urlparse, urlunparse


def clean_url(url: str) -> str:
    """Strip query, fragments, and trailing slash for TikTok and Instagram."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))
