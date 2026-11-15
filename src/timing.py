import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager

from constants import MS_PER_SECOND


def _to_ms(seconds: float) -> float:
    return round(seconds * MS_PER_SECOND, 1)


def _stage_durations(stages: dict[str, float]) -> dict[str, float]:
    return {f"{name}_ms": _to_ms(seconds) for name, seconds in stages.items()}


def new_request_id() -> str:
    return uuid.uuid4().hex[:8]


class StageTimer:
    """Accumulates wall-clock stage durations (monotonic clock) for one request."""

    __slots__ = ("_stages", "_started")

    def __init__(self) -> None:
        self._started = time.perf_counter()
        self._stages: dict[str, float] = {}

    @contextmanager
    def stage(self, name: str) -> Generator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self._add(name, time.perf_counter() - started)

    def summary(self) -> dict[str, float]:
        """Durations in milliseconds, keyed ``<stage>_ms`` plus ``total_ms``."""
        durations = _stage_durations(self._stages)
        durations["total_ms"] = _to_ms(time.perf_counter() - self._started)
        return durations

    def _add(self, name: str, elapsed: float) -> None:
        self._stages[name] = self._stages.get(name, 0) + elapsed
