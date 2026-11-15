"""Fixtures for the gallery-dl settings, job and download tests."""

import asyncio
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from shutil import rmtree
from typing import NamedTuple
from unittest.mock import MagicMock

import pytest
from faker import Faker
from pytest_mock import MockerFixture

from config import settings
from constants import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from downloader.gallery import DownloadResult, download_media
from downloader.gdl_job import Job, apply_settings
from tests.constants import (
    GALLERY_CLEANUP_WAIT_SECONDS,
    GALLERY_FAILURE_STATUS_MAX,
    GALLERY_JOB_TIMEOUT_SECONDS,
    GALLERY_JOB_WAIT_SECONDS,
    GALLERY_RMTREE_TARGET,
    GALLERY_RUN_JOB_TARGET,
)

JobOutcome = tuple[int, str, None]


class Credentials(NamedTuple):
    """An Instagram login pair."""

    username: str
    password: str


class ParentJob(NamedTuple):
    """A parent job with the destination and cancel flag it was built from."""

    job: Job
    dest: Path
    cancel: threading.Event


class JobPair(NamedTuple):
    """Two jobs for one URL with different destinations."""

    first: Job
    second: Job
    first_dest: Path
    second_dest: Path


class PartialDownload(NamedTuple):
    """A job that wrote one file and then failed on another."""

    written_name: str
    failed_name: str


class StuckJob:
    """A fake job that waits for the cancel flag, then writes a late file and stops."""

    def __init__(self, late_name: str) -> None:
        self.late_name = late_name
        self.stopped = threading.Event()

    def __call__(self, url: str, work_dir: Path, cancel: threading.Event) -> JobOutcome:
        assert cancel.wait(timeout=GALLERY_JOB_WAIT_SECONDS)
        (work_dir / self.late_name).write_bytes(b"late")
        self.stopped.set()
        return 1, "", None


@pytest.fixture
def cookies_path(download_dir: Path, faker: Faker) -> Path:
    """An existing cookies file."""
    path = download_dir / faker.pystr()
    path.write_text(faker.sentence())
    return path


