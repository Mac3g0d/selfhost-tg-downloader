import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager


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
            elapsed = time.perf_counter() - started
            self._stages[name] = self._stages.get(name, 0.0) + elapsed

    def summary(self) -> dict[str, float]:
        """Durations in milliseconds, keyed ``<stage>_ms`` plus ``total_ms``."""
        result = {f"{name}_ms": round(value * 1000, 1) for name, value in self._stages.items()}
        result["total_ms"] = round((time.perf_counter() - self._started) * 1000, 1)
        return result
