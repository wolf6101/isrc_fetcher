"""Cancellable sleep utility for cooperative cancellation."""
from __future__ import annotations

import threading
import time

# Global cancel event — set() to cancel, clear() to reset.
_cancel_event = threading.Event()


def cancel():
    """Signal cancellation."""
    _cancel_event.set()


def reset():
    """Reset cancellation for a new job."""
    _cancel_event.clear()


def is_cancelled() -> bool:
    """Check if cancellation was requested."""
    return _cancel_event.is_set()


class CancelledError(Exception):
    """Raised when a sleep is interrupted by cancellation."""


def sleep(seconds: float):
    """Sleep that wakes up quickly when cancelled.

    Raises CancelledError if cancelled during sleep.
    """
    # Sleep in 0.5s chunks so we can respond to cancel quickly
    end = time.time() + seconds
    while time.time() < end:
        if _cancel_event.is_set():
            raise CancelledError("Operation cancelled by user")
        remaining = end - time.time()
        if remaining <= 0:
            break
        _cancel_event.wait(min(remaining, 0.5))

    if _cancel_event.is_set():
        raise CancelledError("Operation cancelled by user")
