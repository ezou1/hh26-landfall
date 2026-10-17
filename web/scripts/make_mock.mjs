// Write a small fake LANDFALL dataset to web/.mock/out/ that follows .dev/CONTRACT.md.
// Usage: node scripts/make_mock.mjs [outDir]
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(process.argv[2] ?? path.join(here, "..", ".mock", "out"));

// ---------- helpers ----------
let seed = 42;
function rnd() {
  seed |= 0;
  seed = (seed + 0x6d2b79f5) | 0;
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}
function gauss() {
  const u = Math.max(1e-9, rnd());
  const v = rnd();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}
const T0 = Date.parse("2022-09-25T00:00:00Z");
const HOURS = 120;
const iso = (h) => new Date(T0 + h * 3600_000).toISOString().replace(".000Z", "Z");
const advKey = (h) => {
  const d = new Date(T0 + h * 3600_000);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}${p(d.getUTCMonth() + 1)}${p(d.getUTCDate())}${p(d.getUTCHours())}`;
};
const r4 = (x) => Math.round(x * 1e4) / 1e4;
const r1 = (x) => Math.round(x * 10) / 10;
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const md = (fallback = false, items = []) => ({
  seed: 42,
  git_sha: "mock000",
  created_utc: "2026-10-17T00:00:00Z",
  used_fallback: fallback,
  fallback_items: items,
});
function write(rel, obj) {
  const f = path.join(OUT, rel);
  fs.mkdirSync(path.dirname(f), { recursive: true });
  fs.writeFileSync(f, JSON.stringify(obj));
}
function kmToDeg(km, lat) {
  return { dLat: km / 111.0, dLon: km / (111.0 * Math.cos((lat * Math.PI) / 180)) };
}
function distKm(a, b) {
  const R = 6371;
  const toR = Math.PI / 180;
  const dLat = (b[1] - a[1]) * toR;
  const dLon = (b[0] - a[0]) * toR;
  const s = Math.sin(dLat / 2) ** 2 + Math.cos(a[1] * toR) * Math.cos(b[1] * toR) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}

// ---------- truth track ----------
// [hour, lat, lon, vmax_kt, pmin_mb, rmax_km]
const KEY = [
  [0, 15.4, -79.2, 40, 1002, 60],
  [12, 16.3, -80.5, 50, 997, 50],
  [24, 17.6, -81.6, 65, 987, 40],
  [36, 19.4, -82.6, 80, 976, 30],
  [48, 20.9, -83.2, 95, 966, 25],
  [56, 22.2, -83.6, 110, 952, 20],
  [66, 23.6, -83.4, 100, 956, 22],
  [72, 24.3, -83.1, 105, 952, 22],
  [84, 25.7, -82.6, 135, 937, 25],
  [91.08, 26.6, -82.2, 130, 941, 28],
  [96, 27.0, -81.9, 100, 955, 35],
  [108, 28.1, -81.3, 60, 980, 60],
  [120, 29.3, -80.4, 55, 985, 80],
  [132, 30.8, -79.8, 60, 984, 90],
  [150, 33.0, -79.4, 65, 980, 90],
  [170, 35.0, -79.6, 35, 995, 120],
];
function truthAt(h) {
  let i = 0;
  while (i < KEY.length - 2 && KEY[i + 1][0] <= h) i++;
  const a = KEY[i];
  const b = KEY[i + 1];
  const f = (h - a[0]) / (b[0] - a[0]);
  const L = (k) => a[k] + (b[k] - a[k]) * f;
  return { lat: L(1), lon: L(2), vmax: L(3), pmin: L(4), rmax: L(5) };
}

const ADVISORIES = [0, 24, 48, 72];
const PLAN_ADV = 48;
const SPREAD = { 0: 1.0, 24: 0.8, 48: 0.55, 72: 0.28 };
// Scenario offsets: west-east degrees per day after the advisory, and an intensity change.
const SCEN = [
  { id: 0, label: "OFCL", p: 0.35, lonPerDay: -0.22, dv: 0, ofcl: true },
  { id: 1, label: "S01", p: 0.27, lonPerDay: 0.12, dv: -8 },
  { id: 2, label: "S02", p: 0.23, lonPerDay: -0.04, dv: 14 },
  { id: 3, label: "S03", p: 0.15, lonPerDay: -0.55, dv: -5 },
];

function scenarioAt(sc, hAdv, h) {
  const tr = truthAt(h);
  const dh = Math.max(0, h - hAdv);
  const k = SPREAD[hAdv];
  // The forecast slows down a little for western tracks.
  const lon = tr.lon + sc.lonPerDay * k * (dh / 24) * 1.4;
  const lat = tr.lat - Math.abs(sc.lonPerDay) * k * (dh / 24) * 0.25;
  const landF = lat > 26.5 + (-82.2 - lon) * 1.2 ? 1 : 0;
  const vmax = clamp(tr.vmax + sc.dv * Math.min(1, dh / 36) * (landF ? 0.5 : 1), 20, 160);
  return { lat, lon, vmax, pmin: tr.pmin - (vmax - tr.vmax) * 0.8, rmax: tr.rmax };
}
function coastLat(lon) {
  return 26.6 + (-82.2 - lon) * 1.2;
}
function landfallOf(track) {
  for (let i = 1; i < track.length; i++) {
    const a = track[i - 1];
    const b = track[i];
    if (a.lat < coastLat(a.lon) && b.lat >= coastLat(b.lon)) return { i, fix: b };
  }
  return null;
}
function catOf(v) {
  if (v >= 137) return "5";
  if (v >= 113) return "4";
  if (v >= 96) return "3";
  if (v >= 83) return "2";
  if (v >= 64) return "1";
  return "TS";
}

// ---------- geography ----------
const BBOX = [-82.4, 26.3, -81.55, 26.85];
const COAST = [
  [-82.27, 26.82],
  [-82.24, 26.7],
  [-82.2, 26.56],
  [-82.13, 26.48],
  [-82.03, 26.44],
  [-81.96, 26.445],
  [-81.9, 26.4],
  [-81.85, 26.32],
];
function shiftedCoast(dLon) {
  return COAST.map(([x, y]) => [r4(x + dLon), y]);
}
function band(a, b) {
  const left = shiftedCoast(a);
  const right = shiftedCoast(b).reverse();
  const ring = [...left, ...right, left[0]];
  return ring;
}

const zonesFc = {
  type: "FeatureCollection",
  metadata: md(true, ["zones"]),
  features: [
    ["A", -0.02, 0.03, 61000],
    ["B", 0.03, 0.08, 94000],
    ["C", 0.08, 0.14, 128000],
    ["D", 0.14, 0.22, 151000],
    ["E", 0.22, 0.32, 166000],
  ].map(([zone, a, b, population]) => ({
    type: "Feature",
    properties: { zone, population },
    geometry: { type: "Polygon", coordinates: [band(a, b)] },
  })),
};

const shelters = [
  ["sh01", "Hertz Arena", 26.429, -81.809, 4000, false],
  ["sh02", "South Fort Myers HS", 26.535, -81.857, 2200, false],
  ["sh03", "Island Coast HS", 26.65, -81.99, 1800, false],
  ["sh04", "Estero Rec Center", 26.43, -81.775, 1200, false],
  ["sh05", "Lehigh Acres MS", 26.61, -81.64, 1600, false],
  ["sh06", "North Fort Myers Rec", 26.72, -81.87, 1400, false],
  ["sh07", "Harns Marsh MS", 26.64, -81.69, 1500, true],
  ["sh08", "Riverdale HS", 26.66, -81.77, 2000, false],
].map(([id, name, lat, lon, capacity, is_special_needs]) => ({ id, name, lat, lon, capacity, is_special_needs }));

const hospitals = [
  ["h01", "Lee Memorial", 26.627, -81.873, 415, true, 2],
  ["h02", "HealthPark", 26.507, -81.888, 368, true, 2],
  ["h03", "Gulf Coast Medical", 26.548, -81.791, 349, true, 3],
  ["h04", "Cape Coral Hospital", 26.591, -81.975, 291, false, null],
].map(([id, name, lat, lon, beds, has_helipad, trauma_level]) => ({ id, name, lat, lon, beds, has_helipad, trauma_level }));

const COMMODITIES = [
  { id: "water", unit: "L", kg_per_unit: 1.0 },
  { id: "food", unit: "meal", kg_per_unit: 0.5 },
  { id: "med_kits", unit: "kit", kg_per_unit: 2.0 },
  { id: "fuel", unit: "L", kg_per_unit: 0.85 },
  { id: "generators", unit: "unit", kg_per_unit: 90 },
];
const depots = [
  ["d01", "State LSA Fort Myers", "state", 26.59, -81.75, 14],
  ["d02", "County EOC Depot", "county", 26.62, -81.82, 8],
  ["d03", "Retail DC Estero", "retail", 26.44, -81.78, 6],
].map(([id, name, kind, lat, lon, trucks]) => ({
  id,
  name,
  kind,
  lat,
  lon,
  trucks,
  inventory: { water: 400000, food: 150000, med_kits: 3000, fuel: 60000, generators: 40 },
}));

const assets = [
  ["a01", "helo", "LCSO Air 1", 26.536, -81.755, 220, 4, 3.5],
  ["a02", "helo", "USCG 6512", 26.536, -81.755, 250, 6, 4],
  ["a03", "boat", "FMB Fire Boat", 26.46, -81.95, 35, 8, 10],
  ["a04", "boat", "Cape Coral Marine 2", 26.56, -81.95, 35, 6, 10],
  ["a05", "high_water_truck", "HWT 1", 26.62, -81.82, 40, 12, 12],
  ["a06", "high_water_truck", "HWT 2", 26.59, -81.75, 40, 12, 12],
].map(([id, kind, name, base_lat, base_lon, speed_kmh, capacity_persons, endurance_h]) => ({
  id,
  kind,
  name,
  base_lat,
  base_lon,
  speed_kmh,
  capacity_persons,
  endurance_h,
}));

// ---------- roads ----------
const roads = [];
let node = 1;
function addRoad(name, highway, lanes, coords, crit = null, bridge = false) {
  for (let i = 1; i < coords.length; i++) {
    const u = node++;
    const v = node;
    roads.push({
      type: "Feature",
      properties: {
        edge_id: `${u}-${v}-0`,
        name,
        highway,
        lanes,
        is_critical: !!crit,
        critical_name: crit,
        is_bridge: bridge,
      },
      geometry: { type: "LineString", coordinates: [coords[i - 1].map(r4), coords[i].map(r4)] },
    });
  }
  node++;
}
function line(a, b, n) {
  const out = [];
  for (let i = 0; i <= n; i++) out.push([a[0] + ((b[0] - a[0]) * i) / n, a[1] + ((b[1] - a[1]) * i) / n]);
  return out;
}
addRoad("I-75", "motorway", 3, line([-81.8, 26.33], [-81.79, 26.8], 12));
addRoad("US 41", "trunk", 3, line([-81.82, 26.33], [-81.87, 26.8], 12));
addRoad("Del Prado Blvd", "primary", 2, line([-81.94, 26.53], [-81.94, 26.72], 6));
addRoad("Chiquita Blvd", "secondary", 2, line([-82.0, 26.53], [-82.0, 26.7], 5));
addRoad("Ortiz Ave", "secondary", 2, line([-81.82, 26.6], [-81.8, 26.7], 3));
addRoad("SR 82", "primary", 2, line([-81.86, 26.64], [-81.6, 26.66], 7));
addRoad("Colonial Blvd", "primary", 3, line([-81.94, 26.6], [-81.7, 26.6], 7));
addRoad("Daniels Pkwy", "primary", 3, line([-81.88, 26.55], [-81.65, 26.55], 7));
addRoad("Alico Rd", "primary", 2, line([-81.86, 26.49], [-81.7, 26.49], 5));
addRoad("Corkscrew Rd", "secondary", 2, line([-81.81, 26.43], [-81.62, 26.43], 5));
addRoad("Bonita Beach Rd", "primary", 2, line([-81.87, 26.335], [-81.74, 26.335], 4));
addRoad("Cape Coral Pkwy", "primary", 2, line([-82.0, 26.565], [-81.93, 26.565], 3));
addRoad("Pine Island Rd", "primary", 2, line([-82.03, 26.63], [-81.87, 26.64], 5));
addRoad("Estero Blvd", "secondary", 2, line([-81.965, 26.47], [-81.88, 26.38], 5));
addRoad("Sanibel-Captiva Rd", "secondary", 2, line([-82.19, 26.49], [-82.03, 26.435], 5));
addRoad("Summerlin Rd", "primary", 2, line([-82.0, 26.49], [-81.88, 26.58], 5));
addRoad("Sanibel Causeway", "primary", 2, [[-82.0, 26.49], [-82.03, 26.47], [-82.04, 26.45]], "Sanibel Causeway", true);
addRoad("Matanzas Pass Bridge", "primary", 2, [[-81.955, 26.48], [-81.96, 26.465]], "Matanzas Pass Bridge", true);
addRoad("Matlacha Bridge", "primary", 2, [[-82.08, 26.63], [-82.03, 26.63]], "Matlacha Bridge", true);
addRoad("Cape Coral Bridge", "primary", 4, [[-81.93, 26.565], [-81.895, 26.555]], "Cape Coral Bridge", true);
addRoad("Midpoint Bridge", "primary", 4, [[-81.94, 26.6], [-81.9, 26.6]], "Midpoint Bridge", true);
addRoad("Pine Island", "secondary", 2, line([-82.11, 26.52], [-82.12, 26.7], 4));
const roadsFc = { type: "FeatureCollection", metadata: md(), features: roads };

// ---------- meta ----------
const meta = {
  metadata: md(),
  storm_id: "AL092022",
  storm_name: "IAN",
  t0: iso(0),
  t_end: iso(HOURS),
  hours: HOURS,
  county: { name: "Lee County, FL", fips: "12071", bbox: BBOX },
  advisories: ADVISORIES.map(iso),
  plan_advisories: [iso(PLAN_ADV)],
  default_plan_advisory: iso(PLAN_ADV),
  truth_landfall: { time: "2022-09-28T19:05:00Z", lat: 26.6, lon: -82.2, vmax_kt: 130 },
  home_camera: { lon: -82.25, lat: 26.05, height_m: 60000, heading_deg: 35, pitch_deg: -35 },
  assumptions: [
    { key: "EVAC_COMPLIANCE", value: 0.7, unit: "fraction", text: "Seven of ten persons in an ordered zone leave." },
    { key: "VEHICLES_PER_HOUSEHOLD", value: 1.3, unit: "vehicles", text: "Each household that leaves uses 1.3 vehicles." },
    { key: "LANE_CAPACITY_VPH", value: 1800, unit: "veh/h/lane", text: "One lane moves 1800 vehicles each hour at most." },
    { key: "SHELTER_SHARE", value: 0.15, unit: "fraction", text: "Fifteen percent of evacuees go to a public shelter." },
    { key: "RESCUE_RATE", value: 0.3, unit: "fraction", text: "Thirty percent of persons who stay in deep surge ask for rescue." },
    { key: "TREE_FALL_GUST_MPH", value: 75, unit: "mph", text: "Trees can block roads when gusts exceed 75 mph." },
  ],
  commodities: COMMODITIES,
};

// ---------- write static ----------
fs.rmSync(OUT, { recursive: true, force: true });
write("meta.json", meta);
write("static/zones.geojson", zonesFc);
write("static/shelters.json", shelters);
write("static/hospitals.json", hospitals);
write("static/depots.json", depots);
write("static/assets.json", assets);
write("roads.geojson", roadsFc);
write("truth.json", {
  metadata: md(),
  track: Array.from({ length: 21 }, (_v, i) => i * 6).map((h) => {
    const s = truthAt(h);
    return { t: iso(h), lat: r4(s.lat), lon: r4(s.lon), vmax_kt: Math.round(s.vmax), pmin_mb: Math.round(s.pmin) };
  }),
  carq: ADVISORIES.map((h) => {
    const s = truthAt(h);
    return { t: iso(h), lat: r4(s.lat), lon: r4(s.lon), vmax_kt: Math.round(s.vmax), pmin_mb: Math.round(s.pmin) };
  }),
});

// ---------- stage 1 ----------
const scenarioTracks = {};
for (const hAdv of ADVISORIES) {
  const k = SPREAD[hAdv];
  const key = advKey(hAdv);
  const times = Array.from({ length: 21 }, (_v, i) => hAdv + i * 6);
  const members = [];
  for (let m = 0; m < 200; m++) {
    const lonBias = gauss() * 0.32 * k;
    const tBias = gauss() * 3 * k;
    const vBias = gauss() * 12 * k;
    const life = rnd() < 0.08 ? 10 + Math.floor(rnd() * 8) : 21;
    const pts = [];
    for (let i = 0; i < life; i++) {
      const h = times[i];
      const dh = h - hAdv;
      const s = truthAt(Math.max(hAdv, h + (tBias * dh) / 48));
      pts.push([
        r4(s.lon + lonBias * (dh / 24) * 1.3 + gauss() * 0.02 * k),
        r4(s.lat - Math.abs(lonBias) * (dh / 24) * 0.15),
        Math.round(clamp(s.vmax + (vBias * dh) / 48, 15, 170)),
      ]);
    }
    members.push(pts);
  }
  const mean = times.map((_h, i) => {
    const pts = members.filter((m) => m.length > i).map((m) => m[i]);
    const avg = (j) => pts.reduce((a, p) => a + p[j], 0) / pts.length;
    return [r4(avg(0)), r4(avg(1)), Math.round(avg(2))];
  });
  const ofclSc = SCEN[0];
  write(`stage1/${key}/ensemble.json`, {
    metadata: md(),
    advisory_time: iso(hAdv),
    n_members: 1000,
    times: times.map(iso),
    members,
    mean,
    ofcl: times.map((h) => {
      const s = scenarioAt(ofclSc, hAdv, h);
      return { t: iso(h), lat: r4(s.lat), lon: r4(s.lon), vmax_kt: Math.round(s.vmax) };
    }),
    observed: Array.from({ length: hAdv / 6 + 1 }, (_v, i) => i * 6).map((h) => {
      const s = truthAt(h);
      return { t: iso(h), lat: r4(s.lat), lon: r4(s.lon), vmax_kt: Math.round(s.vmax) };
    }),
  });
  // Cone: a buffer around the mean track that grows with lead time.
  const coneFeat = (level, f) => {
    const left = [];
    const right = [];
    mean.forEach((p, i) => {
      const prev = mean[Math.max(0, i - 1)];
      const next = mean[Math.min(mean.length - 1, i + 1)];
      const dx = next[0] - prev[0];
      const dy = next[1] - prev[1];
      const n = Math.hypot(dx, dy) || 1;
      const lead = i * 6;
      const rKm = f * (15 + 55 * (lead / 24)) * (0.4 + 0.6 * k);
      const { dLat, dLon } = kmToDeg(rKm, p[1]);
      left.push([r4(p[0] - (dy / n) * dLon), r4(p[1] + (dx / n) * dLat)]);
      right.push([r4(p[0] + (dy / n) * dLon), r4(p[1] - (dx / n) * dLat)]);
    });
    const ring = [...left, ...right.reverse()];
    ring.push(ring[0]);
    return { type: "Feature", properties: { level }, geometry: { type: "Polygon", coordinates: [ring] } };
  };
  write(`stage1/${key}/cone.geojson`, {
    type: "FeatureCollection",
    metadata: md(),
    features: [coneFeat("p90", 1.6), coneFeat("p66", 1.0), coneFeat("p50", 0.65)],
  });
  const scen = SCEN.map((sc) => {
    const track = [];
    for (let h = 0; h <= HOURS; h++) {
      const s = scenarioAt(sc, hAdv, h);
      track.push({
        t: iso(h),
        lat: r4(s.lat),
        lon: r4(s.lon),
        vmax_kt: Math.round(s.vmax),
        pmin_mb: Math.round(s.pmin),
        rmax_km: Math.round(s.rmax),
      });
    }
    const lf = landfallOf(track);
    return {
      id: sc.id,
      label: sc.label,
      probability: sc.p,
      is_ofcl: !!sc.ofcl,
      is_worst: hAdv === PLAN_ADV && sc.id === 2,
      landfall_time: lf ? track[lf.i].t : null,
      landfall_lon: lf ? lf.fix.lon : null,
      landfall_lat: lf ? lf.fix.lat : null,
      category: lf ? catOf(lf.fix.vmax_kt) : null,
      track,
    };
  });
  scenarioTracks[hAdv] = scen;
  write(`stage1/${key}/scenarios.json`, { metadata: md(), advisory_time: iso(hAdv), scenarios: scen });
  const pLf = { 0: 0.31, 24: 0.48, 48: 0.72, 72: 0.94 }[hAdv];
  const lfH = 91 + (hAdv < 48 ? 4 : 1);
  const sp = 10 * k;
  write(`stage1/${key}/landfall.json`, {
    metadata: md(),
    advisory_time: iso(hAdv),
    p_landfall_county: pLf,
    landfall_time_p10: iso(Math.round(lfH - sp)),
    landfall_time_p50: iso(lfH),
    landfall_time_p90: iso(Math.round(lfH + sp * 1.3)),
    category_dist:
      hAdv < 48
        ? { TS: 0.12, 1: 0.15, 2: 0.22, 3: 0.25, 4: 0.2, 5: 0.06 }
        : { TS: 0.03, 1: 0.05, 2: 0.12, 3: 0.25, 4: 0.45, 5: 0.1 },
  });
}

// ---------- impact and plan (plan advisory, scenarios 0..2) ----------
const planKey = advKey(PLAN_ADV);
const PLAN_SCEN = [0, 1, 2];
const RELEASE = { A: 50, B: 55, C: 61, D: 68, E: null };
const CLEAR_DUR = { A: 13, B: 17, C: 21, D: 24, E: 26 };

function ringAround(lon, lat, rKm, skew) {
  const out = [];
  for (let i = 0; i < 72; i++) {
    const a = (i / 72) * Math.PI * 2;
    const r = rKm * (1 + skew * Math.cos(a - Math.PI / 4));
    const { dLat, dLon } = kmToDeg(r, lat);
    out.push([r4(lon + Math.cos(a) * dLon), r4(lat + Math.sin(a) * dLat)]);
  }
  out.push(out[0]);
  return out;
}
function along(pathPts, f) {
  const segs = [];
  let tot = 0;
  for (let i = 1; i < pathPts.length; i++) {
    const d = distKm(pathPts[i - 1], pathPts[i]);
    segs.push(d);
    tot += d;
  }
  let goal = f * tot;
  for (let i = 0; i < segs.length; i++) {
    if (goal <= segs[i] || i === segs.length - 1) {
      const g = segs[i] > 0 ? clamp(goal / segs[i], 0, 1) : 0;
      const a = pathPts[i];
      const b = pathPts[i + 1];
      return [a[0] + (b[0] - a[0]) * g, a[1] + (b[1] - a[1]) * g];
    }
    goal -= segs[i];
  }
  return pathPts[pathPts.length - 1];
}
function czmlPos(samples) {
  // samples: [hour, lon, lat, height]
  const arr = [];
  for (const [h, lon, lat, z] of samples) arr.push(Math.round(h * 3600), r4(lon), r4(lat), z);
  return { epoch: iso(0), cartographicDegrees: arr, interpolationAlgorithm: "LINEAR" };
}
const rgba = (hex, a = 255) => [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16), a];

const perScenario = [];
for (const sid of PLAN_SCEN) {
  const sc = scenarioTracks[PLAN_ADV].find((s) => s.id === sid);
  const severity = { 0: 0.9, 1: 0.7, 2: 1.25 }[sid];
  const lf = landfallOf(sc.track);
  const lfH = lf ? lf.i : 92;
  const dir = `impact/${planKey}/s${sid}`;

  // Wind rings.
  const rings = { 34: [], 50: [], 64: [], 96: [] };
  for (let h = 0; h <= HOURS; h++) {
    const f = sc.track[h];
    const r34 = f.vmax_kt >= 34 ? 70 + 1.5 * f.vmax_kt : null;
    const mk = (thr, frac) => (f.vmax_kt >= thr && r34 ? ringAround(f.lon, f.lat, r34 * frac, 0.25) : null);
    rings[34].push(mk(34, 1));
    rings[50].push(mk(50, 0.55));
    rings[64].push(mk(64, 0.33));
    rings[96].push(mk(96, 0.16));
  }
  write(`${dir}/wind.json`, { metadata: md(), times: Array.from({ length: HOURS + 1 }, (_v, h) => iso(h)), rings });

  // Surge bands.
  const surgeBands = [
    [0.3, 0.16],
    [1, 0.1],
    [2, 0.06],
    [3, 0.035],
  ];
  write(`${dir}/surge.geojson`, {
    type: "FeatureCollection",
    metadata: md(),
    features: surgeBands.map(([band_m, w]) => ({
      type: "Feature",
      properties: { band_m, peak_time: iso(lfH + 1) },
      geometry: {
        type: "MultiPolygon",
        coordinates: [
          [band(-0.03, w * severity)],
          [
            [
              [-81.96, 26.53],
              [-81.86, 26.57 + w * 0.15],
              [-81.86, 26.61 + w * 0.2],
              [-81.96, 26.56 + w * 0.2],
              [-81.96, 26.53],
            ],
          ],
        ],
      },
    })),
  });
  write(`${dir}/gust.geojson`, {
    type: "FeatureCollection",
    metadata: md(),
    features: [34, 50, 64, 96].map((band_kt, i) => ({
      type: "Feature",
      properties: { band_kt },
      geometry: { type: "Polygon", coordinates: [band(-0.05 + i * 0.0, 0.45 - i * 0.1)] },
    })),
  });

  // Zones.
  const zones = zonesFc.features.map((f, zi) => {
    const zone = f.properties.zone;
    const rel = RELEASE[zone];
    const ts = lfH - 13 + zi;
    const clr = rel === null ? null : rel + CLEAR_DUR[zone] * (sid === 2 ? 1.25 : sid === 1 ? 0.85 : 1);
    const margin = clr === null ? null : r1(ts - clr);
    const pop = f.properties.population;
    const evac = rel === null ? 0 : Math.round(pop * 0.7);
    const notCleared = margin !== null && margin < 0 ? Math.round(evac * Math.min(0.5, -margin / 20)) : 0;
    return {
      zone,
      release_time: rel === null ? null : iso(rel),
      clearance_time: clr === null ? null : iso(clr),
      ts_arrival: iso(ts),
      margin_h: margin,
      population: pop,
      evacuees: evac,
      not_cleared: notCleared,
    };
  });

  // Evacuation flow on outbound roads.
  const evacRoads = roads.filter((r) =>
    ["US 41", "I-75", "Daniels Pkwy", "Colonial Blvd", "SR 82", "Summerlin Rd", "Cape Coral Pkwy", "Pine Island Rd", "Del Prado Blvd", "Estero Blvd", "Alico Rd"].includes(
      r.properties.name,
    ),
  );
  const evac_edges = evacRoads.map((r, i) => {
    const cap = 1800 * r.properties.lanes;
    const h0 = 50 + (i % 4) * 3;
    const vph = [];
    for (let k = 0; k < 40; k++) {
      const x = k / 39;
      vph.push(Math.round(cap * (0.35 + 0.8 * severity * Math.sin(Math.PI * x) ** 1.5) * (0.7 + 0.3 * rnd())));
    }
    return { edge_id: r.properties.edge_id, path: r.geometry.coordinates, capacity_vph: cap, h0, vph };
  });

  // Shelters.
  const shelterPlan = shelters.map((s, i) => {
    const open = !(sid === 1 && i === 5);
    const full = clamp(0.45 + 0.6 * severity * rnd(), 0.2, 1.08);
    const occ = [];
    for (let h = 0; h <= HOURS; h++) {
      const x = 1 / (1 + Math.exp(-(h - 66) / 6));
      const after = h > 104 ? 1 - (h - 104) / 40 : 1;
      occ.push(open ? Math.round(s.capacity * full * x * after) : 0);
    }
    return { id: s.id, open, capacity: s.capacity, occupancy: occ };
  });

  // Hospitals.
  const hospPlan = hospitals.map((hp, i) => {
    const avail = [];
    for (let h = 0; h <= HOURS; h++) {
      let a = hp.beds * 0.22;
      if (h > lfH - 2) a -= hp.beds * 0.18 * severity * Math.min(1, (h - lfH + 2) / 8);
      if (h > lfH + 20) a += hp.beds * 0.08 * Math.min(1, (h - lfH - 20) / 12);
      avail.push(Math.max(0, Math.round(a)));
    }
    return { id: hp.id, beds_total: hp.beds, beds_available: avail, grid_out_h: i === 3 ? lfH + 1 : null };
  });

  // Shipments.
  const shipments = [];
  const sites = [...shelters.map((s) => ({ ...s, kind: "shelter" })), ...hospitals.map((h) => ({ ...h, kind: "hospital" }))];
  let sp = 1;
  const truckSamples = new Map();
  const departs = [52, 56, 60, 64, 68, 72, 76, 80, 98, 102, 106, 110];
  for (const dep of departs) {
    for (let j = 0; j < 2; j++) {
      const d = depots[(sp + j) % depots.length];
      const site = sites[(sp * 3 + j) % sites.length];
      const c = COMMODITIES[(sp + j) % COMMODITIES.length];
      const mid = [(d.lon + site.lon) / 2 + (rnd() - 0.5) * 0.03, (d.lat + site.lat) / 2 + (rnd() - 0.5) * 0.03];
      const p = [[d.lon, d.lat], mid, [site.lon, site.lat]].map((q) => q.map(r4));
      const km = distKm(p[0], p[1]) + distKm(p[1], p[2]);
      const depart = dep + rnd() * 2;
      const arrive = depart + Math.max(0.6, km / 35);
      const truck = `tr${String(((sp + j) % 9) + 1).padStart(3, "0")}`;
      const qty = c.id === "generators" ? 4 : c.id === "med_kits" ? 300 : 12000;
      shipments.push({
        id: `sp${String(sp).padStart(3, "0")}`,
        truck_id: truck,
        depot_id: d.id,
        site_id: site.id,
        site_kind: site.kind,
        commodity: c.id,
        qty,
        unit: c.unit,
        depart_t: iso(depart),
        arrive_t: iso(arrive),
        path: p,
      });
      const smp = truckSamples.get(truck) ?? [];
      for (let k = 0; k <= 10; k++) {
        const pos = along(p, k / 10);
        smp.push([depart + ((arrive - depart) * k) / 10, pos[0], pos[1], 5]);
      }
      truckSamples.set(truck, smp);
      sp++;
    }
  }

  // Unmet demand.
  const unmet = [];
  if (sid !== 1) {
    for (const s of shelters.slice(0, 3 + sid)) {
      unmet.push({ site_id: s.id, window_start: iso(lfH + 6), commodity: "water", qty: Math.round(3000 * severity), unit: "L" });
      if (sid === 2) unmet.push({ site_id: s.id, window_start: iso(lfH + 12), commodity: "food", qty: 1500, unit: "meal" });
    }
  }

  // Rescue tasks.
  const islands = [
    ["Sanibel", [-82.14, 26.45], [-82.03, 26.43], true],
    ["Fort Myers Beach", [-81.96, 26.46], [-81.89, 26.39], true],
    ["Pine Island", [-82.12, 26.55], [-82.11, 26.68], true],
    [null, [-81.99, 26.54], [-81.9, 26.62], false],
    [null, [-81.9, 26.42], [-81.84, 26.5], false],
  ];
  const nTasks = Math.round(140 * severity);
  const tasks = [];
  for (let i = 0; i < nTasks; i++) {
    const [island, a, b, barrier] = islands[i % islands.length];
    const f = rnd();
    const lon = a[0] + (b[0] - a[0]) * f + (rnd() - 0.5) * 0.015;
    const lat = a[1] + (b[1] - a[1]) * f + (rnd() - 0.5) * 0.015;
    const pr = rnd() < 0.25 ? 1 : rnd() < 0.6 ? 2 : 3;
    const type = island === "Sanibel" ? "helo" : barrier ? (rnd() < 0.5 ? "boat" : "helo") : rnd() < 0.6 ? "high_water_truck" : "boat";
    tasks.push({
      id: `t${String(i + 1).padStart(3, "0")}`,
      lon: r4(lon),
      lat: r4(lat),
      persons: 1 + Math.floor(rnd() * 5),
      priority: pr,
      asset_type: type,
      on_barrier_island: barrier,
      island,
      created_t: iso(lfH + rnd() * 14),
      served_t: null,
      asset_id: null,
      hospital_id: null,
    });
  }
  tasks.sort((x, y) => x.created_t.localeCompare(y.created_t) || x.priority - y.priority);
  const sarAssets = [];
  const assetSamples = new Map();
  for (const a of assets) {
    const base = [a.base_lon, a.base_lat];
    let t = lfH + 3;
    const wps = [{ t: iso(t), lon: base[0], lat: base[1], task_id: null }];
    const smp = [[t, base[0], base[1], a.kind === "helo" ? 300 : 3]];
    let sinceBase = 0;
    let pos = base;
    for (const task of tasks) {
      if (task.asset_id || task.asset_type !== a.kind) continue;
      if (Date.parse(task.created_t) > T0 + t * 3600_000) {
        t = (Date.parse(task.created_t) - T0) / 3600_000;
      }
      const leg = distKm(pos, [task.lon, task.lat]) / a.speed_kmh + 0.15;
      if (t + leg > HOURS - 0.5) break;
      if (sinceBase + leg + distKm([task.lon, task.lat], base) / a.speed_kmh > a.endurance_h) {
        const back = distKm(pos, base) / a.speed_kmh;
        t += back;
        wps.push({ t: iso(t), lon: base[0], lat: base[1], task_id: null });
        smp.push([t, base[0], base[1], a.kind === "helo" ? 300 : 3]);
        t += 0.75;
        wps.push({ t: iso(t), lon: base[0], lat: base[1], task_id: null });
        smp.push([t, base[0], base[1], a.kind === "helo" ? 300 : 3]);
        pos = base;
        sinceBase = 0;
        continue;
      }
      t += leg;
      sinceBase += leg + 0.25;
      wps.push({ t: iso(t), lon: task.lon, lat: task.lat, task_id: task.id });
      smp.push([t, task.lon, task.lat, a.kind === "helo" ? 150 : 3]);
      t += 0.25;
      task.asset_id = a.id;
      task.served_t = iso(t);
      task.hospital_id = task.priority === 1 ? hospitals[Math.floor(rnd() * hospitals.length)].id : null;
      pos = [task.lon, task.lat];
      if (t > HOURS - 1) break;
    }
    sarAssets.push({ id: a.id, kind: a.kind, name: a.name, endurance_h: a.endurance_h, waypoints: wps });
    assetSamples.set(a.id, smp);
  }
  const rescued = [];
  for (let h = 0; h <= HOURS; h++) {
    let n = 0;
    for (const task of tasks) if (task.served_t && Date.parse(task.served_t) <= T0 + h * 3600_000) n += task.persons;
    rescued.push(n);
  }
  const ttr = tasks.filter((x) => x.served_t).map((x) => (Date.parse(x.served_t) - Date.parse(x.created_t)) / 3600_000);
  const hist = Array.from({ length: 12 }, (_v, i) => ({ bin_h: i * 2, count: ttr.filter((v) => v >= i * 2 && v < i * 2 + 2).length }));
  const sorted = [...ttr].sort((x, y) => x - y);
  const median = sorted.length ? r1(sorted[Math.floor(sorted.length / 2)]) : null;
  const unmet72 = tasks.filter((x) => !x.served_t || Date.parse(x.served_t) > T0 + 120 * 3600_000).length;

  // Road status.
  const roadStatus = [];
  const coastal = roads.filter((r) => r.properties.is_critical || r.geometry.coordinates[0][0] < -81.86);
  for (const r of coastal) {
    if (!r.properties.is_critical && rnd() > 0.45 * severity) continue;
    const blocked = lfH - 2 + rnd() * 5;
    const isSanibel = r.properties.critical_name === "Sanibel Causeway";
    const reopen = isSanibel ? null : blocked + 6 + rnd() * 24 * severity;
    roadStatus.push({
      edge_id: r.properties.edge_id,
      path: r.geometry.coordinates,
      blocked_t: iso(blocked),
      reopen_t: reopen === null || reopen > HOURS ? (reopen === null ? null : iso(Math.min(reopen, 119))) : iso(reopen),
      cause: r.properties.is_bridge ? "bridge" : rnd() < 0.5 ? "flood" : "tree",
      is_critical: r.properties.is_critical,
      critical_name: r.properties.critical_name,
    });
  }

  // Debris crews.
  const crews = [];
  const work = roadStatus.filter((x) => x.reopen_t).sort((x, y) => x.reopen_t.localeCompare(y.reopen_t));
  for (let c = 0; c < 3; c++) {
    const mine = work.filter((_x, i) => i % 3 === c);
    const d = depots[c];
    const wps = [{ t: iso(lfH + 4), lon: d.lon, lat: d.lat, edge_id: null }];
    const smp = [[lfH + 4, d.lon, d.lat, 5]];
    for (const e of mine) {
      const h = (Date.parse(e.reopen_t) - T0) / 3600_000;
      const mid = e.path[Math.floor(e.path.length / 2)];
      const arrive = Math.max((Date.parse(wps[wps.length - 1].t) - T0) / 3600_000 + 0.3, h - 1.5);
      wps.push({ t: iso(arrive), lon: mid[0], lat: mid[1], edge_id: e.edge_id });
      smp.push([arrive, mid[0], mid[1], 5]);
      const done = Math.max(arrive + 0.2, h);
      wps.push({ t: iso(done), lon: mid[0], lat: mid[1], edge_id: e.edge_id });
      smp.push([done, mid[0], mid[1], 5]);
    }
    crews.push({ id: `c0${c + 1}`, kind: c === 0 ? "state" : "county", waypoints: wps });
    assetSamples.set(`crew:c0${c + 1}`, smp);
  }

  const kpis = {
    persons_at_risk: Math.round(170000 * severity),
    persons_not_cleared: zones.reduce((a, z) => a + z.not_cleared, 0),
    unmet_supply_kg: Math.round(unmet.reduce((a, u) => a + u.qty * (COMMODITIES.find((c) => c.id === u.commodity)?.kg_per_unit ?? 1), 0)),
    expected_rescues: tasks.reduce((a, x) => a + x.persons, 0),
    clearance_margin_h: Math.min(...zones.filter((z) => z.margin_h !== null).map((z) => z.margin_h)),
  };

  write(`plan/${planKey}/s${sid}.json`, {
    metadata: md(),
    scenario_id: sid,
    advisory_time: iso(PLAN_ADV),
    kpis,
    zones,
    evac_edges,
    shelters: shelterPlan,
    hospitals: hospPlan,
    depots: depots.map((d, i) => ({
      id: d.id,
      staged: { water: 90000 - i * 20000, food: 40000 - i * 8000, med_kits: 800 - i * 150, fuel: 20000 - i * 5000, generators: 12 - i * 3 },
    })),
    shipments,
    unmet,
    sar_tasks: tasks,
    sar_assets: sarAssets,
    rescued_by_hour: rescued,
    time_to_rescue_hist: hist,
    median_time_to_rescue_h: median,
    unmet_tasks_72h: unmet72,
    road_status: roadStatus,
    debris_crews: crews,
  });

  // CZML.
  const czml = [
    {
      id: "document",
      name: `LANDFALL s${sid}`,
      version: "1.0",
      clock: { interval: `${iso(0)}/${iso(HOURS)}`, currentTime: iso(0), multiplier: 7200, range: "CLAMPED", step: "SYSTEM_CLOCK_MULTIPLIER" },
    },
  ];
  for (const [truck, smp] of truckSamples) {
    smp.sort((x, y) => x[0] - y[0]);
    czml.push({
      id: `truck:${truck}`,
      name: truck,
      availability: `${iso(smp[0][0])}/${iso(smp[smp.length - 1][0] + 0.5)}`,
      properties: { kind: "truck" },
      position: czmlPos(smp),
      point: { pixelSize: 7, color: { rgba: rgba("#7cf29a") }, outlineColor: { rgba: [0, 0, 0, 255] }, outlineWidth: 1 },
      path: { show: true, leadTime: 0, trailTime: 3 * 3600, width: 1.5, resolution: 120, material: { solidColor: { color: { rgba: rgba("#7cf29a", 140) } } } },
    });
  }
  for (const a of assets) {
    const smp = assetSamples.get(a.id);
    if (!smp || smp.length < 2) continue;
    czml.push({
      id: `asset:${a.id}`,
      name: a.name,
      availability: `${iso(smp[0][0])}/${iso(HOURS)}`,
      properties: { kind: a.kind },
      position: czmlPos(smp),
      point: { pixelSize: 9, color: { rgba: rgba("#ffd54f") } },
      path: { show: true, leadTime: 0, trailTime: 4 * 3600, width: 2, resolution: 120, material: { solidColor: { color: { rgba: rgba(a.kind === "helo" ? "#ffd54f" : a.kind === "boat" ? "#4dd0e1" : "#ce93d8", 150) } } } },
    });
  }
  for (const c of crews) {
    const smp = assetSamples.get(`crew:${c.id}`);
    if (!smp || smp.length < 2) continue;
    czml.push({
      id: `crew:${c.id}`,
      name: `Crew ${c.id}`,
      availability: `${iso(smp[0][0])}/${iso(HOURS)}`,
      properties: { kind: "crew" },
      position: czmlPos(smp),
      point: { pixelSize: 9, color: { rgba: rgba("#ff9f43") }, outlineColor: { rgba: [0, 0, 0, 255] }, outlineWidth: 1 },
      path: { show: true, leadTime: 0, trailTime: 4 * 3600, width: 2, resolution: 120, material: { solidColor: { color: { rgba: rgba("#ff9f43", 150) } } } },
    });
  }
  write(`plan/${planKey}/s${sid}.czml`, czml);

  perScenario.push({
    scenario_id: sid,
    probability: sc.probability,
    objective: Math.round(kpis.persons_not_cleared * 10 + kpis.unmet_supply_kg * 0.1 + unmet72 * 50),
    persons_not_cleared: kpis.persons_not_cleared,
    persons_at_risk: kpis.persons_at_risk,
    unmet_supply_kg: kpis.unmet_supply_kg,
    expected_rescues: kpis.expected_rescues,
    clearance_margin_h: kpis.clearance_margin_h,
    unmet_tasks_72h: unmet72,
    median_time_to_rescue_h: median,
    blocked_edges: roadStatus.length,
  });
}

// ---------- plan aggregates ----------
function stats(key, scale = 1) {
  const vals = perScenario.map((p) => (p[key] ?? 0) * scale);
  const probs = perScenario.map((p) => p.probability);
  const tot = probs.reduce((a, b) => a + b, 0);
  const expected = vals.reduce((a, v, i) => a + v * probs[i], 0) / tot;
  const s = [...vals].sort((a, b) => a - b);
  const worst = key === "clearance_margin_h" ? s[0] : s[s.length - 1];
  return { expected: r1(expected), worst10: r1(worst), p10: r1(s[0]), p50: r1(s[Math.floor(s.length / 2)]), p90: r1(s[s.length - 1]) };
}
const METRICS = [
  "persons_at_risk",
  "persons_not_cleared",
  "unmet_supply_kg",
  "expected_rescues",
  "unmet_tasks_72h",
  "median_time_to_rescue_h",
  "clearance_margin_h",
  "objective",
  "blocked_edges",
];
function aggregate(planName, scale) {
  const metrics = {};
  for (const m of METRICS) metrics[m] = stats(m, m === "clearance_margin_h" ? 1 : scale);
  if (planName === "baseline") metrics.clearance_margin_h = stats("clearance_margin_h");
  if (planName === "baseline") {
    metrics.clearance_margin_h.expected = r1(metrics.clearance_margin_h.expected - 3.5);
    metrics.clearance_margin_h.worst10 = r1(metrics.clearance_margin_h.worst10 - 4);
  }
  metrics.persons_evacuated = { expected: 380000, worst10: 360000, p10: 350000, p50: 380000, p90: 400000 };
  metrics.persons_rescued_72h = { expected: 420, worst10: 380, p10: 360, p50: 420, p90: 470 };
  metrics.transport_cost = { expected: 182000 * scale, worst10: 240000 * scale, p10: 150000, p50: 180000, p90: 240000 };
  return {
    metadata: md(),
    plan: planName,
    metrics,
    worst_case: 2,
    per_scenario: perScenario,
    release_time: Object.fromEntries(Object.entries(RELEASE).map(([z, h]) => [z, h === null ? null : iso(planName === "baseline" ? h + 4 : h)])),
  };
}
const agg = aggregate("optimized", 1);
const base = aggregate("baseline", 1.0);
for (const m of ["persons_not_cleared", "unmet_supply_kg", "unmet_tasks_72h", "median_time_to_rescue_h", "objective"]) {
  for (const k of ["expected", "worst10", "p10", "p50", "p90"]) base.metrics[m][k] = r1(base.metrics[m][k] * 1.45 + 5);
}
write(`plan/${planKey}/aggregate.json`, agg);
write(`plan/${planKey}/baseline.json`, base);
write(`plan/${planKey}/comparison.json`, {
  metadata: md(),
  rows: ["persons_not_cleared", "unmet_supply_kg", "unmet_tasks_72h", "median_time_to_rescue_h", "transport_cost", "objective"].map((m) => ({
    metric: m,
    label_key: `metric.${m}`,
    optimized: agg.metrics[m].expected,
    baseline: base.metrics[m].expected,
    better: "lower",
  })),
});
write(`plan/${planKey}/first_stage.json`, {
  metadata: md(),
  release_time: Object.fromEntries(Object.entries(RELEASE).map(([z, h]) => [z, h === null ? null : iso(h)])),
  open_shelters: shelters.map((s) => s.id),
  staging: depots.flatMap((d, i) => [
    { depot_id: d.id, commodity: "water", qty: 90000 - i * 20000 },
    { depot_id: d.id, commodity: "food", qty: 40000 - i * 8000 },
  ]),
  objective: agg.metrics.objective.expected,
  method: "greedy+LP",
});
const crit = roads.filter((r) => r.properties.is_critical);
const others = roads.filter((r) => !r.properties.is_critical && r.geometry.coordinates[0][0] < -81.86);
write(`plan/${planKey}/infrastructure.json`, {
  metadata: md(),
  harden: [...crit, ...others.slice(0, 10 - crit.length)].map((r, i) => ({
    rank: i + 1,
    edge_id: r.properties.edge_id,
    name: r.properties.critical_name ?? r.properties.name,
    p_blocked_any: r1(0.9 - i * 0.06),
    criticality: r1(1000 - i * 70),
    score: r1(900 - i * 75),
    path: r.geometry.coordinates,
  })),
  zones_flagged: [
    { zone: "C", p_late: 0.31 },
    { zone: "D", p_late: 0.22 },
  ],
  shelters_flagged: [{ shelter_id: "sh01", p_full: 0.41 }],
});

// ---------- verification ----------
write("verify/summary.json", {
  metadata: md(),
  leads_h: [12, 24, 48, 72, 96],
  n_cases: 21,
  methods: {
    model: { track_km: [48, 78, 130, 196, 270], intensity_kt: [8, 11, 15, 18, 20], n: [21, 21, 19, 17, 14] },
    cliper: { track_km: [70, 140, 290, 450, 610], intensity_kt: [10, 14, 19, 22, 25], n: [21, 21, 19, 17, 14] },
    ofcl: { track_km: [42, 66, 105, 160, 220], intensity_kt: [7, 10, 13, 16, 18], n: [21, 21, 19, 17, 14] },
  },
  spread_km: [40, 70, 120, 175, 240],
  rank_hist: { bins: Array.from({ length: 11 }, (_v, i) => i), counts: [3, 2, 2, 1, 2, 1, 2, 2, 1, 2, 3] },
});

console.log(`mock data written to ${OUT}`);
