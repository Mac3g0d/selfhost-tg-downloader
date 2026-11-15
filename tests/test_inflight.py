import asyncio

import inflight
from inflight import url_lock
from timing import StageTimer


async def test_same_url_is_serialized_and_lock_is_released() -> None:
    active = 0
    peak = 0

    async def work(url: str) -> None:
        nonlocal active, peak
        async with url_lock(url):
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1

    await asyncio.gather(*(work("https://vm.tiktok.com/a") for _ in range(3)))

    assert peak == 1
    assert not inflight._locks
    assert not inflight._waiters


async def test_different_urls_run_concurrently() -> None:
    both_inside = asyncio.Event()
    inside = 0

    async def work(url: str) -> None:
        nonlocal inside
        async with url_lock(url):
            inside += 1
            if inside == 2:
                both_inside.set()
            await asyncio.wait_for(both_inside.wait(), timeout=1)

    await asyncio.gather(work("https://vm.tiktok.com/a"), work("https://vm.tiktok.com/b"))


def test_stage_timer_accumulates_repeated_stages() -> None:
    timer = StageTimer()
    with timer.stage("upload"):
        pass
    with timer.stage("upload"):
        pass

    summary = timer.summary()

    assert set(summary) == {"upload_ms", "total_ms"}
    assert summary["total_ms"] >= summary["upload_ms"] >= 0
