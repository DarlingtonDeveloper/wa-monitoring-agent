"""Retry utilities with exponential backoff for API calls."""

import asyncio
import logging
import time

import anthropic
import httpx

log = logging.getLogger(__name__)

RETRIABLE_EXCEPTIONS = (
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    ConnectionError,
    TimeoutError,
)


def retry_api_call(fn, *args, max_retries=3, backoff_base=1.0, **kwargs):
    """Retry a synchronous API call with exponential backoff."""
    for attempt in range(max_retries + 1):
        try:
            return fn(*args, **kwargs)
        except RETRIABLE_EXCEPTIONS as e:
            if attempt >= max_retries:
                raise
            wait = backoff_base * (2 ** attempt)
            log.warning(
                f"Retry {attempt + 1}/{max_retries} after {wait:.1f}s: "
                f"{type(e).__name__}: {e}"
            )
            time.sleep(wait)


async def retry_async_call(fn, *args, max_retries=3, backoff_base=1.0, **kwargs):
    """Retry an async call with exponential backoff."""
    for attempt in range(max_retries + 1):
        try:
            return await fn(*args, **kwargs)
        except RETRIABLE_EXCEPTIONS as e:
            if attempt >= max_retries:
                raise
            wait = backoff_base * (2 ** attempt)
            log.warning(
                f"Retry {attempt + 1}/{max_retries} after {wait:.1f}s: "
                f"{type(e).__name__}: {e}"
            )
            await asyncio.sleep(wait)
