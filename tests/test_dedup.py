from handlers.media import _extract_urls
from tests.fixtures.detection import LinkText


async def test_extract_urls_ignores_surrounding_spaces(padded_link: LinkText) -> None:
    extracted = _extract_urls(padded_link.text)

    assert extracted == padded_link.expected


async def test_extract_urls_splits_links_separated_by_spaces(spaced_links: LinkText) -> None:
    extracted = _extract_urls(spaced_links.text)

    assert extracted == spaced_links.expected
