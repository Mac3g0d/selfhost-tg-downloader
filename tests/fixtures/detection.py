"""Fixtures for the link-detection tests: texts together with the links expected in them."""

from typing import NamedTuple

import pytest
from faker import Faker

from tests.constants import (
    EMPTY_TEXT,
    FOREIGN_HOSTS,
    SCHEME_HTTP,
    SCHEME_HTTPS,
    SCHEME_SEPARATOR,
    SUPPORTED_HOSTS,
    TRACKING_SEPARATOR,
)


class LinkText(NamedTuple):
    """A message text and the cleaned links the bot has to find in it."""

    text: str
    expected: list[str]


@pytest.fixture(params=SUPPORTED_HOSTS)
def supported_host(request: pytest.FixtureRequest) -> str:
    """Every host the bot supports, one test run per host."""
    return str(request.param)


@pytest.fixture
def host_link(supported_host: str, faker: Faker) -> LinkText:
    """A link on `supported_host` with a trailing slash; the slash is not expected back."""
    path = f"{faker.pystr()}/{faker.pystr()}"
    link = f"{SCHEME_HTTPS}{SCHEME_SEPARATOR}{supported_host}/{path}"
    return LinkText(text=f"{link}/", expected=[link])


@pytest.fixture
def surrounded_link(supported_url: str, faker: Faker) -> LinkText:
    """A link with a trailing slash between two sentences."""
    return LinkText(
        text=f"{faker.sentence()} {supported_url}/ {faker.sentence()}", expected=[supported_url]
    )


@pytest.fixture
def padded_link(supported_url: str, faker: Faker) -> LinkText:
    """A link with random runs of spaces around it."""
    padding = " " * faker.pyint(min_value=1, max_value=5)
    return LinkText(text=f"{padding}{supported_url}{padding}", expected=[supported_url])


@pytest.fixture
def two_links(tiktok_url: str, instagram_url: str, faker: Faker) -> LinkText:
    """Two links with trailing slashes in one sentence, in this order."""
    first = f"{faker.word()} {instagram_url}/"
    second = f"{faker.word()} {tiktok_url}/ {faker.word()}"
    return LinkText(text=f"{first} {second}", expected=[instagram_url, tiktok_url])


@pytest.fixture
def spaced_links(tiktok_url: str, instagram_url: str, faker: Faker) -> LinkText:
    """Two links separated by a run of two or more spaces and nothing else."""
    gap = " " * faker.pyint(min_value=2, max_value=6)
    return LinkText(
        text=f"{instagram_url}{gap}{tiktok_url}/", expected=[instagram_url, tiktok_url]
    )


@pytest.fixture
def tracked_link(supported_url: str, faker: Faker) -> LinkText:
    """A link carrying a query string that must be stripped."""
    query = f"{faker.pystr()}={faker.pystr()}"
    return LinkText(text=f"{supported_url}{TRACKING_SEPARATOR}{query}", expected=[supported_url])


@pytest.fixture
def insecure_link(supported_url: str) -> LinkText:
    """The same link over plain http; the scheme is kept."""
    insecure = supported_url.replace(SCHEME_HTTPS, SCHEME_HTTP, 1)
    return LinkText(text=insecure, expected=[insecure])


@pytest.fixture
def shouting_link(supported_url: str) -> LinkText:
    """The whole link in upper case: the scheme is lowered, host and path keep their case."""
    shouted = supported_url.upper()
    expected = shouted.replace(SCHEME_HTTPS.upper(), SCHEME_HTTPS, 1)
    return LinkText(text=shouted, expected=[expected])


@pytest.fixture
def plain_text(faker: Faker) -> str:
    """A sentence without any link."""
    return str(faker.sentence())


@pytest.fixture
def empty_text() -> str:
    """The empty message text."""
    return EMPTY_TEXT


@pytest.fixture(params=FOREIGN_HOSTS)
def foreign_link(request: pytest.FixtureRequest, faker: Faker) -> str:
    """A link on a host the bot does not support, one test run per host."""
    return f"{SCHEME_HTTPS}{SCHEME_SEPARATOR}{request.param}/{faker.pystr()}"


@pytest.fixture
def bare_host_link(supported_host: str) -> str:
    """A supported host without any path."""
    return f"{SCHEME_HTTPS}{SCHEME_SEPARATOR}{supported_host}"
