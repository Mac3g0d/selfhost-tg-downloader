"""Fixtures for the per-URL lock and stage timer tests."""

import asyncio
import itertools
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import NamedTuple

import pytest
from faker import Faker
from pytest_mock import MockerFixture

import inflight
from tests.constants import PEER_TIMEOUT_SECONDS
from timing import StageTimer


class CriticalSection:
    """Counts how many workers are inside a critical section at once."""

    def __init__(self) -> None:
        self.active = 0
        self.peak = 0

    def enter(self) -> None:
        self.active += 1
        self.peak = max(self.peak, self.active)

    def leave(self) -> None:
        self.active -= 1


class TimedStages(NamedTuple):
    """A timer that ran one stage twice on a fake clock, with the durations it must report."""

    timer: StageTimer
    stage_name: str
    stage_ms: float
    total_ms: float


@pytest.fixture
def critical_section() -> CriticalSection:
    """A fresh counter of workers inside the guarded section."""
    return CriticalSection()


@pytest.fixture
def serialized_run(
    supported_url: str, critical_section: CriticalSection, faker: Faker
) -> Callable[[], Awaitable[None]]:
    """Awaiting the result runs 2-5 workers on one URL; each yields once inside the lock."""
    workers = faker.pyint(min_value=2, max_value=5)

    async def worker() -> None:
        async with inflight.url_lock(supported_url):
            critical_section.enter()
            await asyncio.sleep(0)
            critical_section.leave()

    async def run() -> None:
        await asyncio.gather(*(worker() for _ in range(workers)))

    return run


@pytest.fixture
def parallel_run(
    tiktok_url: str, instagram_url: str, critical_section: CriticalSection
) -> Callable[[], Awaitable[None]]:
    """Awaiting the result runs two workers on different URLs; each waits for its peer."""
    both_inside = asyncio.Event()

    async def worker(url: str) -> None:
        async with inflight.url_lock(url):
            critical_section.enter()
            if critical_section.active == 2:
                both_inside.set()
            await asyncio.wait_for(both_inside.wait(), timeout=PEER_TIMEOUT_SECONDS)

    async def run() -> None:
        await asyncio.gather(worker(tiktok_url), worker(instagram_url))

    return run


@pytest.fixture
def clock_ticks(faker: Faker) -> list[float]:
    """Six increasing readings of a fake clock, in whole seconds."""
    gaps = [faker.pyint(min_value=1, max_value=100) for _ in range(5)]
    return [float(tick) for tick in itertools.accumulate(gaps, initial=faker.pyint())]


@pytest.fixture
def timed_stages(mocker: MockerFixture, faker: Faker, clock_ticks: list[float]) -> TimedStages:
    """A timer whose clock is `clock_ticks`; the last tick is left for `summary()`.

    Clock reads: timer start, then start and end of two runs of one stage, then the summary.
    """
    mocker.patch("timing.time", SimpleNamespace(perf_counter=iter(clock_ticks).__next__))
    name = faker.pystr()
    timer = StageTimer()
    for _ in range(2):
        with timer.stage(name):
            faker.pyint()
    elapsed = [after - before for before, after in itertools.pairwise(clock_ticks)]
    return TimedStages(
        timer=timer,
        stage_name=name,
        stage_ms=(elapsed[1] + elapsed[3]) * 1000,
        total_ms=sum(elapsed) * 1000,
    )
