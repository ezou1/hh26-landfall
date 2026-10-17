"""Hold the paths, the fixed scenario settings, and every model assumption.

Each assumption is a named constant. The model card and the UI assumptions drawer
show the same values. The ASSUMPTIONS list connects each constant to an STE description.
"""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"
RAW = DATA / "raw"
CACHE = DATA / "cache"
STATIC = DATA / "static"
OUT = ROOT / "out"

for _d in (RAW, CACHE, STATIC, OUT):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- environment
SEED = int(os.environ.get("LANDFALL_SEED", "42"))
CHALK_MODE = os.environ.get("CHALK_MODE", "local").strip().lower() or "local"
HAZARD_TYPE = "hurricane"  # hook for later hazard types; only hurricanes exist now

# ---------------------------------------------------------------- scenario
STORM_ID = "AL092022"
STORM_NAME = "IAN"
T0 = datetime(2022, 9, 25, 0, 0, tzinfo=UTC)
T_END = datetime(2022, 9, 30, 0, 0, tzinfo=UTC)
HOURS = 120
TRUTH_LANDFALL = {"time": "2022-09-28T19:05:00Z", "lat": 26.7, "lon": -82.2, "vmax_kt": 130.0}
COUNTY_NAME = "Lee County, FL"
COUNTY_FIPS = "12071"
STATE_FIPS = "12"
COUNTY_CODE = "071"
BBOX = (-82.40, 26.30, -81.55, 26.85)  # west, south, east, north
HOME_CAMERA = {"lon": -82.32, "lat": 26.02, "height_m": 60000.0, "heading_deg": 35.0, "pitch_deg": -32.0}

# Advisory times for Stage 1 (every 6 h) and for Stage 2-3.
ADVISORY_START = datetime(2022, 9, 25, 0, tzinfo=UTC)
ADVISORY_END = datetime(2022, 9, 29, 0, tzinfo=UTC)
PLAN_ADVISORIES = [
    datetime(2022, 9, 27, 0, tzinfo=UTC),
    datetime(2022, 9, 25, 0, tzinfo=UTC),
    datetime(2022, 9, 28, 0, tzinfo=UTC),
]
DEFAULT_PLAN_ADVISORY = datetime(2022, 9, 27, 0, tzinfo=UTC)
VERIFY_START = datetime(2022, 9, 23, 0, tzinfo=UTC)
VERIFY_END = datetime(2022, 9, 28, 0, tzinfo=UTC)

# ---------------------------------------------------------------- Stage 1
TRAIN_YEARS = (1980, 2021)
N_MEMBERS = 1000
N_VERIFY_MEMBERS = 500
HORIZON_H = 120
STEP_H = 6
N_SUBSAMPLE_UI = 200
K_SCENARIOS = 20
VMAX_MIN_KT = 15.0
VMAX_MAX_KT = 165.0
LAND_DECAY_PER_H = 0.07  # vmax *= exp(-0.07 * 6 h) over land
DISSIPATE_KT = 20.0
DISSIPATE_HOURS = 12
RESIDUAL_JITTER = 0.1  # Gaussian jitter as a fraction of the bucket residual std
LEAD_BUCKETS_H = (6, 12, 24, 48, 72, 96, 120)
MLP_HIDDEN = 256
MLP_LAYERS = 3
MLP_DROPOUT = 0.1
MLP_EPOCHS = 60
MLP_BAG = int(__import__("os").environ.get("LANDFALL_MLP_BAG", "5"))  # bagged members
MLP_INPUT_NOISE = float(__import__("os").environ.get("LANDFALL_MLP_NOISE", "0.0"))
REDUCE_INTENSITY_WEIGHT_KM_PER_KT = 3.0
CLIPER_DRIFT_WEIGHT = 0.5

