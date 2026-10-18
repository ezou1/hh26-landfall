# Decisions

This file records the decisions that the build prompt did not fix. Each entry gives the decision and the reason.

## Compute and model

- **No GPU.** The build machine has no NVIDIA GPU. The 5 MLP members train on the CPU in about 6 minutes in total. The size of the model did not change (3 layers of 256 units).
- **Bagged MLP.** The predictor is the mean of 5 MLP members with different seeds. We compared 3 configurations on the 2015-2021 validation storms. The 48-h ensemble errors of 1 member and 5 members were about equal (500 km and 501 km). The 5-member model had a lower deterministic error (511 km, not 514 km) and a lower validation loss. Input noise did not help. We did not tune on Ian.
- **Residual sampling.** At each step, the sampler draws one residual vector from the bank of the lead-time bucket and the latitude band of the member. The first sampler drew a full residual sequence of one validation case for each member. That sampler replaced the model skill with the motion of other storms, so we removed it.
- **Spread calibration.** A scale factor for each bucket makes the median ensemble spread equal to the median error of the ensemble mean on the validation storms. The calibration uses only the 2015-2021 storms.
- **Residuals at the rolled state.** The residual of step k is the true 6-h change minus the model change at the state of a deterministic rollout. Thus, the residuals grow with lead time, as the prompt requires.
- **Start state from Chalk.** The ensemble starts from the online `StormState` of Chalk. The position at -18 h is the mean of the -12 h and -24 h positions, because `StormState` has no 18-h lag.

## Wind, surge, and damage

- **Gradient-wind Holland profile.** The field uses the Holland (1980) profile with the Coriolis term, scaled so that V(Rmax) = Vmax. The pure formula of the prompt puts the 34-kt wind about 380 km from the centre. Then the tropical-storm winds reach Lee County about 1 day too early. With the Coriolis term, the radius is about 230 km. The function `holland()` keeps the exact formula of the prompt, and the tests check it at r = Rmax.
- **Wind asymmetry.** The model adds 60% of the forward speed times the cosine of the angle from the right of the motion, on the right half only.
- **Surge calibration.** The default constant 0.0084 gives 28.6 m at Fort Myers Beach for the Ian truth track. The pipeline fits the constant so that the truth track gives 4.0 m at Fort Myers Beach. The fitted value is about 0.00118.
- **Surge geometry.** The onshore direction of the Lee County coast is 75 degrees. On the left of the track, the surge decreases to 0 at 1 Rmax.
- **Causeways.** A causeway segment over water floods if the surge minus the ground elevation minus 1 m is more than 0.3 m. A bridge deck does not flood. A flooded critical link is a washout. It needs a 30-day repair, as Ian did to the Sanibel Causeway and the Matlacha Pass bridge.
- **Tree cover.** The repository has no land-cover data. The tree-cover proxy depends on the road class: 0.02 for a motorway, 0.10 for a primary road, 0.25 for a tertiary road, and 0.35 for other roads.
- **Hospital admissions.** 10% of the injured persons of the damage model need a hospital bed.

## Logistics

- **Release search.** The first stage does not solve one large LP for the release times. A greedy coordinate search tries 6-h bins for each zone. It uses 2 passes and the LP for supply only. The prompt allows this choice.
- **Persons not cleared.** This metric counts the persons in flooded areas that are still in the area when the tropical-storm wind arrives. A first version counted only the evacuees. With that version, the best plan was to order no evacuation.
- **Persons evacuated unnecessarily.** This metric counts the cleared evacuees from block groups that do not flood in the scenario.
- **Evacuation queue.** A point queue for each zone moves the vehicles through the most loaded edge of the zone. Only an edge with 10% or more of the zone vehicles can limit the zone.
- **Shelter share.** 7% of the evacuees go to a public shelter. The other evacuees leave the county by I-75 N, I-75 S, or SR-80 E.
- **Baseline plan.** The baseline orders zones by the category of the OFCL forecast: zone A at Category 1, B at Category 2, and so on. The order comes 12 h after the advisory. The baseline stages the expected demand at the county depots by population. The state depot holds the rest.
- **Supply storage.** A site can store supplies. Thus, a delivery before the storm can cover the demand of a later window. During the storm (from the arrival of tropical-storm winds to landfall + 6 h), trucks do not move.
- **Planning roads.** The first-stage LP uses one sampled set of blocked edges for each scenario and the debris schedule of that set (a sample-average approximation). The test with a threshold of p_blocked >= 0.5 gave staging that was too optimistic.
- **Orlando depot.** The state depot in Orlando enters the road graph at the I-75 N exit with 3.5 h of extra travel time.
- **SAR tasks.** A task holds 2 to 8 persons. If a sample has more than 400 tasks, the pipeline merges tasks and keeps the total of persons. Each helicopter flies sorties of one endurance, with 1 h on the ground between sorties.
- **SAR start in a cell.** A rescue task starts at landfall + 6 h, or 1 h after the last hurricane-force wind in its cell, if that is later. The prompt uses the end of the 34-kt wind. The wind model does not reduce the wind over land, so the 34-kt wind stays for 34 h to 47 h over the county. With that rule, rescue work started only near the end of the clock.
- **SAR travel times.** Boats travel in straight lines with a detour factor of 1.3. Helicopters travel on great circles. High-water trucks use the road graph at 40 km/h, with the edges that are closed 12 h after the start of SAR.

