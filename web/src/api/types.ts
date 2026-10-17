/**
 * Types for the backend artifacts. The file .dev/CONTRACT.md gives the source of truth.
 */

/** An ISO-8601 UTC time string with a trailing Z. */
export type IsoTime = string;
/** A position as [lon, lat]. */
export type LonLat = [number, number];

/** The metadata block that each JSON artifact contains. */
export interface ArtifactMetadata {
  seed?: number | null;
  git_sha?: string | null;
  created_utc?: string | null;
  used_fallback?: boolean | null;
  fallback_items?: string[] | null;
}

export interface Assumption {
  key: string;
  value: number | string | boolean | null;
  unit?: string | null;
  text?: string | null;
}

export interface Commodity {
  id: string;
  unit: string;
  kg_per_unit: number;
}

export interface HomeCamera {
  lon: number;
  lat: number;
  height_m: number;
  heading_deg: number;
  pitch_deg: number;
}

export interface Meta {
  metadata?: ArtifactMetadata;
  storm_id: string;
  storm_name: string;
  t0: IsoTime;
  t_end: IsoTime;
  hours: number;
  county: { name: string; fips: string; bbox: [number, number, number, number] };
  advisories: IsoTime[];
  plan_advisories: IsoTime[];
  default_plan_advisory: IsoTime | null;
  truth_landfall: { time: IsoTime; lat: number; lon: number; vmax_kt: number } | null;
  home_camera: HomeCamera;
  assumptions: Assumption[];
  commodities: Commodity[];
}

export interface TrackFix {
  t: IsoTime;
  lat: number;
  lon: number;
  vmax_kt: number;
  pmin_mb?: number | null;
  rmax_km?: number | null;
}

export interface Truth {
  metadata?: ArtifactMetadata;
  track: TrackFix[];
  carq?: TrackFix[];
}

/** One ensemble point as [lon, lat, vmax_kt]. */
export type EnsemblePoint = [number, number, number];

export interface Ensemble {
  metadata?: ArtifactMetadata;
  advisory_time: IsoTime;
  n_members: number;
  times: IsoTime[];
  members: EnsemblePoint[][];
  mean: EnsemblePoint[];
  ofcl: TrackFix[];
  observed: TrackFix[];
}

// GeoJSON (only the parts that the UI reads).
export interface PolygonGeom {
  type: "Polygon";
  coordinates: LonLat[][];
}
export interface MultiPolygonGeom {
  type: "MultiPolygon";
  coordinates: LonLat[][][];
}
export interface LineStringGeom {
  type: "LineString";
  coordinates: LonLat[];
}
export interface MultiLineStringGeom {
  type: "MultiLineString";
  coordinates: LonLat[][];
}
export type AreaGeom = PolygonGeom | MultiPolygonGeom;
export type LineGeom = LineStringGeom | MultiLineStringGeom;

export interface Feature<G, P> {
  type: "Feature";
  geometry: G | null;
  properties: P;
}
export interface FeatureCollection<G, P> {
  type: "FeatureCollection";
  metadata?: ArtifactMetadata;
  features: Feature<G, P>[];
}

export type ConeLevel = "p50" | "p66" | "p90";
export type ConeCollection = FeatureCollection<AreaGeom, { level: ConeLevel }>;

export interface Landfall {
  metadata?: ArtifactMetadata;
  advisory_time: IsoTime;
  p_landfall_county: number;
  landfall_time_p10: IsoTime | null;
  landfall_time_p50: IsoTime | null;
  landfall_time_p90: IsoTime | null;
  category_dist: Record<string, number>;
}

export interface Scenario {
  id: number;
  label: string;
  probability: number;
  is_ofcl: boolean;
  is_worst: boolean;
  landfall_time: IsoTime | null;
  landfall_lon: number | null;
  landfall_lat: number | null;
  category: string | null;
  track: TrackFix[];
}

export interface Scenarios {
  metadata?: ArtifactMetadata;
  advisory_time: IsoTime;
  scenarios: Scenario[];
}

export type WindThreshold = "34" | "50" | "64" | "96";
export interface WindField {
  metadata?: ArtifactMetadata;
  times: IsoTime[];
  rings: Partial<Record<WindThreshold, (LonLat[] | null)[]>>;
}