# ---------------------------------------------------------------- Stage 2
GRID_RES_M = 500.0
HOLLAND_B = 1.3
RMAX_MAJOR_KM = 35.0  # Cat 3+
RMAX_OTHER_KM = 50.0
FORWARD_MOTION_FRACTION = 0.6
GUST_FACTOR = 1.3  # peak gust / 1-min sustained wind
SURGE_COEFF = 0.0084  # S = coeff * vmax_kt^1.7 * k_angle; see docs/MODEL_CARD.md
SURGE_EXP = 1.7
SURGE_INLAND_KM = 15.0
SURGE_K_ANGLE_MIN = 0.3
DAMAGE_SIGMOID_A = 0.08  # per mph
DAMAGE_GUST_MID_MPH = 95.0
INJURY_RATE = 0.02
INJURY_ADMIT_FRACTION = 0.10  # fraction of injuries that need a hospital bed
RESCUE_RATE = 0.3
TREE_SIGMOID_C = 0.08  # per mph
TREE_GUST_MID_MPH = 80.0
FLOOD_BLOCK_DEPTH_M = 0.3
BRIDGE_BLOCK_P = 0.5
BRIDGE_BLOCK_GUST_MPH = 120.0
KT_TO_MPH = 1.15078
KT_TO_MS = 0.514444

# ---------------------------------------------------------------- Stage 3
M_DRAWS = 5
EVAC_COMPLIANCE = 0.7
EVAC_COMPLIANCE_RANGE = (0.55, 0.85)
SHADOW_EVAC = 0.15
DEPARTURE_WINDOW_H = 12
LANE_CAPACITY_VPH = 1800.0
CAPACITY_FACTOR = 0.7
VEHICLES_PER_HOUSEHOLD = 1.3
PERSONS_PER_HOUSEHOLD = 2.4
SHELTER_FRACTION = 0.07  # fraction of evacuees that go to a public shelter
LOADING_ROUNDS = 5
RELEASE_BIN_H = 6
W1_NOT_CLEARED = 1000.0
W2_UNMET_SUPPLY = 50.0
W3_RESCUE = 500.0
W4_UNNECESSARY = 1.0
W5_TRANSPORT = 0.1
WATER_L_PER_PERSON_DAY = 4.0
MEALS_PER_PERSON_DAY = 3.0
KITS_PER_INJURY = 1.2
KITS_PER_PERSON = 0.01
GEN_PER_SHELTERED = 1 / 200
GEN_PER_HOSPITAL_OUTAGE = 2
FUEL_L_PER_GEN_HOUR = 10.0
GRID_OUTAGE_GUST_MPH = 100.0
TRUCK_CAPACITY_KG = 3000.0
SUPPLY_WINDOW_H = 12
SAR_START_AFTER_LANDFALL_H = 6
SAR_HORIZON_H = 72
HELO_GROUND_ETA_LIMIT_MIN = 45.0
MEDEVAC_P2_FRACTION = 0.2
HOSPITAL_RECOVERY_PER_DAY = 0.10
HOSPITAL_FREE_FRACTION = 0.25  # fraction of beds free at T0
SAR_SERVICE_MIN = {"boat": 25.0, "high_water_truck": 20.0, "helo": 30.0}
SAR_MAX_TASK_PERSONS = {"boat": 8, "high_water_truck": 10, "helo": 4}
SAR_MAX_TASKS = 400
CREWS_COUNTY = 8
CREWS_STATE = 4
CLEAR_H_PER_100M = 0.5
CLEAR_MIN_H = 1.0
BRIDGE_REPAIR_DAYS = 30
CREW_SPEED_KMH = 30.0

COMMODITIES = [
    {"id": "water", "unit": "L", "kg_per_unit": 1.0},
    {"id": "food", "unit": "meals", "kg_per_unit": 0.5},
    {"id": "med_kits", "unit": "kits", "kg_per_unit": 2.0},
    {"id": "fuel", "unit": "L", "kg_per_unit": 0.85},
    {"id": "generators", "unit": "units", "kg_per_unit": 120.0},
]

ZONES = ["A", "B", "C", "D", "E"]

