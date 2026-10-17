import { clearCache, onFallback, rerunStatus, startRerun } from "../api/client";
import { clearCzmlChecks, loadMeta, loadPlanCommon, loadPlanScenario, loadStage1, loadStatics, loadVerify } from "../api/load";
import { ms } from "../time";
import { useStore } from "./store";

let requestedAdvisory: string | null = null;
let requestedPlanKey: string | null = null;
let requestedCommon: string | null = null;

/** Return the latest advisory that is not later than the time. Return the first advisory if none. */
export function advisoryAt(advisories: string[], tMs: number): string | null {
  if (advisories.length === 0) return null;
  let best = advisories[0];
  for (const a of advisories) {
    if (ms(a) <= tMs) best = a;
  }
  return best;
}

/** Return the plan advisory for a Stage 1 advisory. */
export function planAdvisoryFor(adv: string | null): string | null {
  const meta = useStore.getState().meta;
  if (!meta) return null;
  const plans = [...(meta.plan_advisories ?? [])].sort((a, b) => ms(a) - ms(b));
  if (adv) {
    let best: string | null = null;
    for (const p of plans) if (ms(p) <= ms(adv)) best = p;
    if (best) return best;
  }
  return meta.default_plan_advisory ?? plans[0] ?? null;
}

/** Load the Stage 1 data of an advisory and make it active when it arrives. */
export function requestAdvisory(adv: string | null): void {
  if (!adv || adv === requestedAdvisory) return;
  requestedAdvisory = adv;
  void loadStage1(adv).then((bundle) => {
    if (requestedAdvisory !== adv) return;
    const s = useStore.getState();
    const ids = bundle.scenarios?.scenarios.map((x) => x.id) ?? [];
    const patch: Parameters<typeof s.set>[0] = { stage1: bundle, activeAdvisory: adv };
    if (ids.length > 0 && !ids.includes(s.scenarioId)) patch.scenarioId = ids[0];
    s.set(patch);
    requestPlan();
  });
  requestPlan(adv);
}

/** Load the plan data for the active plan advisory and the selected scenario. */
export function requestPlan(advOverride?: string): void {
  const s = useStore.getState();
  const plan = planAdvisoryFor(advOverride ?? requestedAdvisory ?? s.activeAdvisory);
  if (!plan) {
    s.set({ activePlanAdvisory: null, planCommon: null, planScenario: null, planStatus: "missing" });
    return;
  }
  if (plan !== requestedCommon) {
    requestedCommon = plan;
    void loadPlanCommon(plan).then((common) => {
      if (requestedCommon !== plan) return;
      const st = useStore.getState();
      st.set({ planCommon: common, activePlanAdvisory: plan });
    });
  }
  const id = s.scenarioId;
  const key = `${plan}|${id}`;
  if (key === requestedPlanKey) return;
  requestedPlanKey = key;
  if (!s.planScenario) s.set({ planStatus: "loading" });
  void loadPlanScenario(plan, id).then((bundle) => {
    if (requestedPlanKey !== key) return;
    useStore.getState().set({
      planScenario: bundle,
      activePlanAdvisory: plan,
      planStatus: bundle.plan ? "ok" : "missing",
    });
  });
}

/** Load meta, the static data, and the first advisory. */
export async function initData(): Promise<void> {
  const st = useStore.getState();
  onFallback((url, items) => useStore.getState().addFallback(url, items));
  const meta = await loadMeta();
  if (!meta) {
    st.set({ loadError: "load.noMeta" });
    return;
  }
  const advisories = [...(meta.advisories ?? [])].sort((a, b) => ms(a) - ms(b));
  meta.advisories = advisories;
  st.set({ meta, t0Ms: ms(meta.t0), tEndMs: ms(meta.t_end) });
  const [statics, verify] = await Promise.all([loadStatics(), loadVerify()]);
  useStore.getState().set({ statics, verify });
  requestAdvisory(advisoryAt(advisories, ms(meta.t0)));
  // Load the other advisories in the background, so that the cone changes without delay.
  void (async () => {
    for (const a of advisories) {
      await loadStage1(a);
    }
  })();
}

/** Select a scenario and load its plan data. */
export function selectScenario(id: number): void {
  useStore.getState().set({ scenarioId: id });
  requestPlan();
}

/** Start a re-plan job for the active advisory and reload the data when it completes. */
export async function rerunPlan(): Promise<void> {
  const st = useStore.getState();
  const adv = st.activeAdvisory;
  if (!adv || st.rerun.status === "running") return;
  const job = await startRerun(adv, false);
  if (!job) {
    st.set({ rerun: { jobId: null, status: "error", progress: 0, message: "rerun.startFailed" } });
    return;
  }
  st.set({ rerun: { jobId: job.job_id, status: "running", progress: 0, message: "" } });
  const poll = async () => {
    const status = await rerunStatus(job.job_id);
    if (!status) {
      useStore.getState().set({ rerun: { jobId: job.job_id, status: "error", progress: 0, message: "rerun.pollFailed" } });
      return;
    }
    useStore.getState().set({
      rerun: { jobId: job.job_id, status: status.status, progress: status.progress, message: status.message },
    });
    if (status.status === "running") {
      window.setTimeout(() => void poll(), 1500);
    } else if (status.status === "done") {
      clearCache();
      clearCzmlChecks();
      requestedAdvisory = null;
      requestedPlanKey = null;
      requestedCommon = null;
      const s = useStore.getState();
      s.set({ fallbackItems: [], fallbackUrls: [] });
      requestAdvisory(adv);
    }
  };
  window.setTimeout(() => void poll(), 1000);
}
