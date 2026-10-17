"""Write CZML documents for the moving entities: trucks, SAR assets, and debris crews."""

from __future__ import annotations

from typing import Any

from landfall.config import T0, T_END, iso

COLORS = {
    "truck": [255, 196, 0, 255],
    "helo": [0, 229, 255, 255],
    "boat": [64, 160, 255, 255],
    "high_water_truck": [120, 255, 120, 255],
    "crew": [255, 120, 40, 255],
}
HEIGHT = {"helo": 600.0, "truck": 5.0, "boat": 2.0, "high_water_truck": 5.0, "crew": 5.0}


def document() -> dict[str, Any]:
    """Return the CZML document packet with the scenario clock."""
    return {
        "id": "document", "name": "LANDFALL plan", "version": "1.0",
        "clock": {"interval": f"{iso(T0)}/{iso(T_END)}", "currentTime": iso(T0), "multiplier": 7200,
                  "range": "CLAMPED", "step": "SYSTEM_CLOCK_MULTIPLIER"},
    }


def mover(entity_id: str, kind: str, name: str, samples: list[tuple[float, float, float]],
          label: str | None = None) -> dict[str, Any] | None:
    """Return a CZML packet for an entity that moves along timed samples (hour, lon, lat)."""
    pts = sorted(samples, key=lambda s: s[0])
    if not pts:
        return None
    # Remove duplicate times, which CZML interpolation does not accept.
    clean: list[tuple[float, float, float]] = []
    for p in pts:
        if clean and abs(p[0] - clean[-1][0]) < 1e-6:
            clean[-1] = p
        else:
            clean.append(p)
    if len(clean) == 1:
        clean.append((clean[0][0] + 0.01, clean[0][1], clean[0][2]))
    h = HEIGHT.get(kind, 5.0)
    carto: list[float] = []
    for t, lon, lat in clean:
        carto += [round(t * 3600.0, 1), round(lon, 5), round(lat, 5), h]
    start = T0.timestamp() + clean[0][0] * 3600
    end = T0.timestamp() + clean[-1][0] * 3600
    from datetime import UTC, datetime

    avail = f"{datetime.fromtimestamp(start, UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}/" \
            f"{datetime.fromtimestamp(end, UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}"
    color = COLORS.get(kind, [255, 255, 255, 255])
    pkt: dict[str, Any] = {
        "id": entity_id, "name": name, "availability": avail,
        "properties": {"kind": kind},
        "position": {"epoch": iso(T0), "cartographicDegrees": carto, "interpolationAlgorithm": "LINEAR"},
        "point": {"pixelSize": 9 if kind == "helo" else 7, "color": {"rgba": color},
                  "outlineColor": {"rgba": [0, 0, 0, 255]}, "outlineWidth": 1},
        "path": {"material": {"solidColor": {"color": {"rgba": color[:3] + [120]}}}, "width": 1.5,
                 "leadTime": 0, "trailTime": 3 * 3600, "resolution": 120},
    }
    if label:
        pkt["label"] = {"text": label, "font": "11px monospace", "pixelOffset": {"cartesian2": [10, -10]},
                        "fillColor": {"rgba": color}, "showBackground": False, "show": False}
    return pkt


def along_path(path: list[tuple[float, float]], t_start: float, t_end: float) -> list[tuple[float, float, float]]:
    """Return timed samples along a polyline, with the time in proportion to the distance."""
    from landfall.geoutil import haversine_km

    if len(path) < 2:
        return [(t_start, path[0][0], path[0][1])] if path else []
    seg = [float(haversine_km(a[1], a[0], b[1], b[0])) for a, b in zip(path[:-1], path[1:], strict=True)]
    total = sum(seg) or 1.0
    out = [(t_start, path[0][0], path[0][1])]
    acc = 0.0
    step = max(1, len(path) // 60)  # keep at most about 60 samples on a path
    for i in range(1, len(path)):
        acc += seg[i - 1]
        if i % step == 0 or i == len(path) - 1:
            out.append((t_start + (t_end - t_start) * acc / total, path[i][0], path[i][1]))
    return out