# Critical links: barrier-island causeways and bridges. The bbox is lon/lat.
CRITICAL_LINKS = {
    "Sanibel Causeway": (-82.040, 26.440, -81.995, 26.495),
    "Matlacha Pass Bridge": (-82.080, 26.620, -82.055, 26.645),
    "Pine Island Road": (-82.130, 26.625, -81.990, 26.660),
    "Fort Myers Beach Bridge": (-81.965, 26.452, -81.945, 26.470),
    "Big Carlos Pass Bridge": (-81.890, 26.395, -81.875, 26.408),
    "Boca Grande Causeway": (-82.290, 26.715, -82.245, 26.755),
}

# Barrier islands with the links that connect them to the mainland.
ISLANDS = {
    "Sanibel": {"bbox": (-82.20, 26.40, -82.00, 26.50), "links": ["Sanibel Causeway"]},
    "Captiva": {"bbox": (-82.20, 26.50, -82.15, 26.56), "links": ["Sanibel Causeway"]},
    "Fort Myers Beach": {
        "bbox": (-81.975, 26.395, -81.880, 26.465),
        "links": ["Fort Myers Beach Bridge", "Big Carlos Pass Bridge"],
    },
    "Pine Island": {
        "bbox": (-82.170, 26.480, -82.065, 26.720),
        "links": ["Matlacha Pass Bridge", "Pine Island Road"],
    },
    "Gasparilla": {"bbox": (-82.290, 26.700, -82.245, 26.790), "links": ["Boca Grande Causeway"]},
}

# Exits from the county for evacuation and supply (lon, lat).
EXITS = {
    "I-75 N": (-81.835, 26.790),
    "I-75 S": (-81.765, 26.320),
    "SR-80 E": (-81.565, 26.735),
}
EXIT_EXTRA_H = {"I-75 N": 0.0, "I-75 S": 0.0, "SR-80 E": 0.0}


def iso(t: datetime) -> str:
    """Return a UTC time as an ISO-8601 string with a Z suffix."""
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def advkey(t: datetime) -> str:
    """Return the folder key of an advisory time, for example 2022092700."""
    return t.astimezone(UTC).strftime("%Y%m%d%H")


def hour_to_time(h: float) -> datetime:
    """Return the UTC time of an hour index from T0."""
    return T0 + timedelta(hours=float(h))


def time_to_hour(t: datetime) -> float:
    """Return the hour index from T0 of a UTC time."""
    return (t - T0).total_seconds() / 3600.0


def advisory_times() -> list[datetime]:
    """Return the Stage 1 advisory times, every 6 h."""
    out = []
    t = ADVISORY_START
    while t <= ADVISORY_END:
        out.append(t)
        t += timedelta(hours=6)
    return out


@lru_cache(maxsize=1)
def git_sha() -> str:
    """Return the short git SHA of the repository, or "unknown"."""
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
            ).stdout.strip()
            or "unknown"
        )
    except Exception:
        return "unknown"


