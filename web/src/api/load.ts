import { exists, fetchJson, paths } from "./client";
import type {
  Asset,
  Comparison,
  ConeCollection,
  Depot,
  Ensemble,
  FirstStage,
  Hospital,
  Infrastructure,
  Landfall,
  Meta,
  PlanAggregate,
  PlanCommon,
  PlanScenarioBundle,
  RoadCollection,
  ScenarioPlan,
  Scenarios,
  Shelter,
  Stage1Bundle,
  Statics,
  SurgeCollection,
  Truth,
  VerifySummary,
  WindField,
  ZoneCollection,
} from "./types";

function arr<T>(v: T[] | null): T[] {
  return Array.isArray(v) ? v : [];
}

/** Load meta.json from the API. */
export function loadMeta(): Promise<Meta | null> {
  return fetchJson<Meta>(paths.meta());
}

/** Load the static inputs: zones, sites, assets, roads, and the best track. */
export async function loadStatics(): Promise<Statics> {
  const [zones, shelters, hospitals, depots, assets, roads, truth] = await Promise.all([
    fetchJson<ZoneCollection>(paths.zones()),
    fetchJson<Shelter[]>(paths.shelters()),
    fetchJson<Hospital[]>(paths.hospitals()),
    fetchJson<Depot[]>(paths.depots()),
    fetchJson<Asset[]>(paths.assets()),
    fetchJson<RoadCollection>(paths.roads()),
    fetchJson<Truth>(paths.truth()),
  ]);
  return {
    zones,
    shelters: arr(shelters),
    hospitals: arr(hospitals),
    depots: arr(depots),
    assets: arr(assets),
    roads,
    truth,
  };
}

/** Load the verification summary for the Model view. */
export function loadVerify(): Promise<VerifySummary | null> {
  return fetchJson<VerifySummary>(paths.verify());
}

/** Load the four Stage 1 artifacts of one advisory. */
export async function loadStage1(adv: string): Promise<Stage1Bundle> {
  const [ensemble, cone, landfall, scenarios] = await Promise.all([
    fetchJson<Ensemble>(paths.ensemble(adv)),
    fetchJson<ConeCollection>(paths.cone(adv)),
    fetchJson<Landfall>(paths.landfall(adv)),
    fetchJson<Scenarios>(paths.scenarios(adv)),
  ]);
  return { advisory: adv, ensemble, cone, landfall, scenarios };
}

/** Load the plan artifacts that do not depend on the scenario. */
export async function loadPlanCommon(adv: string): Promise<PlanCommon> {
  const [firstStage, aggregate, baseline, comparison, infrastructure] = await Promise.all([
    fetchJson<FirstStage>(paths.firstStage(adv)),
    fetchJson<PlanAggregate>(paths.aggregate(adv)),
    fetchJson<PlanAggregate>(paths.baseline(adv)),
    fetchJson<Comparison>(paths.comparison(adv)),
    fetchJson<Infrastructure>(paths.infrastructure(adv)),
  ]);
  return { advisory: adv, firstStage, aggregate, baseline, comparison, infrastructure };
}

const czmlExists = new Map<string, Promise<boolean>>();

/** Load the plan artifacts of one scenario. */
export async function loadPlanScenario(adv: string, id: number): Promise<PlanScenarioBundle> {
  const czml = paths.scenarioCzml(adv, id);
  let ex = czmlExists.get(czml);
  if (!ex) {
    ex = exists(czml);
    czmlExists.set(czml, ex);
  }
  const [plan, wind, surge, hasCzml] = await Promise.all([
    fetchJson<ScenarioPlan>(paths.scenarioPlan(adv, id)),
    fetchJson<WindField>(paths.wind(adv, id)),
    fetchJson<SurgeCollection>(paths.surge(adv, id)),
    ex,
  ]);
  return { advisory: adv, scenarioId: id, plan, wind, surge, czmlUrl: hasCzml ? czml : null };
}

/** Clear the cache of CZML file checks. */
export function clearCzmlChecks(): void {
  czmlExists.clear();
}
