import type { Asset, SarAsset, SarTask, ScenarioPlan, WindField, ZonePlan } from "../api/types";
import { currentTaskId, waypointAt } from "../globe/track";
import { haversineKm } from "../globe/geo";
import { ms } from "../time";

export type ZoneStatus = "none" | "ordered" | "late";

/** Return the release status of a zone at a time. */
export function zoneStatus(z: ZonePlan | undefined, tMs: number, releaseFallback?: string | null): ZoneStatus {
  const release = ms(z?.release_time ?? releaseFallback ?? null);
  if (!Number.isFinite(release) || tMs < release) return "none";
  if (!z) return "ordered";
  const ts = ms(z.ts_arrival);
  const clear = ms(z.clearance_time);
  const late =
    (z.margin_h !== null && z.margin_h !== undefined && z.margin_h < 0) ||
    (Number.isFinite(ts) && (!Number.isFinite(clear) || clear > ts));
  return late ? "late" : "ordered";
}

/** Return the earliest arrival time of tropical-storm winds over all zones, in milliseconds. */
export function earliestTsArrival(plan: ScenarioPlan | null | undefined): number {
  let best = Number.POSITIVE_INFINITY;
  for (const z of plan?.zones ?? []) {
    const v = ms(z.ts_arrival);
    if (Number.isFinite(v) && v < best) best = v;
  }
  return best;
}

export type TaskStatus = "future" | "waiting" | "assigned" | "served";

/** Return, for each task, the time when its asset starts to travel to it. */
export function taskAssignTimes(assets: SarAsset[] | null | undefined): Map<string, number> {
  const out = new Map<string, number>();
  for (const a of assets ?? []) {
    const wps = a.waypoints ?? [];
    for (let i = 0; i < wps.length; i++) {
      const id = wps[i].task_id;
      if (!id || out.has(id)) continue;
      const prev = i > 0 ? wps[i - 1].t : wps[i].t;
      out.set(id, ms(prev));
    }
  }
  return out;
}

/** Return the status of a rescue task at a time. */
export function taskStatus(task: SarTask, assign: Map<string, number>, tMs: number): TaskStatus {
  const created = ms(task.created_t);
  if (Number.isFinite(created) && tMs < created) return "future";
  const served = ms(task.served_t);
  if (Number.isFinite(served) && tMs >= served) return "served";
  const a = assign.get(task.id);
  if (task.asset_id && a !== undefined && Number.isFinite(a) && tMs >= a) return "assigned";
  return "waiting";
}

export type AssetStatus = "standby" | "enRoute" | "atBase" | "done";

/** The state of a rescue asset at a time. */
export interface AssetState {
  status: AssetStatus;
  taskId: string | null;
  enduranceLeftH: number | null;
  lon: number | null;
  lat: number | null;
}

/** Return the state of a rescue asset at a time. */
export function assetState(a: SarAsset, base: Asset | undefined, tMs: number): AssetState {
  const wps = a.waypoints ?? [];
  const pos = waypointAt(wps, tMs);
  const taskId = currentTaskId(wps, tMs);
  if (!pos) return { status: "standby", taskId: null, enduranceLeftH: a.endurance_h ?? null, lon: null, lat: null };
  const baseLL: [number, number] = base
    ? [base.base_lon, base.base_lat]
    : wps.length > 0
      ? [wps[0].lon, wps[0].lat]
      : [pos.lon, pos.lat];
  const atBase = haversineKm(baseLL, [pos.lon, pos.lat]) < 1.5;
  let status: AssetStatus = "enRoute";
  if (pos.before) status = "standby";
  else if (pos.after) status = "done";
  else if (atBase && !taskId) status = "atBase";
  // Endurance: the hours since the asset last left its base.
  let leftAt = Number.NaN;
  for (let i = 0; i < wps.length; i++) {
    const tw = ms(wps[i].t);
    if (tw > tMs) break;
    const here = haversineKm(baseLL, [wps[i].lon, wps[i].lat]) < 1.5;
    if (here) leftAt = tw;
  }
  let left: number | null = a.endurance_h ?? null;
  if (left !== null && !atBase && Number.isFinite(leftAt) && status === "enRoute") {
    left = Math.max(0, left - (tMs - leftAt) / 3_600_000);
  }
  return { status, taskId, enduranceLeftH: left, lon: pos.lon, lat: pos.lat };
}

/** Return the first wind time when the 34 kt ring touches the county box, in milliseconds. */
export function windEta(wind: WindField | null | undefined, bbox: number[] | undefined): number {
  if (!wind || !bbox) return Number.POSITIVE_INFINITY;
  const [w, s, e, n] = bbox;
  const rings = wind.rings?.["34"] ?? [];
  for (let i = 0; i < rings.length; i++) {
    const r = rings[i];
    if (!r) continue;
    let minX = Infinity,
      maxX = -Infinity,
      minY = Infinity,
      maxY = -Infinity;
    for (const p of r) {
      minX = Math.min(minX, p[0]);
      maxX = Math.max(maxX, p[0]);
      minY = Math.min(minY, p[1]);
      maxY = Math.max(maxY, p[1]);
    }
    if (maxX >= w && minX <= e && maxY >= s && minY <= n) return ms(wind.times?.[i] ?? null);
  }
  return Number.POSITIVE_INFINITY;
}
