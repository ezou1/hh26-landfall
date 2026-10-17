"""Send the medevac victims to hospitals and track the free beds of each hospital.

Priority-1 victims and 20% of priority-2 victims go to a hospital. A victim goes to the
nearest hospital with a free bed. A helicopter victim goes to a hospital with a helipad.
The injuries of the damage model also use beds. Each hospital frees 10% of its used
beds each day.
"""

from __future__ import annotations

import numpy as np

from landfall.config import (
    HOSPITAL_FREE_FRACTION,
    HOSPITAL_RECOVERY_PER_DAY,
    HOURS,
    MEDEVAC_P2_FRACTION,
)
from landfall.geoutil import haversine_km
from landfall.logistics.sar import Task

H = HOURS + 1


def hospital_beds(hospitals: list[dict[str, object]], tasks: list[Task], injuries_by_hour: np.ndarray,
                  rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Assign medevac victims to hospitals. Return (free beds [hospital, hour], patients [hospital, hour])."""
    n = len(hospitals)
    total = np.array([float(h["beds"]) for h in hospitals])
    free = total * HOSPITAL_FREE_FRACTION
    lat = np.array([float(h["lat"]) for h in hospitals])
    lon = np.array([float(h["lon"]) for h in hospitals])
    pad = np.array([bool(h["has_helipad"]) for h in hospitals])
    arrivals = np.zeros((n, H))
    # Injuries of the damage model: split by bed count, except the overflow hospital.
    share = total / total.sum()
    arrivals += share[:, None] * injuries_by_hour[None, :]
    for t in tasks:
        if t.served_h is None:
            continue
        p2 = sum(rng.random() < MEDEVAC_P2_FRACTION for _ in range(t.persons)) if t.priority == 2 else 0
        t.medevac_persons = t.persons if t.priority == 1 else int(p2)
    events = sorted((t.served_h, i) for i, t in enumerate(tasks) if t.served_h is not None and t.medevac_persons)
    free_h = np.zeros((n, H))
    patients = np.zeros((n, H))
    k = 0
    cur = free.copy()
    for h in range(H):
        cur = cur + HOSPITAL_RECOVERY_PER_DAY / 24.0 * (total - cur)
        cur = cur - arrivals[:, h]
        while k < len(events) and events[k][0] < h + 1:
            t = tasks[events[k][1]]
            d = haversine_km(t.lat, t.lon, lat, lon)
            ok = cur >= t.medevac_persons
            if t.asset_type == "helo":
                ok &= pad
            if not ok.any():
                ok = pad if t.asset_type == "helo" else np.ones(n, bool)
            j = int(np.argmin(np.where(ok, d, np.inf)))
            t.hospital_id = str(hospitals[j]["id"])
            cur[j] -= t.medevac_persons
            k += 1
        cur = np.clip(cur, 0.0, total)
        free_h[:, h] = cur
        patients[:, h] = total - cur
    return free_h, patients
