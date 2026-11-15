import asyncio
import time

import inflight
from timing import StageTimer


class _Counter:
    """Tracks how many workers are inside a critical section at once."""

    def __init__(self) -> None:
        self.active = 0
        self.peak = 0

    def enter(self) -> None:
        self.active += 1
        self.peak = max(self.peak, self.active)

    def leave(self) -> None:
        self.active -= 1


async def _serialized_work(counter: _Counter, url: str) -> None:
    async with inflight.url_lock(url):
        counter.enter()
        await asyncio.sleep(0.01)
        counter.leave()


async def test_same_url_is_serialized_and_lock_is_released() -> None:
    counter = _Counter()

    url = "https://vm.tiktok.com/a"
    workers = [_serialized_work(counter, url) for _ in range(3)]
    await asyncio.gather(*workers)

    assert counter.peak == 1
    assert not inflight._locks
    assert not inflight._waiters


async def _wait_for_peer(counter: _Counter, both_inside: asyncio.Event, url: str) -> None:
    async with inflight.url_lock(url):
        counter.enter()
        if counter.active == 2:
            both_inside.set()
        await asyncio.wait_for(both_inside.wait(), timeout=1)


async def test_different_urls_run_concurrently() -> None:
    counter = _Counter()
    both_inside = asyncio.Event()

    await asyncio.gather(
        _wait_for_peer(counter, both_inside, "https://vm.tiktok.com/a"),
        _wait_for_peer(counter, both_inside, "https://vm.tiktok.com/b"),
    )


def _run_upload_stage(timer: StageTimer) -> None:
    with timer.stage("upload"):
        time.sleep(0.001)


def test_stage_timer_accumulates_repeated_stages() -> None:
    timer = StageTimer()
    _run_upload_stage(timer)
    _run_upload_stage(timer)

    summary = timer.summary()

    assert set(summary) == {"upload_ms", "total_ms"}
    assert summary["upload_ms"] >= 0
    assert summary["total_ms"] >= summary["upload_ms"]
