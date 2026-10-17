import type { TrackFix, Waypoint } from "../api/types";
import { ms } from "../time";

/** The state of the storm at one time. */
export interface StormState {
  lon: number;
  lat: number;
  vmax: number;
  rmaxKm: number;
}

const timesCache = new WeakMap<object, number[]>();

function timesOf<T extends { t: string }>(list: T[]): number[] {
  let t = timesCache.get(list);
  if (!t) {
    t = list.map((x) => ms(x.t));
    timesCache.set(list, t);
  }
  return t;
}

/** Return the index i so that times[i] <= tMs < times[i + 1], or -1 if tMs is before the first time. */
export function bracket(times: number[], tMs: number): number {
  let lo = 0;
  let hi = times.length - 1;
  if (hi < 0 || tMs < times[0]) return -1;
  if (tMs >= times[hi]) return hi;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (times[mid] <= tMs) lo = mid;
    else hi = mid;
  }
  return lo;
}

/** Interpolate a storm track at a time. Return null outside the track. */
export function stormAt(track: TrackFix[] | null | undefined, tMs: number): StormState | null {
  if (!track || track.length === 0) return null;
  const times = timesOf(track);
  const i = bracket(times, tMs);
  if (i < 0) return null;
  const a = track[i];
  if (i === track.length - 1) {
    if (tMs - times[i] > 3_600_000) return null;
    return { lon: a.lon, lat: a.lat, vmax: a.vmax_kt, rmaxKm: a.rmax_km ?? 40 };
  }
  const b = track[i + 1];
  const f = (tMs - times[i]) / Math.max(1, times[i + 1] - times[i]);
  const lerp = (x: number, y: number) => x + (y - x) * f;
  return {
    lon: lerp(a.lon, b.lon),
    lat: lerp(a.lat, b.lat),
    vmax: lerp(a.vmax_kt, b.vmax_kt),
    rmaxKm: lerp(a.rmax_km ?? 40, b.rmax_km ?? 40),
  };
}

/** The position of a moving unit at one time and the index of its current segment. */
export interface WaypointState {
  lon: number;
  lat: number;
  index: number;
  before: boolean;
  after: boolean;
}

/** Interpolate a list of waypoints at a time. */
export function waypointAt(wps: Waypoint[] | null | undefined, tMs: number): WaypointState | null {
  if (!wps || wps.length === 0) return null;
  const times = timesOf(wps);
  const i = bracket(times, tMs);
  if (i < 0) return { lon: wps[0].lon, lat: wps[0].lat, index: -1, before: true, after: false };
  if (i === wps.length - 1) return { lon: wps[i].lon, lat: wps[i].lat, index: i, before: false, after: true };
  const a = wps[i];
  const b = wps[i + 1];
  const f = (tMs - times[i]) / Math.max(1, times[i + 1] - times[i]);
  return { lon: a.lon + (b.lon - a.lon) * f, lat: a.lat + (b.lat - a.lat) * f, index: i, before: false, after: false };
}

/** Return the task that an asset works on at a time, or null. */
export function currentTaskId(wps: Waypoint[] | null | undefined, tMs: number): string | null {
  if (!wps || wps.length === 0) return null;
  const times = timesOf(wps);
  const i = bracket(times, tMs);
  if (i < 0 || i >= wps.length - 1) return null;
  return wps[i + 1].task_id ?? wps[i].task_id ?? null;
}
