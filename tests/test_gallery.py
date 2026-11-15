import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from unittest.mock import MagicMock

from gallery_dl import config as gdl_config

from constants import INSTAGRAM_PATH
from downloader.gallery import DownloadResult, cleanup, download_media
from downloader.gdl_job import Job, apply_settings, run_job
from tests import constants as spec
from tests.fixtures import (
    Credentials,
    JobPair,
    ParentJob,
    PartialDownload,
    StuckJob,
)


async def test_settings_without_auth() -> None:
    apply_settings()

    assert gdl_config.get((), spec.COOKIES_KEY) is None
    assert gdl_config.get(INSTAGRAM_PATH, spec.USERNAME_KEY) is None
    assert gdl_config.get((), spec.MTIME_KEY) is False
    assert gdl_config.get(spec.OUTPUT_PATH, spec.OUTPUT_MODE_KEY) == spec.OUTPUT_MODE_NULL


async def test_settings_with_cookies_file(cookies_configured: Path) -> None:
    apply_settings()

    assert gdl_config.get((), spec.COOKIES_KEY) == str(cookies_configured)


async def test_missing_cookies_file_is_not_passed(missing_cookies_configured: Path) -> None:
    apply_settings()

    assert gdl_config.get((), spec.COOKIES_KEY) is None


async def test_credentials_take_priority_over_cookies(
    cookies_configured: Path, credentials_configured: Credentials
) -> None:
    apply_settings()

    assert gdl_config.get(INSTAGRAM_PATH, spec.USERNAME_KEY) == credentials_configured.username
    assert gdl_config.get(INSTAGRAM_PATH, spec.PASSWORD_KEY) == credentials_configured.password
    assert gdl_config.get((), spec.COOKIES_KEY) is None


async def test_partial_credentials_are_ignored(
    partial_credentials_configured: Credentials,
) -> None:
    apply_settings()

    assert gdl_config.get(INSTAGRAM_PATH, spec.USERNAME_KEY) is None


async def test_credentials_are_removed_when_unset(credentials_unset_again: Credentials) -> None:
    apply_settings()

    assert gdl_config.get(INSTAGRAM_PATH, spec.PASSWORD_KEY) is None


async def test_each_job_answers_its_own_destination(job_pair: JobPair) -> None:
    answers = (
        job_pair.first.extractor.config(spec.BASE_DIRECTORY_KEY),
        job_pair.second.extractor.config(spec.BASE_DIRECTORY_KEY),
    )

    assert answers == (str(job_pair.first_dest), str(job_pair.second_dest))
    assert gdl_config.get((), spec.BASE_DIRECTORY_KEY) is None


async def test_child_job_inherits_destination_and_cancel_flag(
    parent_job: ParentJob, gallery_dl_url: str
) -> None:
    child = Job(gallery_dl_url, parent_job.job)

    assert child.extractor.config(spec.BASE_DIRECTORY_KEY) == str(parent_job.dest)
    assert child.cancel is parent_job.cancel
    assert child.root is parent_job.job


async def test_successful_download_returns_files_and_timings(
    successful_job: str, gallery_dl_url: str
) -> None:
    outcome = await download_media(gallery_dl_url)

    assert outcome.success
    assert [media.path.name for media in outcome.media_files] == [successful_job]
    assert outcome.timings[spec.GALLERY_DOWNLOAD_TIMING_KEY] >= 0
    assert outcome.work_dir is not None
    assert outcome.work_dir.is_dir()


async def test_failed_download_reports_gallery_dl_error(
    failing_job: str, gallery_dl_url: str, download_dir: Path
) -> None:
    outcome = await download_media(gallery_dl_url)

    assert not outcome.success
    assert outcome.error == failing_job
    assert list(download_dir.iterdir()) == []


async def test_partial_download_is_a_failure(
    partial_job: PartialDownload, gallery_dl_url: str, download_dir: Path
) -> None:
    outcome = await download_media(gallery_dl_url)

    assert not outcome.success
    assert partial_job.failed_name in outcome.error
    assert list(download_dir.iterdir()) == []


async def test_timeout_cancels_job_and_cleans_up_after_it_stops(
    timed_out_download: Callable[[], Awaitable[DownloadResult]],
    stuck_job: StuckJob,
    download_dir: Path,
) -> None:
    outcome = await timed_out_download()

    assert outcome.success is False
    assert spec.TIMED_OUT_MESSAGE in outcome.error
    assert stuck_job.stopped.is_set()
    assert list(download_dir.iterdir()) == []


async def test_unsupported_url_is_reported(
    unsupported_url: str, download_dir: Path, cancel_event: threading.Event
) -> None:
    status, error, first_file_at = run_job(unsupported_url, download_dir, cancel_event)

    assert status != 0
    assert error == spec.UNSUPPORTED_URL_MESSAGE
    assert first_file_at is None


async def test_cleanup_ignores_errors_for_existing_and_missing_directories(
    cleanup_target: Path, remove_tree: MagicMock
) -> None:
    cleanup(cleanup_target)

    remove_tree.assert_called_once_with(cleanup_target, ignore_errors=True)


async def test_job_cancelled_while_queued_does_not_contact_the_site(
    execute: MagicMock, gallery_dl_url: str, download_dir: Path, set_cancel_event: threading.Event
) -> None:
    status, error, first_file_at = run_job(gallery_dl_url, download_dir, set_cancel_event)

    assert status != 0
    assert error == spec.CANCELLED_MESSAGE
    assert first_file_at is None
    execute.assert_not_called()
