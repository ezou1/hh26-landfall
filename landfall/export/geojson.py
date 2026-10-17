"""Convert grids to GeoJSON band polygons and write the static GeoJSON files."""

from __future__ import annotations

from typing import Any

import numpy as np
from rasterio import features as rfeatures
from rasterio.transform import from_origin
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from landfall.ingest.geo import CountyGrid


def bands(grid: CountyGrid, field: np.ndarray, thresholds: list[float], key: str,
          mask: np.ndarray | None = None, extra: dict[str, Any] | None = None,
          simplify_deg: float = 0.0015) -> dict[str, Any]:
    """Return one MultiPolygon feature for each threshold: the area where field >= threshold."""
    dlon = grid.lon[1] - grid.lon[0]
    dlat = grid.lat[1] - grid.lat[0]
    tf = from_origin(grid.lon[0] - dlon / 2, grid.lat[-1] + dlat / 2, dlon, dlat)
    feats = []
    for thr in thresholds:
        m = field >= thr
        if mask is not None:
            m &= mask
        if not m.any():
            continue
        img = m[::-1, :].astype(np.uint8)
        polys = [shape(g) for g, v in rfeatures.shapes(img, mask=img.astype(bool), transform=tf) if v == 1]
        geom = unary_union(polys).buffer(0).simplify(simplify_deg, preserve_topology=True)
        if geom.is_empty:
            continue
        props: dict[str, Any] = {key: thr}
        if extra:
            props.update(extra)
        feats.append({"type": "Feature", "properties": props, "geometry": mapping(geom)})
    return {"type": "FeatureCollection", "features": feats}


def roads(edges: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the display road network as GeoJSON LineStrings."""
    feats = []
    seen: set[tuple[int, int]] = set()
    for e in edges:
        if not e["display"]:
            continue
        key = (min(e["u"], e["v"]), max(e["u"], e["v"]))
        if key in seen and not e["is_critical"]:
            continue
        seen.add(key)
        feats.append({
            "type": "Feature",
            "properties": {
                "edge_id": e["edge_id"], "name": e["name"], "highway": e["highway"],
                "lanes": e["lanes"], "is_critical": e["is_critical"],
                "critical_name": e["critical_name"], "is_bridge": e["bridge"],
            },
            "geometry": {"type": "LineString", "coordinates": [list(c) for c in e["coords"]]},
        })
    return {"type": "FeatureCollection", "features": feats}
