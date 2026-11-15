# flake8: noqa: WPS100 -- module name is imported project-wide as `utils`
from urllib.parse import urlparse, urlunparse


def clean_url(url: str) -> str:
    parsed = urlparse(url)
    # Strip query, fragments, and trailing slash for TikTok and Instagram
    path = parsed.path.rstrip("/")
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))
