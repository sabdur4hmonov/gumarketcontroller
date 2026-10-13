"""Pure byte/text CPU work: two workers, no cached async clients or sessions."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")
CPU_WORKERS = 2
_pool = ThreadPoolExecutor(max_workers=CPU_WORKERS, thread_name_prefix="gulbot-cpu")


async def run_cpu(function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    """Session/ORM writes stay with the caller; only copied input data goes here.

    The executor is process-owned pure computation, not an asyncio socket/client.
    Cancellation cancels queued work; running image work finishes without DB access.
    """
    return await asyncio.get_running_loop().run_in_executor(
        _pool, partial(function, *args, **kwargs)
    )
