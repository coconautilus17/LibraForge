"""Opt-in debug tracing for data-choosing / data-altering / data-scoring code.

Instruments the fixer (and later the organizer) so every function that
*chooses*, *alters*, or *scores* data can announce its inputs and outputs when
debugging is turned on, and costs nothing when it is off.

Design constraints:
* The fixer's stdout is parsed line-by-line by app/main.py, so trace output
  must never go to stdout. It goes to stderr by default, or a file via
  configure(file_path=...).
* The fixer runs work on a ThreadPoolExecutor, so the sink is lock-guarded and
  every line is tagged with the worker thread name.
* Tracing is disabled by default: a decorated function behaves identically to
  the undecorated one until configure(enabled=True) is called.

Environment variables (override configure() defaults):
  LIBRAFORGE_DEBUG=1               enable tracing
  LIBRAFORGE_DEBUG_FILE=/path      write to file instead of stderr
  LIBRAFORGE_DEBUG_CATEGORIES=score,choose   filter by category

Usage:
    from app.debug_trace import trace, trace_block, log, subject
    from app.debug_trace import CHOOSE, ALTER, SCORE

    @trace(SCORE)
    def score_product_for_metadata(product, clues, ...): ...

    @trace(ALTER, capture=["value"])
    def clean_text(value): ...

    with subject(folder_name):
        ...
        with trace_block(CHOOSE, "pick winner", n=len(candidates)):
            ...
"""

from __future__ import annotations

import functools
import inspect
import os
import sys
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterable, Optional, Sequence

CHOOSE = "choose"
ALTER  = "alter"
SCORE  = "score"

_ENV_ENABLE     = "LIBRAFORGE_DEBUG"
_ENV_FILE       = "LIBRAFORGE_DEBUG_FILE"
_ENV_CATEGORIES = "LIBRAFORGE_DEBUG_CATEGORIES"


class _Sink:
    """Thread-safe writer to a stream and/or an append-mode file."""

    def __init__(self, stream=None, file_path: Optional[str] = None) -> None:
        self._lock   = threading.Lock()
        self._stream = stream
        self._fh: Any = None
        if file_path:
            try:
                self._fh = open(file_path, "a", encoding="utf-8")
            except OSError:
                if self._stream is None:
                    self._stream = sys.stderr

    def write(self, line: str) -> None:
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.write(line + "\n")
                    self._stream.flush()
                except Exception:
                    pass
            if self._fh is not None:
                try:
                    self._fh.write(line + "\n")
                    self._fh.flush()
                except Exception:
                    pass

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.close()
                except Exception:
                    pass
                self._fh = None


class _Config:
    enabled:      bool           = False
    categories:   Optional[set]  = None   # None == all categories
    max_value_len: int           = 300
    sink:         Optional[_Sink] = None


_config = _Config()
_local  = threading.local()


def configure(
    enabled: bool = False,
    *,
    file_path: Optional[str] = None,
    stream=None,
    categories: Optional[Iterable[str]] = None,
    max_value_len: int = 300,
) -> None:
    """Turn tracing on/off and configure the sink. Safe to call multiple times."""
    if not enabled and os.environ.get(_ENV_ENABLE, "").strip() not in ("", "0", "false", "False"):
        enabled = True
    if file_path is None:
        file_path = os.environ.get(_ENV_FILE) or None
    if categories is None:
        env_cats = os.environ.get(_ENV_CATEGORIES, "").strip()
        if env_cats:
            categories = [c.strip() for c in env_cats.split(",") if c.strip()]

    if _config.sink is not None:
        _config.sink.close()
        _config.sink = None

    _config.enabled       = bool(enabled)
    _config.categories    = set(categories) if categories else None
    _config.max_value_len = max_value_len

    if _config.enabled:
        _config.sink = _Sink(stream=stream or sys.stderr, file_path=file_path)
        _config.sink.write(
            f"# libraforge debug-trace  "
            f"categories={sorted(_config.categories) if _config.categories else 'all'}"
        )


def is_enabled(category: Optional[str] = None) -> bool:
    if not _config.enabled:
        return False
    if category is not None and _config.categories is not None:
        return category in _config.categories
    return True


# ---------------------------------------------------------------------------
# Subject correlation -- which book/file is being processed
# ---------------------------------------------------------------------------

def set_subject(value: Optional[str]) -> None:
    _local.subject = value


def get_subject() -> Optional[str]:
    return getattr(_local, "subject", None)


@contextmanager
def subject(value: Optional[str]):
    """Tag every trace line in this block with `value` (e.g. the book folder name)."""
    prev = getattr(_local, "subject", None)
    _local.subject = value
    try:
        yield
    finally:
        _local.subject = prev


# ---------------------------------------------------------------------------
# Value summarization
# ---------------------------------------------------------------------------

