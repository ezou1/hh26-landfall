import {
  BoundingSphere,
  Cartesian3,
  ClockRange,
  ClockStep,
  Color,
  Ellipsoid,
  HeadingPitchRange,
  JulianDate,
  Math as CMath,
  Matrix4,
  PolylineCollection,
  Material,
  type Viewer,
} from "cesium";
import { advisoryAt, requestAdvisory } from "../state/data";
import { useStore, type Speed } from "../state/store";
import { CzmlManager } from "./czml";
import { DebrisLayer } from "./layers/debris";
import { EvacLayer } from "./layers/evac";
import { HospitalsLayer } from "./layers/hospitals";
import { InfraLayer } from "./layers/infra";
import { RoadsLayer } from "./layers/roads";
import { SarLayer } from "./layers/sar";
import { SheltersLayer } from "./layers/shelters";
import { StormLayer } from "./layers/storm";
import { SupplyLayer } from "./layers/supply";
import { SurgeLayer } from "./layers/surge";
import type { GlobeLayer, ScenarioFrame } from "./layers/types";
import { WindLayer } from "./layers/wind";
import { ZonesLayer } from "./layers/zones";

/** One hour of replay for each 0.5 s of real time, at speed 1. */
export const BASE_MULTIPLIER = 7200;

let viewer: Viewer | null = null;
let czml: CzmlManager | null = null;
const storm = new StormLayer();
const layers: GlobeLayer[] = [
  new SurgeLayer(),
  new ZonesLayer(),
  new WindLayer(),
  storm,
  new RoadsLayer(),
  new DebrisLayer(),
  new EvacLayer(),
  new InfraLayer(),
  new SheltersLayer(),
  new HospitalsLayer(),
  new SupplyLayer(),
  new SarLayer(),
];
let lastHour = Number.NaN;
let lastFollow = 0;
let lastStoreUpdate = 0;
let tickCount = 0;

/** Return the count of clock ticks since the start. Tests use it to wait for new frames. */
export function getTickCount(): number {
  return tickCount;
}
let clockReady = false;
let unsub: (() => void) | null = null;

/** Return the Cesium viewer, or null before the globe starts. */
export function getViewer(): Viewer | null {
  return viewer && !viewer.isDestroyed() ? viewer : null;
}

function configureClock(v: Viewer): void {
  const s = useStore.getState();
  if (!s.meta || clockReady) return;
  const start = JulianDate.fromIso8601(s.meta.t0);
  const stop = JulianDate.fromIso8601(s.meta.t_end);
  v.clock.startTime = start.clone();
  v.clock.stopTime = stop.clone();
  v.clock.currentTime = start.clone();
  v.clock.clockRange = ClockRange.CLAMPED;
  v.clock.clockStep = ClockStep.SYSTEM_CLOCK_MULTIPLIER;
  v.clock.multiplier = BASE_MULTIPLIER * s.speed;
  v.clock.shouldAnimate = false;
  clockReady = true;
  addCountyOutline(v);
  home(0);
}

function addCountyOutline(v: Viewer): void {
  const bbox = useStore.getState().meta?.county?.bbox;
  if (!bbox) return;
  const [w, s, e, n] = bbox;
  const coll = new PolylineCollection();
  coll.add({
    positions: Cartesian3.fromDegreesArrayHeights([w, s, 10, e, s, 10, e, n, 10, w, n, 10, w, s, 10]),
    width: 1.5,
    material: Material.fromType("PolylineDash", { color: Color.fromCssColorString("#4fc3f7").withAlpha(0.7), dashLength: 16 }),
  });
  v.scene.primitives.add(coll);
}

function onTick(): void {
  const v = getViewer();
  if (!v) return;
  tickCount++;
  configureClock(v);
  const st = useStore.getState();
  if (!st.meta) return;
  const time = v.clock.currentTime;
  const tMs = JulianDate.toDate(time).getTime();
  const hourF = (tMs - st.t0Ms) / 3_600_000;
  const hour = Math.max(0, Math.min(st.meta.hours ?? 120, Math.floor(hourF + 1e-6)));
  if (hour !== lastHour) {
    lastHour = hour;
    requestAdvisory(advisoryAt(st.meta.advisories, tMs));
  }
  // Limit the React updates to about 4 Hz during the replay.
  const now = performance.now();
  if (hour !== st.hour && (!v.clock.shouldAnimate || now - lastStoreUpdate > 250)) {
    lastStoreUpdate = now;
    st.set({ hour });
  }
  czml?.update(st.planScenario?.czmlUrl ?? null, st.layers);
  const frame: ScenarioFrame = { tMs, hourF, hour, state: useStore.getState(), czml: czml?.source ?? null };
  for (const l of layers) {
    try {
      l.update(time, frame);
    } catch (err) {
      console.error(`layer ${l.id} update failed`, err);
    }
  }
  if (st.playing && JulianDate.greaterThanOrEquals(time, v.clock.stopTime)) {
    v.clock.shouldAnimate = false;
    st.set({ playing: false });
  }
  if (st.followStorm) followStorm(v);
}

