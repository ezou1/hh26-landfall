"""Give small geodesy helpers that all stages use."""

from __future__ import annotations

import numpy as np

EARTH_KM = 6371.0


def haversine_km(lat1: np.ndarray | float, lon1: np.ndarray | float,
                 lat2: np.ndarray | float, lon2: np.ndarray | float) -> np.ndarray:
    """Return the great-circle distance in km between points."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * EARTH_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def bearing_deg(lat1: np.ndarray | float, lon1: np.ndarray | float,
                lat2: np.ndarray | float, lon2: np.ndarray | float) -> np.ndarray:
    """Return the initial bearing in degrees from point 1 to point 2 (0 = north)."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    x = np.sin(dl) * np.cos(p2)
    y = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    return (np.degrees(np.arctan2(x, y)) + 360.0) % 360.0


def local_xy_km(lat: np.ndarray, lon: np.ndarray, lat0: float, lon0: float) -> tuple[np.ndarray, np.ndarray]:
    """Return east and north offsets in km from a reference point (flat-earth form)."""
    x = (np.asarray(lon) - lon0) * 111.32 * np.cos(np.radians(lat0))
    y = (np.asarray(lat) - lat0) * 111.32
    return x, y


def destination(lat: float, lon: float, bearing: np.ndarray, dist_km: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return the points at a bearing and a distance from a start point."""
    d = np.asarray(dist_km) / EARTH_KM
    b = np.radians(bearing)
    p1, l1 = np.radians(lat), np.radians(lon)
    p2 = np.arcsin(np.sin(p1) * np.cos(d) + np.cos(p1) * np.sin(d) * np.cos(b))
    l2 = l1 + np.arctan2(np.sin(b) * np.sin(d) * np.cos(p1), np.cos(d) - np.sin(p1) * np.sin(p2))
    return np.degrees(p2), np.degrees(l2)
