from collections.abc import Awaitable, Callable

import inflight
from tests.fixtures import CriticalSection, TimedStages


async def test_same_url_is_serialized_and_lock_is_released(
    serialized_run: Callable[[], Awaitable[None]], critical_section: CriticalSection
) -> None:
    await serialized_run()

    assert critical_section.peak == 1
    assert not inflight._locks
    assert not inflight._waiters


async def test_different_urls_run_concurrently(
    parallel_run: Callable[[], Awaitable[None]], critical_section: CriticalSection
) -> None:
    await parallel_run()

    assert critical_section.peak == 2
    assert not inflight._locks


async def test_stage_timer_accumulates_repeated_stages(timed_stages: TimedStages) -> None:
    summary = timed_stages.timer.summary()

    assert summary == {
        f"{timed_stages.stage_name}_ms": timed_stages.stage_ms,
        "total_ms": timed_stages.total_ms,
    }
