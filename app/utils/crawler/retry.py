from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


T = TypeVar("T")


def retryable(
    *,
    attempts: int = 5,
    min_wait_seconds: float = 0.5,
    max_wait_seconds: float = 8.0,
    exception_types: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    return retry(
        reraise=True,
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=min_wait_seconds, max=max_wait_seconds),
        retry=retry_if_exception_type(exception_types),
    )