def _summarize(value: Any, max_len: int) -> str:
    """Compact, never-raising repr. Collapses big containers to shape+sample."""
    try:
        if value is None or isinstance(value, (bool, int, float)):
            return repr(value)
        if isinstance(value, str):
            s = value
            return repr(s if len(s) <= max_len else s[:max_len] + f"...(+{len(s) - max_len})")
        if isinstance(value, dict):
            keys = list(value.keys())
            shown = ", ".join(
                f"{k!r}: {_summarize(value[k], max_len // 2)}" for k in keys[:8]
            )
            extra = f", +{len(keys) - 8} more" if len(keys) > 8 else ""
            return "{" + shown + extra + "}"
        if isinstance(value, (list, tuple, set)):
            kind  = type(value).__name__
            items = list(value)
            shown = ", ".join(_summarize(v, max_len // 2) for v in items[:5])
            extra = f", +{len(items) - 5} more" if len(items) > 5 else ""
            return f"{kind}(len={len(items)})[{shown}{extra}]"
        s = repr(value)
        return s if len(s) <= max_len else s[:max_len] + "..."
    except Exception:
        try:
            return f"<unreprable {type(value).__name__}>"
        except Exception:
            return "<unreprable>"


def _emit(line: str) -> None:
    sink = _config.sink
    if sink is None:
        return
    subj   = get_subject()
    prefix = f"[{threading.current_thread().name}]"
    if subj:
        prefix += f"[{subj}]"
    sink.write(f"{prefix} {line}")


# ---------------------------------------------------------------------------
# Core decorator
# ---------------------------------------------------------------------------

def trace(
    category: Optional[str] = None,
    *,
    name: Optional[str] = None,
    capture: Optional[Sequence[str]] = None,
    show_result: bool = True,
) -> Callable:
    """Decorate a function to log its inputs/outputs when tracing is enabled.

    category    CHOOSE, ALTER, SCORE, or any string; used for filtering.
    name        label to use in output (defaults to function name).
    capture     list of arg names to log on entry. None => all args (compact).
                [] => log entry event only, no args.
    show_result if False, return value is not logged (use for huge returns).
    """
    def decorator(func: Callable) -> Callable:
        label = name or func.__name__
        try:
            sig         = inspect.signature(func)
            param_names = list(sig.parameters)
        except (TypeError, ValueError):
            sig         = None
            param_names = []

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not _config.enabled or (
                category is not None
                and _config.categories is not None
                and category not in _config.categories
            ):
                return func(*args, **kwargs)

            cat     = category or "trace"
            max_len = _config.max_value_len
            arg_repr = _format_args(sig, param_names, args, kwargs, capture, max_len)
            _emit(f"[{cat}] -> {label}({arg_repr})")
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                elapsed = (time.perf_counter() - start) * 1000
                _emit(f"[{cat}] !! {label} raised {exc!r}  ({elapsed:.1f}ms)")
                raise
            elapsed = (time.perf_counter() - start) * 1000
            if show_result:
                _emit(f"[{cat}] <- {label} = {_summarize(result, max_len)}  ({elapsed:.1f}ms)")
            else:
                _emit(f"[{cat}] <- {label} done  ({elapsed:.1f}ms)")
            return result

        wrapper.__wrapped__ = func  # type: ignore[attr-defined]
        return wrapper

    return decorator


def _format_args(sig, param_names, args, kwargs, capture, max_len) -> str:
    if capture is not None and len(capture) == 0:
        return ""
    try:
        if sig is not None:
            bound = sig.bind_partial(*args, **kwargs)
            bound.apply_defaults()
            data = dict(bound.arguments)
        else:
            data = dict(kwargs)
            for i, val in enumerate(args):
                data[f"arg{i}"] = val
    except Exception:
        data = {f"arg{i}": v for i, v in enumerate(args)}
        data.update(kwargs)
    for noise in ("self", "cls"):
        data.pop(noise, None)
    if capture:
        data = {k: data[k] for k in capture if k in data}
    return ", ".join(f"{k}={_summarize(v, max_len // 2)}" for k, v in data.items())


# ---------------------------------------------------------------------------
# Inline / block helpers
# ---------------------------------------------------------------------------

@contextmanager
def trace_block(category: Optional[str], name: str, **fields):
    """Trace an inline section that isn't a whole function."""
    if not is_enabled(category):
        yield
        return
    cat     = category or "trace"
    max_len = _config.max_value_len
    field_repr = ", ".join(f"{k}={_summarize(v, max_len // 2)}" for k, v in fields.items())
    _emit(f"[{cat}] -> {{{name}}}({field_repr})")
    start = time.perf_counter()
    try:
        yield
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        _emit(f"[{cat}] !! {{{name}}} raised {exc!r}  ({elapsed:.1f}ms)")
        raise
    elapsed = (time.perf_counter() - start) * 1000
    _emit(f"[{cat}] <- {{{name}}} done  ({elapsed:.1f}ms)")


def log(category: Optional[str], message: str, **fields) -> None:
    """Emit a one-off trace line (a named checkpoint inside a function)."""
    if not is_enabled(category):
        return
    cat = category or "trace"
    if fields:
        max_len = _config.max_value_len
        extra   = " " + ", ".join(f"{k}={_summarize(v, max_len // 2)}" for k, v in fields.items())
    else:
        extra = ""
    _emit(f"[{cat}] .. {message}{extra}")
