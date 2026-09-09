"""Shared Earth Engine I/O: initialisation, retrying fetches, atomic writes.

Everything in this module exists to make one class of bug impossible: an export
that appears to succeed while returning fewer rows than it should. See
`.claude/skills/failure-modes/SKILL.md` entries 4 and 5.

Three defences, and they only work together:

1. Requests stay small, so size limits are never approached.
2. Every fetch is checked against an independently computed server-side count.
3. Files are written atomically, so a failed check leaves nothing on disk for
   resume logic to trust later.
"""

from __future__ import annotations

import os
import random
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

import ee
import pandas as pd
import yaml

T = TypeVar("T")

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "data.yaml"


class TruncatedFetchError(RuntimeError):
    """A fetch returned a different number of rows than the server reported."""


def load_config(path: Path | str = DEFAULT_CONFIG) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def initialize(config: dict[str, Any] | None = None) -> str:
    """Initialise Earth Engine and return the project actually used."""
    config = config if config is not None else load_config()
    project = os.environ.get("EE_PROJECT") or config.get("gee", {}).get("project")
    if not project:
        raise RuntimeError(
            "No Earth Engine project. Set EE_PROJECT or gee.project in config/data.yaml."
        )
    ee.Initialize(project=project)
    return project


# --------------------------------------------------------------------------
# retry
# --------------------------------------------------------------------------
_TRANSIENT_MARKERS = (
    "429", "500", "502", "503", "504",
    "too many requests", "quota", "rate limit",
    "deadline", "timed out", "timeout",
    "internal error", "temporarily unavailable", "connection",
)


def _is_transient(exc: Exception) -> bool:
    """Distinguish a retryable hiccup from a deterministic error.

    Retrying a deterministic error forever is its own failure mode: it turns a
    clear message into a hang. Only markers of transport and throttling count.
    """
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


def with_retry(
    fn: Callable[[], T],
    *,
    what: str,
    max_retries: int = 5,
    backoff_base: float = 2.0,
) -> T:
    """Call `fn`, retrying transient Earth Engine failures with exponential backoff."""
    last: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - we re-raise below
            last = exc
            if not _is_transient(exc) or attempt == max_retries:
                raise
            delay = backoff_base**attempt + random.uniform(0, 0.5)
            print(
                f"    [retry {attempt + 1}/{max_retries}] {what}: "
                f"{type(exc).__name__}: {str(exc)[:120]} - waiting {delay:.1f}s"
            )
            time.sleep(delay)
    raise AssertionError(f"unreachable: {what}") from last


# --------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------
def fetch_features(
    fc: "ee.FeatureCollection",
    *,
    what: str,
    expected_rows: int | None = None,
    page_size: int = 5000,
    max_retries: int = 5,
    backoff_base: float = 2.0,
) -> pd.DataFrame:
    """Pull a FeatureCollection into a DataFrame, verifying nothing was truncated.

    `ee.data.computeFeatures` can return a partial result without raising when a
    size limit is hit. The only way to notice is to compare against a count the
    server computed separately, so that is done on every call rather than when it
    seems worth it.

    `expected_rows`, when given, is a second independent check: the number the
    caller believes it asked for. Both must agree.
    """
    server_count = with_retry(
        lambda: fc.size().getInfo(), what=f"{what} (size)",
        max_retries=max_retries, backoff_base=backoff_base,
    )

    def _compute() -> pd.DataFrame:
        return ee.data.computeFeatures(
            {
                "expression": fc,
                "fileFormat": "PANDAS_DATAFRAME",
                "pageSize": page_size,
            }
        )

    df = with_retry(
        _compute, what=f"{what} (fetch)",
        max_retries=max_retries, backoff_base=backoff_base,
    )
    df = pd.DataFrame(df)

    if len(df) != server_count:
        raise TruncatedFetchError(
            f"{what}: server reported {server_count} features, fetch returned "
            f"{len(df)}. This is silent truncation, not a data gap - reduce the "
            "request size rather than accepting the smaller number."
        )
    if expected_rows is not None and len(df) != expected_rows:
        raise TruncatedFetchError(
            f"{what}: expected {expected_rows} rows, server and fetch both say "
            f"{len(df)}. The request is internally consistent but does not match "
            "what the caller asked for - check the region, the filter or the date range."
        )
    return df


# --------------------------------------------------------------------------
# atomic writes
# --------------------------------------------------------------------------
def atomic_write(df: pd.DataFrame, path: Path | str, *, index: bool = False) -> Path:
    """Write a DataFrame so that `path` never exists in a partial state.

    Resume logic elsewhere skips files that exist. If a write can be interrupted
    halfway, that skip protects a truncated file forever - so the file only
    appears at its final path once it is complete.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    try:
        if path.suffix == ".parquet":
            df.to_parquet(tmp, index=index)
        else:
            df.to_csv(tmp, index=index)
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return path


def schema_fingerprint(columns: list[str]) -> str:
    """Stable fingerprint of a file's column set.

    Resume logic skips files that already exist. That is safe only while the schema
    is fixed: add a column to an exporter and every previously written year is
    silently skipped, leaving a panel whose columns depend on when each year
    happened to be fetched. Nothing errors - T4 just finds nulls it cannot explain.

    Recording the fingerprint in the manifest lets resume distinguish "already done"
    from "done under a different schema".
    """
    import hashlib

    joined = ",".join(columns)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def report(label: str, expected: Any, actual: Any) -> bool:
    """Print an expected/actual pair and return whether they match.

    The protocol requires the numbers to be visible, not just a pass/fail - a
    printed "OK" hides the case where the expectation itself was wrong.
    """
    ok = expected == actual
    mark = "OK" if ok else "MISMATCH"
    print(f"  [{mark:8}] {label}: expected {expected} -> actual {actual}")
    return ok
