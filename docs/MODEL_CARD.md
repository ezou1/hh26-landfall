# Model card

This card describes the LANDFALL track and intensity predictor, the impact model, and the logistics model. It also gives every modelling assumption.

## Predictor

### Summary

| Item | Value |
| --- | --- |
| Task | Predict the change of latitude, longitude, and wind speed over the next 6 h |
| Architecture | MLP: 3 hidden layers of 256 units, GELU, dropout 0.1. The predictor is the mean of 5 members with different seeds. |
| Framework | PyTorch 2.7 on the CPU. The machine has no GPU. |
| Inputs | The 19 `StormState` features of `chalk/features.py`. The heading and the day of the year become sine and cosine values. |
| Training data | Atlantic HURDAT2 fixes from 1980 to 2014: 14,227 rows |
| Validation data | Atlantic HURDAT2 fixes from 2015 to 2021: 3,873 rows and 134 storms |
| Training time | About 6 min for the 5 members on a 12-core CPU |
| Validation loss | 0.203 (MSE of the standardised targets) |
| One-step mean absolute error | 0.19 degrees of latitude, 0.25 degrees of longitude, 3.0 kt |

The training rows come from one Chalk offline query. Each row resolves at its own fix time, so the features are point-in-time correct. Ian (2022) is not in the training data or the validation data. We did not tune any value on Ian.

### Residual bank

The sampler adds a residual vector to each 6-h step. The bank holds the rollout residuals of the validation storms. The residual of step k is the true 6-h change minus the model change at the state of a deterministic rollout. A member draws from the bucket of its lead time and from its latitude band. The 5 bands have edges at 20 N, 26 N, 32 N, and 40 N. A Gaussian jitter of 10% of the bucket standard deviation follows.

The residuals grow with lead time, as the table shows.

| Lead bucket (h) | Residuals | Std of dlat (deg) | Std of dlon (deg) | Std of dv (kt) | Spread scale |
| --- | --- | --- | --- | --- | --- |
| 6 | 3,873 | 0.29 | 0.39 | 4.3 | 0.98 |
| 12 | 3,524 | 0.42 | 0.57 | 4.9 | 0.88 |
| 24 | 6,430 | 0.56 | 0.77 | 5.3 | 0.52 |
| 48 | 10,981 | 0.72 | 1.04 | 6.0 | 0.53 |
| 72 | 8,858 | 0.84 | 1.29 | 6.3 | 0.63 |
| 96 | 7,057 | 0.90 | 1.49 | 6.3 | 0.92 |
| 120 | 5,526 | 0.92 | 1.62 | 5.7 | 0.75 |

The spread scale of each bucket makes the median ensemble spread equal to the median error of the ensemble mean on the validation storms.

| Lead (h) | Median error of the mean (km) | Median spread (km) |
| --- | --- | --- |
| 6 | 25 | 25 |
| 12 | 66 | 63 |
| 24 | 128 | 131 |
| 48 | 291 | 291 |
| 72 | 578 | 560 |
| 96 | 970 | 861 |
| 120 | 1,167 | 1,153 |

### Rollout rules

1. Clip the wind speed to the range 15 kt to 165 kt.
2. Over land (`land_distance_km < 0`), multiply the wind speed by exp(-0.07 x 6 h). Then add the model change.
3. If the wind speed stays below 20 kt for 12 h, stop the track.
4. Compute the pressure from the wind speed with the Atkinson-Holliday relation.

### Baseline: CLIPER-lite

CLIPER-lite keeps the last 12-h motion vector. It blends this motion with the mean August-October motion of 1980-2021 in 2.5-degree bins. The weight of the climatology grows from 0 to 1 over 72 h. The wind keeps the 12-h trend with an e-folding time of 24 h, and it decays over land.

### Skill on the validation storms (2015-2021)

| Lead (h) | Cases | Model, deterministic (km) | Model, ensemble mean (km) | CLIPER-lite (km) |
| --- | --- | --- | --- | --- |
| 24 | 776 | 209 | 208 | 238 |
| 48 | 627 | 511 | 501 | 520 |
| 72 | 502 | 835 | 811 | 800 |