function followStorm(v: Viewer): void {
  const now = performance.now();
  if (now - lastFollow < 100) return;
  lastFollow = now;
  const s = storm.current();
  if (!s) return;
  const target = Cartesian3.fromDegrees(s.lon, s.lat, 0);
  const range = 900_000;
  v.camera.lookAt(target, new HeadingPitchRange(v.camera.heading, CMath.toRadians(-55), range));
  v.camera.lookAtTransform(Matrix4.IDENTITY);
}

/** Attach the layers and the clock to a new viewer. */
export function attachViewer(v: Viewer): void {
  if (viewer === v) return;
  viewer = v;
  clockReady = false;
  lastHour = Number.NaN;
  czml = new CzmlManager(v);
  for (const l of layers) l.init(v);
  const vis = useStore.getState().layers;
  for (const l of layers) l.setVisible(vis[l.id]);
  unsub?.();
  unsub = useStore.subscribe((s, prev) => {
    if (s.layers !== prev.layers) for (const l of layers) l.setVisible(s.layers[l.id]);
    if (s.followStorm !== prev.followStorm && !s.followStorm) v.camera.lookAtTransform(Matrix4.IDENTITY);
  });
  v.clock.onTick.addEventListener(onTick);
}

/** Set the clock to an hour since T0. The value can have a fraction. */
export function setHour(h: number): void {
  const v = getViewer();
  const s = useStore.getState();
  if (!v || !s.meta) return;
  const max = s.meta.hours ?? 120;
  const clamped = Math.max(0, Math.min(max, h));
  v.clock.currentTime = JulianDate.addSeconds(JulianDate.fromIso8601(s.meta.t0), clamped * 3600, new JulianDate());
}

/** Return the clock time as hours since T0, with a fraction. */
export function getHourF(): number {
  const v = getViewer();
  const s = useStore.getState();
  if (!v || !s.meta) return 0;
  return (JulianDate.toDate(v.clock.currentTime).getTime() - s.t0Ms) / 3_600_000;
}

/** Start the replay. */
export function play(): void {
  const v = getViewer();
  if (!v) return;
  if (JulianDate.greaterThanOrEquals(v.clock.currentTime, v.clock.stopTime)) v.clock.currentTime = v.clock.startTime.clone();
  v.clock.shouldAnimate = true;
  useStore.getState().set({ playing: true });
}

/** Stop the replay. */
export function pause(): void {
  const v = getViewer();
  if (v) v.clock.shouldAnimate = false;
  useStore.getState().set({ playing: false });
}

/** Set the replay speed. */
export function setSpeed(speed: Speed): void {
  const v = getViewer();
  if (v) v.clock.multiplier = BASE_MULTIPLIER * speed;
  useStore.getState().set({ speed });
}

/** Fly the camera to the home view from meta.json. */
export function home(duration = 1.5): void {
  const v = getViewer();
  const cam = useStore.getState().meta?.home_camera;
  if (!v) return;
  const c = cam ?? { lon: -82.25, lat: 26.05, height_m: 60000, heading_deg: 35, pitch_deg: -35 };
  useStore.getState().set({ followStorm: false });
  v.camera.flyTo({
    destination: Cartesian3.fromDegrees(c.lon, c.lat, c.height_m),
    orientation: { heading: CMath.toRadians(c.heading_deg), pitch: CMath.toRadians(c.pitch_deg), roll: 0 },
    duration,
  });
}

/** Fly the camera to a point. */
export function flyToPoint(lon: number, lat: number, range = 12_000): void {
  const v = getViewer();
  if (!v || !Number.isFinite(lon) || !Number.isFinite(lat)) return;
  useStore.getState().set({ followStorm: false });
  const center = Cartesian3.fromDegrees(lon, lat, 0);
  v.camera.flyToBoundingSphere(new BoundingSphere(center, 200), {
    offset: new HeadingPitchRange(CMath.toRadians(20), CMath.toRadians(-50), range),
    duration: 1.2,
  });
}

/** Fly the camera to a line given as [lon, lat] points. */
export function flyToPath(path: [number, number][]): void {
  const v = getViewer();
  if (!v || path.length === 0) return;
  const pts = path.map((p) => Cartesian3.fromDegrees(p[0], p[1], 0));
  const bs = BoundingSphere.fromPoints(pts);
  useStore.getState().set({ followStorm: false });
  v.camera.flyToBoundingSphere(bs, {
    offset: new HeadingPitchRange(CMath.toRadians(20), CMath.toRadians(-55), Math.max(6000, bs.radius * 3.2)),
    duration: 1.2,
  });
}

/** Return the position of a CZML entity at the clock time as [lon, lat], or null. */
export function entityLonLat(id: string): [number, number] | null {
  const v = getViewer();
  const ent = czml?.source?.entities.getById(id);
  if (!v || !ent?.position) return null;
  const p = ent.position.getValue(v.clock.currentTime);
  if (!p) return null;
  const c = Ellipsoid.WGS84.cartesianToCartographic(p);
  if (!c) return null;
  return [CMath.toDegrees(c.longitude), CMath.toDegrees(c.latitude)];
}

/** Fly to a CZML entity. Return false if the entity has no position at the clock time. */
export function flyToEntity(id: string): boolean {
  const ll = entityLonLat(id);
  if (!ll) return false;
  flyToPoint(ll[0], ll[1], 9000);
  return true;
}

/** Return the storm state at the clock time, or null. */
export function stormNow() {
  return storm.current();
}
