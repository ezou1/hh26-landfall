import type { ArtifactMetadata, RerunStart, RerunStatus } from "./types";

/** Convert an ISO time to the advisory key YYYYMMDDHH. */
export function advKey(iso: string): string {
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}${p(d.getUTCMonth() + 1)}${p(d.getUTCDate())}${p(d.getUTCHours())}`;
}

/** The URL builders for each artifact. */
export const paths = {
  meta: () => "/api/meta",
  truth: () => "/out/truth.json",
  zones: () => "/out/static/zones.geojson",
  shelters: () => "/out/static/shelters.json",
  hospitals: () => "/out/static/hospitals.json",
  depots: () => "/out/static/depots.json",
  assets: () => "/out/static/assets.json",
  roads: () => "/out/roads.geojson",
  verify: () => "/out/verify/summary.json",
  ensemble: (adv: string) => `/out/stage1/${advKey(adv)}/ensemble.json`,
  cone: (adv: string) => `/out/stage1/${advKey(adv)}/cone.geojson`,
  landfall: (adv: string) => `/out/stage1/${advKey(adv)}/landfall.json`,
  scenarios: (adv: string) => `/out/stage1/${advKey(adv)}/scenarios.json`,
  wind: (adv: string, id: number) => `/out/impact/${advKey(adv)}/s${id}/wind.json`,
  surge: (adv: string, id: number) => `/out/impact/${advKey(adv)}/s${id}/surge.geojson`,
  firstStage: (adv: string) => `/out/plan/${advKey(adv)}/first_stage.json`,
  aggregate: (adv: string) => `/out/plan/${advKey(adv)}/aggregate.json`,
  baseline: (adv: string) => `/out/plan/${advKey(adv)}/baseline.json`,
  comparison: (adv: string) => `/out/plan/${advKey(adv)}/comparison.json`,
  infrastructure: (adv: string) => `/out/plan/${advKey(adv)}/infrastructure.json`,
  scenarioPlan: (adv: string, id: number) => `/out/plan/${advKey(adv)}/s${id}.json`,
  scenarioCzml: (adv: string, id: number) => `/out/plan/${advKey(adv)}/s${id}.czml`,
};

type FallbackListener = (url: string, items: string[]) => void;
const fallbackListeners: FallbackListener[] = [];
const cache = new Map<string, Promise<unknown>>();

/** Register a function that receives each artifact that has used_fallback=true. */
export function onFallback(fn: FallbackListener): void {
  fallbackListeners.push(fn);
}

function checkMetadata(url: string, body: unknown): void {
  if (body === null || typeof body !== "object" || Array.isArray(body)) return;
  const md = (body as { metadata?: ArtifactMetadata }).metadata;
  if (md && md.used_fallback === true) {
    const items = Array.isArray(md.fallback_items) ? md.fallback_items : [];
    for (const fn of fallbackListeners) fn(url, items);
  }
}

/** Fetch a JSON artifact once and keep it in the cache. Return null if the file does not exist. */
export function fetchJson<T>(url: string): Promise<T | null> {
  const hit = cache.get(url);
  if (hit) return hit as Promise<T | null>;
  const p = fetch(url)
    .then(async (res) => {
      if (!res.ok) return null;
      const text = await res.text();
      let body: T;
      try {
        body = JSON.parse(text) as T;
      } catch {
        // The backend can write NaN or Infinity. Change them to null.
        body = JSON.parse(text.replace(/\b(NaN|-?Infinity)\b/g, "null")) as T;
      }
      checkMetadata(url, body);
      return body;
    })
    .catch((err: unknown) => {
      console.warn(`fetch failed: ${url}`, err);
      cache.delete(url);
      return null;
    });
  cache.set(url, p);
  return p;
}

/** Check if a file exists on the server. */
export async function exists(url: string): Promise<boolean> {
  try {
    const res = await fetch(url, { method: "HEAD" });
    if (res.ok) return true;
    if (res.status === 405) {
      const get = await fetch(url);
      return get.ok;
    }
    return false;
  } catch {
    return false;
  }
}

/** Remove all cached artifacts. */
export function clearCache(): void {
  cache.clear();
}

/** Start a re-plan job on the backend. */
export async function startRerun(advisory: string, full: boolean): Promise<RerunStart | null> {
  try {
    const res = await fetch(`/api/rerun?advisory=${advKey(advisory)}&full=${full ? 1 : 0}`, { method: "POST" });
    if (!res.ok) return null;
    return (await res.json()) as RerunStart;
  } catch {
    return null;
  }
}

/** Get the status of a re-plan job. */
export async function rerunStatus(jobId: string): Promise<RerunStatus | null> {
  try {
    const res = await fetch(`/api/rerun/${encodeURIComponent(jobId)}`);
    if (!res.ok) return null;
    return (await res.json()) as RerunStatus;
  } catch {
    return null;
  }
}