These errors include extratropical and high-latitude storms. Thus, they are larger than the errors for tropical storms.

### Verification on Ian

`landfall/predict/verify.py` uses 21 advisory times from 2022-09-23 06Z to 2022-09-28 00Z, every 6 h. For each time, it takes the CARQ `StormState` from Chalk and rolls out 500 members. The table gives the mean error of the ensemble mean against the HURDAT2 truth (`out/verify/summary.json`).

| Lead (h) | Model track (km) | CLIPER-lite track (km) | OFCL track (km) | Model wind (kt) | CLIPER-lite wind (kt) | OFCL wind (kt) | Ensemble spread (km) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 12 | 79 | 77 | 30 | 11.4 | 8.8 | 8.0 | 75 |
| 24 | 180 | 187 | 52 | 21.2 | 11.8 | 9.5 | 177 |
| 48 | 432 | 449 | 118 | 30.6 | 39.6 | 11.0 | 435 |
| 72 | 607 | 635 | 208 | 29.2 | 56.9 | 13.2 | 798 |
| 96 | 497 | 901 | 282 | 26.6 | 56.3 | 17.6 | 1,253 |

The result is the honest expected result. The model beats CLIPER-lite at 24 h to 96 h, and it loses to OFCL at every lead time. At 48 h, the model error is 432 km, the CLIPER-lite error is 449 km, and the OFCL error is 118 km. The margin over CLIPER-lite is small at 12 h to 72 h. NHC had dynamical models and the steering flow, and LANDFALL does not.

The calibration histogram uses the rank of the truth distance among the member distances from the ensemble mean (10 bins, 100 cases). The counts are 13, 5, 4, 12, 3, 18, 12, 7, 12, 14. A flat histogram shows a calibrated spread. Bin 9 holds the cases where the truth is outside most members. The counts are high in bin 0 and in the last bins. Thus, the mean spread is near the error, but some Ian cases fall outside the ensemble.

## Impact model

| Part | Method |
| --- | --- |
| Grid | 500 m cells over the bbox -82.40 to -81.55 E, 26.30 to 26.85 N (122 x 169 cells) |
| Wind | Holland (1980) profile, B = 1.3, gradient-wind form with the Coriolis term. Rmax is 35 km for Category 3 and higher, 50 km for weaker storms. The model adds 60% of the forward speed on the right side. The peak gust is 1.3 times the sustained wind. The model does not reduce the wind over land. |
| Surge | S = C x Vmax^1.7 x max(0.3, cos(approach angle)). The full value applies from 0 to 3 Rmax on the right of the track. It decreases to 0 at 6 Rmax. Land cells up to 15 km from the coast flood if they are lower than the surge. |
| Surge calibration | C = 0.00118. With the default C = 0.0084, the Ian truth track gives 28.6 m at Fort Myers Beach. The fitted C gives 4.0 m. This is a fit at one point. It is not a SLOSH result. |
| Damage | p_major = sigmoid(0.08 x (gust - 95 mph)) x (1 + 0.5 x depth), clipped to 1 |
| Injuries | population x p_major x 0.02 x (1 - evacuated fraction). 10% of the injured persons need a hospital bed. |
| Rescue requests | population x (1 - evacuated fraction) x p(depth > 1 m) x 0.3 |
| Roads | p_blocked = 1 - (1 - p_tree)(1 - p_flood)(1 - p_bridge). p_tree = sigmoid(0.08 x (gust - 80 mph)) x tree cover. p_flood = 1 if depth > 0.3 m. p_bridge = 0.5 for a bridge if the gust is more than 120 mph. |

## Logistics model