export type SurgeCollection = FeatureCollection<AreaGeom, { band_m: number; peak_time: IsoTime | null }>;
export type GustCollection = FeatureCollection<AreaGeom, { band_kt: number }>;

export type ZoneCollection = FeatureCollection<AreaGeom, { zone: string; population: number }>;

export interface Shelter {
  id: string;
  name: string;
  lat: number;
  lon: number;
  capacity: number;
  is_special_needs: boolean;
}

export interface Hospital {
  id: string;
  name: string;
  lat: number;
  lon: number;
  beds: number;
  has_helipad: boolean;
  trauma_level: number | string | null;
}

export interface Depot {
  id: string;
  name: string;
  kind: "state" | "county" | "retail";
  lat: number;
  lon: number;
  inventory: Record<string, number>;
  trucks: number;
}

export type AssetKind = "helo" | "boat" | "high_water_truck";
export interface Asset {
  id: string;
  kind: AssetKind;
  name: string;
  base_lat: number;
  base_lon: number;
  speed_kmh: number;
  capacity_persons: number;
  endurance_h: number;
}

export interface RoadProps {
  edge_id: string;
  name: string | null;
  highway: string | null;
  lanes: number | null;
  is_critical: boolean;
  critical_name: string | null;
  is_bridge: boolean;
}
export type RoadCollection = FeatureCollection<LineGeom, RoadProps>;

export interface FirstStage {
  metadata?: ArtifactMetadata;
  release_time: Record<string, IsoTime | null>;
  open_shelters: string[];
  staging: { depot_id: string; commodity: string; qty: number }[];
  objective: number;
  method: string;
}

export interface MetricStats {
  expected: number | null;
  worst10: number | null;
  p10?: number | null;
  p50?: number | null;
  p90?: number | null;
}

export type MetricKey =
  | "persons_at_risk"
  | "persons_not_cleared"
  | "persons_evacuated"
  | "unmet_supply_kg"
  | "expected_rescues"
  | "persons_rescued_72h"
  | "unmet_tasks_72h"
  | "median_time_to_rescue_h"
  | "clearance_margin_h"
  | "objective"
  | "blocked_edges"
  | "transport_cost";

export interface PlanAggregate {
  metadata?: ArtifactMetadata;
  plan: "optimized" | "baseline";
  metrics: Partial<Record<MetricKey, MetricStats>>;
  worst_case: number | null;
  per_scenario: ({ scenario_id: number; probability: number } & Partial<Record<MetricKey, number | null>>)[];
  release_time?: Record<string, IsoTime | null>;
}

export interface ComparisonRow {
  metric: string;
  label_key: string;
  optimized: number | null;
  baseline: number | null;
  better: "lower" | "higher";
}
export interface Comparison {
  metadata?: ArtifactMetadata;
  rows: ComparisonRow[];
}

export interface HardenEdge {
  rank: number;
  edge_id: string;
  name: string | null;
  p_blocked_any: number;
  criticality: number;
  score: number;
  path: LonLat[];
}
export interface Infrastructure {
  metadata?: ArtifactMetadata;
  harden: HardenEdge[];
  zones_flagged: { zone: string; p_late: number }[];
  shelters_flagged: { shelter_id: string; p_full: number }[];
}

export interface ZonePlan {
  zone: string;
  release_time: IsoTime | null;
  clearance_time: IsoTime | null;
  ts_arrival: IsoTime | null;
  margin_h: number | null;
  population: number;
  evacuees: number;
  not_cleared: number;
}

export interface EvacEdge {
  edge_id: string;
  path: LonLat[];
  capacity_vph: number;
  h0: number;
  vph: number[];
}

export interface ShelterPlan {
  id: string;
  open: boolean;
  capacity: number;
  occupancy: number[];
}

export interface HospitalPlan {
  id: string;
  beds_total: number;
  beds_available: number[];
  grid_out_h: number | null;
}