@pytest.fixture
def cookies_configured(cookies_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The existing cookies file set as `COOKIES_FILE`."""
    monkeypatch.setattr(settings, "COOKIES_FILE", str(cookies_path))
    return cookies_path


@pytest.fixture
def missing_cookies_configured(
    download_dir: Path, faker: Faker, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """A path that does not exist set as `COOKIES_FILE`."""
    path = download_dir / faker.pystr()
    monkeypatch.setattr(settings, "COOKIES_FILE", str(path))
    return path


@pytest.fixture
def credentials(faker: Faker) -> Credentials:
    """A generated login pair."""
    return Credentials(username=faker.pystr(), password=faker.pystr())


@pytest.fixture
def credentials_configured(
    credentials: Credentials, monkeypatch: pytest.MonkeyPatch
) -> Credentials:
    """The login pair set as `INSTAGRAM_USER` and `INSTAGRAM_PASS`."""
    monkeypatch.setattr(settings, "INSTAGRAM_USER", credentials.username)
    monkeypatch.setattr(settings, "INSTAGRAM_PASS", credentials.password)
    return credentials


@pytest.fixture
def partial_credentials_configured(
    credentials: Credentials, monkeypatch: pytest.MonkeyPatch
) -> Credentials:
    """A user name with an empty password in the settings."""
    monkeypatch.setattr(settings, "INSTAGRAM_USER", credentials.username)
    monkeypatch.setattr(settings, "INSTAGRAM_PASS", "")
    return credentials


@pytest.fixture
def credentials_unset_again(
    credentials_configured: Credentials, monkeypatch: pytest.MonkeyPatch
) -> Credentials:
    """Credentials applied to gallery-dl, then the user name cleared in the settings."""
    apply_settings()
    monkeypatch.setattr(settings, "INSTAGRAM_USER", "")
    return credentials_configured


@pytest.fixture
def cancel_event() -> threading.Event:
    """A cancel flag that is not set."""
    return threading.Event()


@pytest.fixture
def set_cancel_event(cancel_event: threading.Event) -> threading.Event:
    """A cancel flag that is already set."""
    cancel_event.set()
    return cancel_event


@pytest.fixture
def job_pair(gallery_dl_url: str, download_dir: Path, faker: Faker) -> JobPair:
    """Two jobs for one URL, each with its own destination."""
    first_dest = download_dir / faker.pystr()
    second_dest = download_dir / faker.pystr()
    return JobPair(
        first=Job(gallery_dl_url, dest=first_dest),
        second=Job(gallery_dl_url, dest=second_dest),
        first_dest=first_dest,
        second_dest=second_dest,
    )


@pytest.fixture
def parent_job(
    gallery_dl_url: str, download_dir: Path, cancel_event: threading.Event
) -> ParentJob:
    """A parent job with its destination and cancel flag."""
    return ParentJob(
        job=Job(gallery_dl_url, dest=download_dir, cancel=cancel_event),
        dest=download_dir,
        cancel=cancel_event,
    )


@pytest.fixture
def media_name(faker: Faker) -> str:
    """A generated video file name."""
    return faker.pystr() + faker.random_element(sorted(VIDEO_EXTENSIONS))


@pytest.fixture
def photo_name(faker: Faker) -> str:
    """A generated image file name."""
    return faker.pystr() + faker.random_element(sorted(IMAGE_EXTENSIONS))


@pytest.fixture
def job_error(faker: Faker) -> str:
    """A generated gallery-dl error text."""
    return faker.sentence()


@pytest.fixture
def failure_status(faker: Faker) -> int:
    """A non-zero gallery-dl exit status."""
    return faker.pyint(min_value=1, max_value=GALLERY_FAILURE_STATUS_MAX)


@pytest.fixture
def successful_job(mocker: MockerFixture, media_name: str) -> str:
    """`run_job` replaced by a job that writes one video file and succeeds; returns its name."""

    def fake_job(url: str, work_dir: Path, cancel: threading.Event) -> JobOutcome:
        (work_dir / media_name).write_bytes(b"video")
        return 0, "", None

    mocker.patch(GALLERY_RUN_JOB_TARGET, side_effect=fake_job)
    return media_name


@pytest.fixture
def failing_job(
    download_dir: Path, mocker: MockerFixture, failure_status: int, job_error: str
) -> str:
    """`run_job` replaced by a job that fails without files; returns its error text."""
    mocker.patch(GALLERY_RUN_JOB_TARGET, return_value=(failure_status, job_error, None))
    return job_error


@pytest.fixture
def partial_job(
    mocker: MockerFixture, photo_name: str, failure_status: int, faker: Faker
) -> PartialDownload:
    """`run_job` replaced by a job that writes one file and fails on another."""
    failed_name = faker.pystr() + faker.random_element(sorted(IMAGE_EXTENSIONS))

    def fake_job(url: str, work_dir: Path, cancel: threading.Event) -> JobOutcome:
        (work_dir / photo_name).write_bytes(b"photo")
        return failure_status, f"{faker.sentence()} {failed_name}", None

    mocker.patch(GALLERY_RUN_JOB_TARGET, side_effect=fake_job)
    return PartialDownload(written_name=photo_name, failed_name=failed_name)


@pytest.fixture
def stuck_job(mocker: MockerFixture, media_name: str, monkeypatch: pytest.MonkeyPatch) -> StuckJob:
    """`run_job` replaced by a job that only stops once cancelled; the timeout is tiny."""
    monkeypatch.setattr(settings, "DOWNLOAD_TIMEOUT", GALLERY_JOB_TIMEOUT_SECONDS)
    job = StuckJob(media_name)
    mocker.patch(GALLERY_RUN_JOB_TARGET, side_effect=job)
    return job


@pytest.fixture
def timed_out_download(
    stuck_job: StuckJob, mocker: MockerFixture, gallery_dl_url: str
) -> Callable[[], Awaitable[DownloadResult]]:
    """Awaiting the result downloads with the stuck job, then waits for the work dir removal."""
    removed = asyncio.Event()

    def remove_and_signal(directory: Path, *, ignore_errors: bool) -> None:
        rmtree(directory, ignore_errors=ignore_errors)
        removed.set()

    mocker.patch(GALLERY_RMTREE_TARGET, side_effect=remove_and_signal)

    async def run() -> DownloadResult:
        outcome = await download_media(gallery_dl_url)
        await asyncio.wait_for(removed.wait(), timeout=GALLERY_CLEANUP_WAIT_SECONDS)
        return outcome

    return run


@pytest.fixture
def remove_tree(mocker: MockerFixture) -> MagicMock:
    """`shutil.rmtree` as seen by the gallery module, replaced by a mock."""
    return mocker.patch(GALLERY_RMTREE_TARGET)


@pytest.fixture(params=("existing", "missing"))
def cleanup_target(request: pytest.FixtureRequest, download_dir: Path, faker: Faker) -> Path:
    """An existing directory, then one that does not exist."""
    if request.param == "existing":
        return download_dir
    return download_dir / faker.pystr()


@pytest.fixture
def execute(mocker: MockerFixture) -> MagicMock:
    """`Job.execute` replaced by a mock, to see whether the site would be contacted."""
    return mocker.patch.object(Job, "execute")