| Part | Method |
| --- | --- |
| Scenarios | K = 20 k-medoids scenarios, M = 5 draws each: 100 samples for each plan |
| Release times | Greedy coordinate search over 6-h bins. The objective is W1 x persons not cleared + W3 x rescue demand + W4 x persons evacuated unnecessarily. |
| Shelters | Open a shelter if its chance of flooding is less than 20%. |
| Supply staging | Two-stage stochastic LP with HiGHS. W2 = 50 for each kg of unmet supply, W5 = 0.1 for each tonne-km. |
| Evacuation | Incremental loading in 5 rounds on capacity-aware shortest paths. A point queue for each zone at its most loaded edge. |
| Supply | Recourse LP for each sample with the fixed staging, truck hours, and site storage |
| SAR | OR-Tools VRP with time windows for each asset class. The routing starts at landfall + 6 h. |
| Medevac | Priority 1 and 20% of priority 2 go to the nearest hospital with a free bed. A helicopter uses a helipad hospital. |
| Debris | Greedy schedule of 8 county crews and 4 state crews by priority per hour |
| Objective weights | W1 = 1000, W2 = 50, W3 = 500, W4 = 1, W5 = 0.1 |

## Assumptions

Every assumption is a named constant in `landfall/config.py`. The UI shows the same list in the "Assumptions" drawer.

| Constant | Value | Meaning |
| --- | --- | --- |
| HOLLAND_B | 1.3 | Holland B value |
| RMAX_MAJOR_KM | 35 km | Radius of maximum wind for Category 3 and higher |
| RMAX_OTHER_KM | 50 km | Radius of maximum wind for weaker storms |
| FORWARD_MOTION_FRACTION | 0.6 | Part of the forward speed that the model adds on the right side |
| GUST_FACTOR | 1.3 | Peak gust divided by the sustained wind |
| SURGE_COEFF | 0.0084 (fitted: 0.00118) | Surge constant |
| SURGE_INLAND_KM | 15 km | Maximum inland distance of surge |
| DAMAGE_GUST_MID_MPH | 95 mph (42 m/s) | Gust with a 50% chance of major damage |
| INJURY_RATE | 0.02 | Injuries for each person in a damaged building |
| INJURY_ADMIT_FRACTION | 0.10 | Injured persons that need a hospital bed |
| RESCUE_RATE | 0.3 | Persons in water deeper than 1 m that ask for rescue |
| EVAC_COMPLIANCE | 0.7 (0.55 to 0.85) | Persons in an ordered zone that leave |
| SHADOW_EVAC | 0.15 | Persons in the next zone that also leave |
| DEPARTURE_WINDOW_H | 12 h | Departure period after the order (logistic curve) |
| LANE_CAPACITY_VPH | 1800 veh/h x 0.7 | Capacity of one lane |
| VEHICLES_PER_HOUSEHOLD | 1.3 | Vehicles for each household that leaves |
| PERSONS_PER_HOUSEHOLD | 2.4 | Persons in each household |
| SHELTER_FRACTION | 0.07 | Evacuees that go to a public shelter |
| TRUCK_CAPACITY_KG | 3000 kg (6600 lb) | Load of one truck |
| HOSPITAL_FREE_FRACTION | 0.25 | Free hospital beds at the start |
| HOSPITAL_RECOVERY_PER_DAY | 0.10 | Used beds that become free each day |
| GRID_OUTAGE_GUST_MPH | 100 mph (45 m/s) | Gust that cuts the grid power of a site |
| CLEAR_H_PER_100M | 0.5 h (minimum 1 h) | Time for a crew to clear 100 m of road |
| BRIDGE_REPAIR_DAYS | 30 days | Time to repair a bridge or a washed-out causeway |
| SST_PROXY | 28 - 0.25 max(0, abs(lat) - 10) degC | Sea temperature proxy, with a seasonal term |
| LAND_DECAY_PER_H | 0.07 per h | Wind decay over land |

## Limitations

- The predictor has no environmental data, for example the steering flow or the sea temperature. Thus, it cannot predict a turn that a trough causes.
- The surge model is a proxy. It does not model the bathymetry, the tides, or the waves.
- The DEM is a surface model with buildings and trees. Thus, it underestimates the flood extent in built areas.
- The wind model does not reduce the wind over land.
- The evacuation model does not model the traffic signals, the contraflow, or the timing of each route.
- The curated capacities, inventories, and assets are assumptions.

WARNING: Do not use LANDFALL for operational emergency decisions.
