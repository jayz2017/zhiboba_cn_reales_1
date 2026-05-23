from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

T = TypeVar("T")

logger = logging.getLogger(__name__)


def _before_sleep_log(retry_state):
    logger.warning(
        "retry_attempt",
        extra={
            "attempt": retry_state.attempt_number,
            "outcome": str(retry_state.outcome),
        },
    )


def retryable(
    *,
    attempts: int = 5,
    min_wait_seconds: float = 0.5,
    max_wait_seconds: float = 8.0,
    exception_types: tuple[type[BaseException], ...] = (ConnectionError, TimeoutError, OSError),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    return retry(
        reraise=True,
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=min_wait_seconds, max=max_wait_seconds),
        retry=retry_if_exception_type(exception_types),
        before_sleep=_before_sleep_log,
    )