ASSUMPTIONS: list[dict[str, object]] = [
    {"key": "HOLLAND_B", "value": HOLLAND_B, "unit": "-", "text": "The wind model uses a Holland B value of 1.3."},
    {"key": "RMAX_MAJOR_KM", "value": RMAX_MAJOR_KM, "unit": "km", "text": "The radius of maximum wind is 35 km for Category 3 and higher."},
    {"key": "RMAX_OTHER_KM", "value": RMAX_OTHER_KM, "unit": "km", "text": "The radius of maximum wind is 50 km for weaker storms."},
    {"key": "FORWARD_MOTION_FRACTION", "value": FORWARD_MOTION_FRACTION, "unit": "fraction", "text": "The model adds 60% of the forward speed on the right side of the storm."},
    {"key": "GUST_FACTOR", "value": GUST_FACTOR, "unit": "-", "text": "The peak gust is 1.3 times the sustained wind."},
    {"key": "SURGE_COEFF", "value": SURGE_COEFF, "unit": "m/kt^1.7", "text": "The surge proxy uses this constant. The Ian truth track gives about 4 m (13 ft) near Fort Myers Beach."},
    {"key": "SURGE_INLAND_KM", "value": SURGE_INLAND_KM, "unit": "km", "text": "Surge can flood cells up to 15 km from the coast."},
    {"key": "DAMAGE_GUST_MID_MPH", "value": DAMAGE_GUST_MID_MPH, "unit": "mph", "text": "The chance of major damage is 50% at a gust of 95 mph (42 m/s)."},
    {"key": "INJURY_RATE", "value": INJURY_RATE, "unit": "fraction", "text": "2% of persons in a building with major damage get an injury."},
    {"key": "INJURY_ADMIT_FRACTION", "value": INJURY_ADMIT_FRACTION, "unit": "fraction", "text": "10% of injured persons need a hospital bed."},
    {"key": "RESCUE_RATE", "value": RESCUE_RATE, "unit": "fraction", "text": "30% of persons that stay in water deeper than 1 m ask for rescue."},
    {"key": "EVAC_COMPLIANCE", "value": EVAC_COMPLIANCE, "unit": "fraction", "text": "70% of persons in an ordered zone leave. Each draw samples a value from 55% to 85%."},
    {"key": "SHADOW_EVAC", "value": SHADOW_EVAC, "unit": "fraction", "text": "15% of persons in a zone next to an ordered zone also leave."},
    {"key": "DEPARTURE_WINDOW_H", "value": DEPARTURE_WINDOW_H, "unit": "h", "text": "Persons leave over 12 h after the order. The departure curve is logistic."},
    {"key": "LANE_CAPACITY_VPH", "value": LANE_CAPACITY_VPH, "unit": "veh/h", "text": "One lane moves 1800 vehicles each hour. The model uses 70% of this value."},
    {"key": "VEHICLES_PER_HOUSEHOLD", "value": VEHICLES_PER_HOUSEHOLD, "unit": "veh", "text": "Each household that leaves uses 1.3 vehicles."},
    {"key": "SHELTER_FRACTION", "value": SHELTER_FRACTION, "unit": "fraction", "text": "7% of evacuees go to a public shelter. The others leave the county or stay with friends."},
    {"key": "TRUCK_CAPACITY_KG", "value": TRUCK_CAPACITY_KG, "unit": "kg", "text": "One truck carries 3000 kg (6600 lb)."},
    {"key": "HOSPITAL_FREE_FRACTION", "value": HOSPITAL_FREE_FRACTION, "unit": "fraction", "text": "25% of hospital beds are free at the start."},
    {"key": "HOSPITAL_RECOVERY_PER_DAY", "value": HOSPITAL_RECOVERY_PER_DAY, "unit": "fraction/day", "text": "Hospitals free 10% of the used beds each day."},
    {"key": "GRID_OUTAGE_GUST_MPH", "value": GRID_OUTAGE_GUST_MPH, "unit": "mph", "text": "A site loses grid power if the gust is more than 100 mph (45 m/s)."},
    {"key": "CLEAR_H_PER_100M", "value": CLEAR_H_PER_100M, "unit": "h/100 m", "text": "A crew clears 100 m of blocked road in 0.5 h. The minimum time for one task is 1 h."},
    {"key": "BRIDGE_REPAIR_DAYS", "value": BRIDGE_REPAIR_DAYS, "unit": "day", "text": "A bridge repair takes 30 days. The plan shows these tasks but does not schedule them."},
    {"key": "SST_PROXY", "value": "28 - 0.25*max(0,|lat|-10)", "unit": "degC", "text": "The sea temperature is a climate proxy. It is not a measured value."},
    {"key": "LAND_DECAY_PER_H", "value": LAND_DECAY_PER_H, "unit": "1/h", "text": "Over land, the wind speed decreases by a factor of exp(-0.07 per hour)."},
]
