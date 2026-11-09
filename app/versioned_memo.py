"""Remember a text function's results while the lists it depends on are unchanged.

The matcher cleans the same few titles and names thousands of times per book
(every candidate is compared against the same local title and author). Text
cleanup depends only on its input and on the user's editable lists (title noise,
publishers), so each result is kept under the lists' current version and is
never reused once a list changes.
"""
from __future__ import annotations

import functools
from collections.abc import Callable, Hashable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def memo_while(version: Callable[[], Hashable], maxsize: int = 1 << 16) -> Callable[[F], F]:
    """Decorate a function of hashable positional arguments whose result is
    immutable and depends only on its arguments and on what `version()`
    identifies. Calls with unhashable or keyword arguments are not remembered."""

    def decorator(func: F) -> F:
        @functools.lru_cache(maxsize=maxsize)
        def remembered(_version: Hashable, *args: Any) -> Any:
            return func(*args)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if kwargs:
                return func(*args, **kwargs)
            try:
                return remembered(version(), *args)
            except TypeError:  # an unhashable argument
                return func(*args)

        wrapper.cache_clear = remembered.cache_clear  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator
