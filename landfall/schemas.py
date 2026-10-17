"""Define a pydantic model for every JSON artifact that the pipeline writes.

Every stage writes its JSON output through write_model and reads it back through
read_model. The models match the artifact contract that the UI uses.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

LonLat = tuple[float, float]


class Model(BaseModel):
    """The base model for all artifacts."""

    model_config = ConfigDict(extra="forbid")


class Metadata(Model):
    """The metadata block that every artifact carries."""

    seed: int
    git_sha: str
    created_utc: str
    used_fallback: bool
    fallback_items: list[str] = Field(default_factory=list)


class Assumption(Model):
    """One model assumption for the UI drawer."""

    key: str
    value: float | str
    unit: str
    text: str


class Commodity(Model):
    """One supply commodity."""

    id: str
    unit: str
    kg_per_unit: float


class County(Model):
    """The county of the scenario."""

    name: str
    fips: str
    bbox: tuple[float, float, float, float]


class TruthLandfall(Model):
    """The observed landfall."""

    time: str
    lat: float
    lon: float
    vmax_kt: float


class Camera(Model):
    """A camera pose for the globe."""

    lon: float
    lat: float
    height_m: float
    heading_deg: float
    pitch_deg: float


class Meta(Model):
    """The out/meta.json index file."""

    metadata: Metadata
    storm_id: str
    storm_name: str
    t0: str
    t_end: str
    hours: int
    county: County
    advisories: list[str]
    plan_advisories: list[str]
    default_plan_advisory: str
    truth_landfall: TruthLandfall
    home_camera: Camera
    assumptions: list[Assumption]
    commodities: list[Commodity]
    chalk_mode: str = "local"


class Fix(Model):
    """One track point."""

    t: str
    lat: float
    lon: float
    vmax_kt: float
    pmin_mb: float | None = None


class Truth(Model):
    """The best track and the CARQ fixes."""

    metadata: Metadata
    track: list[Fix]
    carq: list[Fix]


class Ensemble(Model):
    """The Stage 1 ensemble for one advisory."""

    metadata: Metadata
    advisory_time: str
    n_members: int
    times: list[str]
    members: list[list[tuple[float, float, float]]]
    mean: list[tuple[float, float, float]]
    ofcl: list[Fix]
    observed: list[Fix]
    seconds: float = 0.0


class Landfall(Model):
    """The landfall summary for one advisory."""

    metadata: Metadata
    advisory_time: str
    p_landfall_county: float
    landfall_time_p10: str | None
    landfall_time_p50: str | None
    landfall_time_p90: str | None
    category_dist: dict[str, float]
    n_landfall: int = 0


class TrackPoint(Model):
    """One hourly point of a scenario track."""

    t: str
    lat: float
    lon: float
    vmax_kt: float
    pmin_mb: float
    rmax_km: float


class Scenario(Model):
    """One reduced scenario."""

    id: int
    label: str
    probability: float
    is_ofcl: bool
    is_worst: bool = False
    landfall_time: str | None
    landfall_lon: float | None
    landfall_lat: float | None
    category: str | None
    track: list[TrackPoint]


class Scenarios(Model):
    """The K reduced scenarios for one advisory."""

    metadata: Metadata
    advisory_time: str
    scenarios: list[Scenario]


class WindRings(Model):
    """Hourly wind-threshold rings for one scenario."""

    metadata: Metadata
    times: list[str]
    rings: dict[str, list[list[LonLat] | None]]


class Site(Model):
    """A shelter."""

    id: str
    name: str
    lat: float
    lon: float
    capacity: int
    is_special_needs: bool


class Hospital(Model):
    """A hospital."""

    id: str
    name: str
    lat: float
    lon: float
    beds: int
    has_helipad: bool
    trauma_level: int


class Depot(Model):
    """A supply depot."""

    id: str
    name: str
    kind: Literal["state", "county", "retail"]
    lat: float
    lon: float
    inventory: dict[str, float]
    trucks: int


class Asset(Model):
    """A SAR asset."""

    id: str
    kind: Literal["helo", "boat", "high_water_truck"]
    name: str
    base_lat: float
    base_lon: float
    speed_kmh: float
    capacity_persons: int
    endurance_h: float


class FirstStage(Model):
    """The first-stage decisions that all scenarios share."""

    metadata: Metadata
    release_time: dict[str, str | None]
    open_shelters: list[str]
    staging: list[dict[str, Any]]
    objective: float
    method: str


class MetricStats(Model):
    """The distribution of one metric over the scenario samples."""

    expected: float
    worst10: float
    p10: float
    p50: float
    p90: float


class Aggregate(Model):
    """The aggregate plan metrics (optimized or baseline)."""

    metadata: Metadata
    plan: Literal["optimized", "baseline"]
    metrics: dict[str, MetricStats]
    worst_case: int
    per_scenario: list[dict[str, float]]
    release_time: dict[str, str | None]


class ComparisonRow(Model):
    """One row of the optimized-vs-baseline table."""

    metric: str
    label_key: str
    optimized: float
    baseline: float
    better: Literal["lower", "higher"]


class Comparison(Model):
    """The optimized-vs-baseline comparison."""

    metadata: Metadata
    rows: list[ComparisonRow]


class HardenEdge(Model):
    """One edge of the harden list."""

    rank: int
    edge_id: str
    name: str
    p_blocked_any: float
    criticality: float
    score: float
    path: list[LonLat]


class Infrastructure(Model):
    """The infrastructure insight across all scenarios."""

    metadata: Metadata
    harden: list[HardenEdge]
    zones_flagged: list[dict[str, Any]]
    shelters_flagged: list[dict[str, Any]]


class ZonePlan(Model):
    """The evacuation result for one zone in one scenario."""

    zone: str
    release_time: str | None
    clearance_time: str | None
    ts_arrival: str | None
    margin_h: float | None
    population: float
    evacuees: float
    not_cleared: float


class EvacEdge(Model):
    """The hourly evacuation flow on one edge."""

    edge_id: str
    path: list[LonLat]
    capacity_vph: float
    h0: int
    vph: list[float]


class ShelterPlan(Model):
    """The hourly occupancy of one shelter."""

    id: str
    open: bool
    capacity: int
    occupancy: list[int]


class HospitalPlan(Model):
    """The hourly free beds of one hospital."""

    id: str
    beds_total: int
    beds_available: list[int]
    grid_out_h: int | None


class DepotPlan(Model):
    """The staged inventory of one depot."""

    id: str
    staged: dict[str, float]


class Shipment(Model):
    """One truck shipment."""

    id: str
    truck_id: str
    depot_id: str
    site_id: str
    site_kind: Literal["shelter", "hospital"]
    commodity: str
    qty: float
    unit: str
    depart_t: str
    arrive_t: str
    path: list[LonLat]


class Unmet(Model):
    """Unmet demand at one site in one window."""

    site_id: str
    window_start: str
    commodity: str
    qty: float
    unit: str


class SarTask(Model):
    """One rescue task."""

    id: str
    lon: float
    lat: float
    persons: int
    priority: int
    asset_type: Literal["boat", "high_water_truck", "helo"]
    on_barrier_island: bool
    island: str | None
    created_t: str
    served_t: str | None
    asset_id: str | None
    hospital_id: str | None


class Waypoint(Model):
    """One timed waypoint of an asset or a crew."""

    t: str
    lon: float
    lat: float
    task_id: str | None = None
    edge_id: str | None = None


class SarAsset(Model):
    """The route of one SAR asset."""

    id: str
    kind: str
    name: str
    endurance_h: float
    waypoints: list[Waypoint]


class RoadStatus(Model):
    """The status of one blocked edge."""

    edge_id: str
    path: list[LonLat]
    blocked_t: str
    reopen_t: str | None
    cause: Literal["tree", "flood", "bridge"]
    is_critical: bool
    critical_name: str | None


class Crew(Model):
    """The route of one debris crew."""

    id: str
    kind: Literal["county", "state"]
    waypoints: list[Waypoint]


class Kpis(Model):
    """The headline numbers of one scenario."""

    persons_at_risk: float
    persons_not_cleared: float
    unmet_supply_kg: float
    expected_rescues: float
    clearance_margin_h: float


class ScenarioPlan(Model):
    """The full plan for one scenario (one representative draw)."""

    metadata: Metadata
    scenario_id: int
    advisory_time: str
    kpis: Kpis
    zones: list[ZonePlan]
    evac_edges: list[EvacEdge]
    shelters: list[ShelterPlan]
    hospitals: list[HospitalPlan]
    depots: list[DepotPlan]
    shipments: list[Shipment]
    unmet: list[Unmet]
    sar_tasks: list[SarTask]
    sar_assets: list[SarAsset]
    rescued_by_hour: list[int]
    time_to_rescue_hist: list[dict[str, float]]
    median_time_to_rescue_h: float | None
    unmet_tasks_72h: int
    road_status: list[RoadStatus]
    debris_crews: list[Crew]


class VerifySummary(Model):
    """The verification summary."""

    metadata: Metadata
    leads_h: list[int]
    n_cases: int
    methods: dict[str, dict[str, list[float | None]]]
    spread_km: list[float | None]
    rank_hist: dict[str, list[int]]
    n_members: int


M = TypeVar("M", bound=BaseModel)


def write_model(path: Path, model: BaseModel) -> None:
    """Validate a model and write it as compact JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(exclude_none=False))


def read_model(path: Path, cls: type[M]) -> M:
    """Read a JSON artifact and validate it with a model."""
    return cls.model_validate(json.loads(path.read_text()))


def write_geojson(path: Path, fc: dict[str, Any], meta: Metadata | dict[str, Any] | None = None) -> None:
    """Write a GeoJSON FeatureCollection. Put the metadata in a foreign member."""
    path.parent.mkdir(parents=True, exist_ok=True)
    out = dict(fc)
    if meta is not None:
        out["metadata"] = meta.model_dump() if isinstance(meta, BaseModel) else meta
    path.write_text(json.dumps(out, separators=(",", ":")))
