"""Configure structlog and record the use of fallback data."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import structlog

from landfall.config import CACHE, SEED, git_sha

_CONFIGURED = False
FALLBACK_FILE = CACHE / "fallbacks.json"


def get_logger(name: str = "landfall") -> structlog.stdlib.BoundLogger:
    """Return a structlog logger that writes one line for each event to stdout."""
    global _CONFIGURED
    if not _CONFIGURED:
        logging.basicConfig(format="%(message)s", level=logging.INFO)
        structlog.configure(
            processors=[
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso", utc=True),
                structlog.dev.ConsoleRenderer(colors=False),
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
        )
        for noisy in ("httpx", "urllib3", "matplotlib", "numba", "fiona", "rasterio"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
        _CONFIGURED = True
    return structlog.get_logger(name)


@contextmanager
def stage(name: str, **kw: object) -> Iterator[dict[str, object]]:
    """Log one line with the duration of a pipeline stage."""
    log = get_logger()
    info: dict[str, object] = {}
    t = time.perf_counter()
    yield info
    log.info("stage", stage=name, seconds=round(time.perf_counter() - t, 2), **kw, **info)


def _load() -> dict[str, str]:
    if FALLBACK_FILE.exists():
        return json.loads(FALLBACK_FILE.read_text())
    return {}


def record_fallback(item: str, reason: str) -> None:
    """Log a WARNING and record that a data item uses fallback data."""
    get_logger().warning("fallback", item=item, reason=reason)
    d = _load()
    d[item] = reason
    FALLBACK_FILE.write_text(json.dumps(d, indent=2))


def clear_fallback(item: str) -> None:
    """Remove a data item from the fallback record after a real download."""
    d = _load()
    if item in d:
        del d[item]
        FALLBACK_FILE.write_text(json.dumps(d, indent=2))


def fallback_items() -> list[str]:
    """Return the names of the data items that use fallback data."""
    return sorted(_load())


def metadata(extra_fallback: list[str] | None = None) -> dict[str, object]:
    """Return the metadata block that every artifact carries."""
    items = sorted(set(fallback_items()) | set(extra_fallback or []))
    return {
        "seed": SEED,
        "git_sha": git_sha(),
        "created_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "used_fallback": bool(items),
        "fallback_items": items,
    }
