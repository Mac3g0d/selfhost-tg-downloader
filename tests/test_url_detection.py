from handlers.media import _extract_urls
from tests.fixtures.detection import LinkText


async def test_link_on_every_supported_host_is_cleaned(host_link: LinkText) -> None:
    extracted = _extract_urls(host_link.text)

    assert extracted == host_link.expected


async def test_link_inside_a_sentence_is_found(surrounded_link: LinkText) -> None:
    extracted = _extract_urls(surrounded_link.text)

    assert extracted == surrounded_link.expected


async def test_two_links_in_one_text_are_found_in_order(two_links: LinkText) -> None:
    extracted = _extract_urls(two_links.text)

    assert extracted == two_links.expected


async def test_query_string_is_stripped(tracked_link: LinkText) -> None:
    extracted = _extract_urls(tracked_link.text)

    assert extracted == tracked_link.expected


async def test_plain_http_scheme_is_kept(insecure_link: LinkText) -> None:
    extracted = _extract_urls(insecure_link.text)

    assert extracted == insecure_link.expected


async def test_scheme_is_lowered_and_host_case_is_kept(shouting_link: LinkText) -> None:
    extracted = _extract_urls(shouting_link.text)

    assert extracted == shouting_link.expected


async def test_text_without_links_yields_nothing(plain_text: str) -> None:
    extracted = _extract_urls(plain_text)

    assert extracted == []


async def test_empty_text_yields_nothing(empty_text: str) -> None:
    extracted = _extract_urls(empty_text)

    assert extracted == []


async def test_unsupported_host_is_ignored(foreign_link: str) -> None:
    extracted = _extract_urls(foreign_link)

    assert extracted == []


async def test_supported_host_without_a_path_is_ignored(bare_host_link: str) -> None:
    extracted = _extract_urls(bare_host_link)

    assert extracted == []
