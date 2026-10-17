import { Cartesian3, PolygonHierarchy } from "cesium";
import type { AreaGeom, LineGeom, LonLat } from "../api/types";

function validPoint(p: unknown): p is LonLat {
  return Array.isArray(p) && Number.isFinite(p[0]) && Number.isFinite(p[1]);
}

/** Remove bad points and repeated points from a line. */
export function cleanLine(path: readonly LonLat[] | null | undefined): LonLat[] {
  const out: LonLat[] = [];
  if (!Array.isArray(path)) return out;
  for (const p of path) {
    if (!validPoint(p)) continue;
    const last = out[out.length - 1];
    if (last && Math.abs(last[0] - p[0]) < 1e-7 && Math.abs(last[1] - p[1]) < 1e-7) continue;
    out.push([p[0], p[1]]);
  }
  return out;
}

/** Convert a line of [lon, lat] points to Cartesian3 positions at a fixed height. */
export function toCartesians(path: readonly LonLat[], height = 0): Cartesian3[] {
  const flat: number[] = [];
  for (const p of path) flat.push(p[0], p[1], height);
  return Cartesian3.fromDegreesArrayHeights(flat);
}

function ringToCartesians(ring: LonLat[]): Cartesian3[] | null {
  const c = cleanLine(ring);
  if (c.length > 1) {
    const a = c[0];
    const b = c[c.length - 1];
    if (Math.abs(a[0] - b[0]) < 1e-9 && Math.abs(a[1] - b[1]) < 1e-9) c.pop();
  }
  if (c.length < 3) return null;
  return toCartesians(c, 0);
}

/** Convert a polygon given as rings to a PolygonHierarchy, or null if the outer ring is not valid. */
export function ringsToHierarchy(rings: LonLat[][]): PolygonHierarchy | null {
  if (!Array.isArray(rings) || rings.length === 0) return null;
  const outer = ringToCartesians(rings[0]);
  if (!outer) return null;
  const holes: PolygonHierarchy[] = [];
  for (const r of rings.slice(1)) {
    const h = ringToCartesians(r);
    if (h) holes.push(new PolygonHierarchy(h));
  }
  return new PolygonHierarchy(outer, holes);
}

/** Convert a Polygon or a MultiPolygon to a list of PolygonHierarchy objects. */
export function areaToHierarchies(geom: AreaGeom | null | undefined): PolygonHierarchy[] {
  if (!geom) return [];
  const out: PolygonHierarchy[] = [];
  if (geom.type === "Polygon") {
    const h = ringsToHierarchy(geom.coordinates);
    if (h) out.push(h);
  } else if (geom.type === "MultiPolygon") {
    for (const poly of geom.coordinates) {
      const h = ringsToHierarchy(poly);
      if (h) out.push(h);
    }
  }
  return out;
}

/** Convert a LineString or a MultiLineString to a list of lines. */
export function lineGeomToPaths(geom: LineGeom | null | undefined): LonLat[][] {
  if (!geom) return [];
  if (geom.type === "LineString") return [cleanLine(geom.coordinates)].filter((l) => l.length >= 2);
  if (geom.type === "MultiLineString") return geom.coordinates.map(cleanLine).filter((l) => l.length >= 2);
  return [];
}

/** Return the outer ring centroid of an area, as [lon, lat]. */
export function areaCentroid(geom: AreaGeom | null | undefined): LonLat | null {
  if (!geom) return null;
  let best: LonLat[] | null = null;
  if (geom.type === "Polygon") best = geom.coordinates[0] ?? null;
  else if (geom.type === "MultiPolygon") {
    let maxLen = -1;
    for (const p of geom.coordinates) {
      const r = p[0];
      if (r && r.length > maxLen) {
        maxLen = r.length;
        best = r;
      }
    }
  }
  if (!best || best.length === 0) return null;
  let x = 0;
  let y = 0;
  for (const p of best) {
    x += p[0];
    y += p[1];
  }
  return [x / best.length, y / best.length];
}

/** Return the length of a line in kilometres. */
export function lineLengthKm(path: readonly LonLat[]): number {
  let d = 0;
  for (let i = 1; i < path.length; i++) d += haversineKm(path[i - 1], path[i]);
  return d;
}

/** Return the great-circle distance between two points in kilometres. */
export function haversineKm(a: LonLat, b: LonLat): number {
  const R = 6371;
  const toRad = Math.PI / 180;
  const dLat = (b[1] - a[1]) * toRad;
  const dLon = (b[0] - a[0]) * toRad;
  const s = Math.sin(dLat / 2) ** 2 + Math.cos(a[1] * toRad) * Math.cos(b[1] * toRad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(s)));
}

/** Return the midpoint vertex of a line. */
export function lineMid(path: readonly LonLat[]): LonLat | null {
  if (path.length === 0) return null;
  return path[Math.floor(path.length / 2)];
}
