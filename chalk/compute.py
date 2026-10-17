"""Fan out the Stage 1 sampler and the Stage 3 scenario solver.

When CHALK_MODE=remote and chalkcompute is available, the module wraps the two batch
functions with @chalkcompute.function and calls them remotely. If the import or a call
fails, the module logs a WARNING and runs the batch locally with joblib.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_REMOTE: dict[str, Any] = {}


def _remote_enabled() -> bool:
    """Return True if remote mode, credentials, and CHALK_COMPUTE=1 are all set.

    Compute is opt-in: a sandbox needs the pipeline code and the cached plan context.
    Also, the account must have free scaling-group capacity.
    """
    return (
        os.environ.get("CHALK_MODE", "local").lower() == "remote"
        and bool(os.environ.get("CHALK_CLIENT_ID"))
        and os.environ.get("CHALK_COMPUTE", "0") == "1"
    )


def _wrap_remote(name: str, fn: Callable[..., Any]) -> Any | None:
    """Return a chalkcompute remote function for fn, or None if that is not possible."""
    if name in _REMOTE:
        return _REMOTE[name]
    try:
        import chalkcompute as cc

        image = cc.Image.debian_slim().pip_install(
            ["numpy", "pandas", "scipy", "highspy", "ortools", "networkx", "torch", "pyarrow"]
        )
        remote = cc.function(fn, image=image, cpu="2", memory="4Gi", name=f"landfall_{name}")  # 2Gi minimum per CPU
        _REMOTE[name] = remote
        return remote
    except Exception as exc:  # noqa: BLE001
        from landfall.log import get_logger

        get_logger().warning("chalkcompute unavailable; joblib used", function=name, error=str(exc)[:200])
        _REMOTE[name] = None
        return None


def fan_out(
    name: str, fn: Callable[..., Any], args: Sequence[tuple[Any, ...]], n_jobs: int = -1
) -> list[Any]:
    """Run fn over every argument tuple. Use Chalk Compute if enabled, or joblib."""
    from landfall.log import get_logger

    log = get_logger()
    if _remote_enabled():
        remote = _wrap_remote(name, fn)
        if remote is not None:
            try:
                handles = [remote.defer(*a) for a in args]
                out = [h.result() for h in handles]
                log.info("chalkcompute fan-out", function=name, calls=len(args))
                return out
            except Exception as exc:  # noqa: BLE001
                log.warning("chalkcompute call failed; joblib used", function=name, error=str(exc)[:200])
    from joblib import Parallel, delayed

    return list(Parallel(n_jobs=n_jobs, backend="loky")(delayed(fn)(*a) for a in args))