export interface Shipment {
  id: string;
  truck_id: string;
  depot_id: string;
  site_id: string;
  site_kind: "shelter" | "hospital";
  commodity: string;
  qty: number;
  unit: string;
  depart_t: IsoTime;
  arrive_t: IsoTime;
  path: LonLat[];
}

export interface Unmet {
  site_id: string;
  window_start: IsoTime;
  commodity: string;
  qty: number;
  unit: string;
}

export interface SarTask {
  id: string;
  lon: number;
  lat: number;
  persons: number;
  priority: 1 | 2 | 3;
  asset_type: AssetKind;
  on_barrier_island: boolean;
  island: string | null;
  created_t: IsoTime;
  served_t: IsoTime | null;
  asset_id: string | null;
  hospital_id: string | null;
}

export interface Waypoint {
  t: IsoTime;
  lon: number;
  lat: number;
  task_id?: string | null;
  edge_id?: string | null;
}

export interface SarAsset {
  id: string;
  kind: AssetKind;
  name: string;
  endurance_h: number;
  waypoints: Waypoint[];
}

export interface RoadStatus {
  edge_id: string;
  path: LonLat[];
  blocked_t: IsoTime;
  reopen_t: IsoTime | null;
  cause: "tree" | "flood" | "bridge";
  is_critical: boolean;
  critical_name: string | null;
}

export interface DebrisCrew {
  id: string;
  kind: "county" | "state";
  waypoints: Waypoint[];
}

export interface ScenarioKpis {
  persons_at_risk: number | null;
  persons_not_cleared: number | null;
  unmet_supply_kg: number | null;
  expected_rescues: number | null;
  clearance_margin_h: number | null;
}

export interface ScenarioPlan {
  metadata?: ArtifactMetadata;
  scenario_id: number;
  advisory_time: IsoTime;
  kpis: ScenarioKpis;
  zones: ZonePlan[];
  evac_edges: EvacEdge[];
  shelters: ShelterPlan[];
  hospitals: HospitalPlan[];
  depots: { id: string; staged: Record<string, number> }[];
  shipments: Shipment[];
  unmet: Unmet[];
  sar_tasks: SarTask[];
  sar_assets: SarAsset[];
  rescued_by_hour: number[];
  time_to_rescue_hist: { bin_h: number; count: number }[];
  median_time_to_rescue_h: number | null;
  unmet_tasks_72h: number | null;
  road_status: RoadStatus[];
  debris_crews: DebrisCrew[];
}

export interface MethodErrors {
  track_km: (number | null)[];
  intensity_kt: (number | null)[];
  n: (number | null)[];
}

export interface VerifySummary {
  metadata?: ArtifactMetadata;
  leads_h: number[];
  n_cases: number;
  methods: Partial<Record<"model" | "cliper" | "ofcl", MethodErrors>>;
  spread_km: (number | null)[];
  rank_hist: { bins: number[]; counts: number[] };
}

export interface RerunStart {
  job_id: string;
  status: string;
}
export interface RerunStatus {
  job_id: string;
  status: "running" | "done" | "error";
  progress: number;
  message: string;
}

/** The static inputs that do not change with the advisory. */
export interface Statics {
  zones: ZoneCollection | null;
  shelters: Shelter[];
  hospitals: Hospital[];
  depots: Depot[];
  assets: Asset[];
  roads: RoadCollection | null;
  truth: Truth | null;
}

/** The Stage 1 artifacts of one advisory. */
export interface Stage1Bundle {
  advisory: IsoTime;
  ensemble: Ensemble | null;
  cone: ConeCollection | null;
  landfall: Landfall | null;
  scenarios: Scenarios | null;
}

/** The plan artifacts of one plan advisory that do not depend on the scenario. */
export interface PlanCommon {
  advisory: IsoTime;
  firstStage: FirstStage | null;
  aggregate: PlanAggregate | null;
  baseline: PlanAggregate | null;
  comparison: Comparison | null;
  infrastructure: Infrastructure | null;
}

/** The plan artifacts of one scenario of one plan advisory. */
export interface PlanScenarioBundle {
  advisory: IsoTime;
  scenarioId: number;
  plan: ScenarioPlan | null;
  wind: WindField | null;
  surge: SurgeCollection | null;
  czmlUrl: string | null;
}