## Data and UI

- **Census population.** The Census API needs a key now. Without `CENSUS_API_KEY`, the pipeline reads the keyless ACS summary-file tables B01003 and B08201. These are real data, not a fallback.
- **Road graph.** The routing graph keeps the tertiary and higher road classes, every bridge, and every causeway. It is the largest strongly connected part of that network.
- **Chalk project folder.** The folder `chalk/` has no `__init__.py`. Thus, `import chalk` always loads the chalkpy package. The pipeline imports the modules of `chalk/` by path.
- **Chalk Compute.** The `@chalkcompute.function` wrapper deploys a function when Python reads the decorator. Thus, `chalk/compute.py` applies the decorator only in remote mode, with credentials, and with `CHALK_COMPUTE=1`. A test on 2026-10-17 registered a probe function, but Chalk did not start it: "scaling-groups at capacity: 100 of 100 admitted". This is a limit of the account plan. Thus, Compute is off by default, and the batches run with joblib.
- **Chalk project root.** The Chalk project is the folder `chalk/`, with its own `chalk.yaml` and `requirements.txt`. With the repository root as the project, `chalk apply` would import the full pipeline, and the folder name `chalk` would hide the chalkpy package.
- **Chalk data bundle.** The deployed resolvers cannot read `data/cache/`. `scripts/chalk_bundle.py` copies the HURDAT2 and CARQ fixes (284 KB), the land-distance grid, and the SST grid to `chalk/data/`. In local mode, the resolvers read the repository files first.
- **Chalk requirements.** The Chalk runtime needs pyarrow 24 or newer. Thus, `chalk/requirements.txt` uses version ranges, not exact pins.
- **Training labels in Chalk.** In an offline query, Chalk shows a has-many relation only up to the row time. This is the point-in-time rule. A 6-h label needs the next fix, so the offline resolver `storm_targets` reads the fixes of the storm directly by storm id. No online resolver reads a future fix.
- **Chalk primary key.** A Chalk query must contain the primary key `StormState.id`. The pipeline sends "storm id:fix source:time".
- **Remote check.** On 2026-10-17, the remote online query for Ian at 2022-09-27 00Z gave the same 19 features as the local runtime. The remote offline query of the full training frame (18,100 rows, 416 s) gave the same features and labels as the local runtime. The maximum difference was less than 1e-6.
- **No ion token.** If `CESIUM_ION_TOKEN` is empty, the globe uses an ellipsoid and Esri World Imagery. Cesium World Terrain also needs an ion token.
- **Stage 2-3 advisories.** The pipeline precomputes Stage 2-3 for 2022-09-25 00Z, 2022-09-27 00Z, and 2022-09-28 00Z. This is stretch item 2.
- **Plan view.** The UI has a Plan tab. It lists the actions of the evacuation lead and the supply lead in time order: zone orders, shelters to open, supplies to stage, deliveries by depot and site, the truck hold during the storm, critical road blocks, and unmet demand. A click on a line shows only that item on the globe. The tab reads the existing plan artifacts; the backend did not change.
- **Layer presets by view.** Each tab opens with its own set of layers. The Command tab shows all layers. The Plan tab shows the storm, the zones, the evacuation flow, the shelters, the depots, and the road status. The rail can change the layers after that.
