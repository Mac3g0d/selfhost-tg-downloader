import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

_locks: dict[str, asyncio.Lock] = {}
_waiters: dict[str, int] = {}


@asynccontextmanager
async def url_lock(url: str) -> AsyncGenerator[None]:
    """Serialize work per URL so concurrent requests reuse the first one's cache entry."""
    lock = _locks.setdefault(url, asyncio.Lock())
    _waiters[url] = _waiters.get(url, 0) + 1
    try:
        async with lock:
            yield
    finally:
        _waiters[url] -= 1
        if not _waiters[url]:
            _waiters.pop(url)
            _locks.pop(url)
