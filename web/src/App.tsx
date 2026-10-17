import { useEffect } from "react";
import { GlobeView, HAS_ION_TOKEN } from "./globe/GlobeView";
import { t } from "./i18n/t";
import { initData } from "./state/data";
import { useStore } from "./state/store";
import { AssumptionsDrawer } from "./ui/AssumptionsDrawer";
import { Hud } from "./ui/Hud";
import { LayerRail } from "./ui/LayerRail";
import { CommandPanel } from "./ui/panels/CommandPanel";
import { ModelPanel } from "./ui/panels/ModelPanel";
import { RescuePanel } from "./ui/panels/RescuePanel";
import { SupplyPanel } from "./ui/panels/SupplyPanel";
import { Timeline } from "./ui/Timeline";

let started = false;

/** The root component: HUD, layer rail, globe, right panel, and timeline. */
export function App() {
  const view = useStore((s) => s.view);
  const loadError = useStore((s) => s.loadError);
  const meta = useStore((s) => s.meta);
  const planAdv = useStore((s) => s.activePlanAdvisory);
  const planStatus = useStore((s) => s.planStatus);

  useEffect(() => {
    if (started) return;
    started = true;
    useStore.getState().set({ ionToken: HAS_ION_TOKEN });
    void initData();
  }, []);

  return (
    <div className="app">
      <Hud />
      <LayerRail />
      <main className="globe-wrap">
        <GlobeView />
        <div className="globe-overlay">
          {loadError && <span className="tag bad">{t(loadError)}</span>}
          {!meta && !loadError && <span className="tag">{t("common.loading")}</span>}
          {meta && (
            <span className="tag">
              {meta.storm_name} {meta.storm_id} · {meta.county?.name}
            </span>
          )}
          {meta && planStatus === "missing" && (
            <span className="tag warn" data-testid="no-plan">
              {t("common.noPlan")}
            </span>
          )}
          {planAdv && <span className="tag muted">{t("globe.planFrom", { time: planAdv.slice(0, 16) })}</span>}
        </div>
      </main>
      <aside className="panel">
        {view === "command" && <CommandPanel />}
        {view === "supply" && <SupplyPanel />}
        {view === "rescue" && <RescuePanel />}
        {view === "model" && <ModelPanel />}
      </aside>
      <Timeline />
      <AssumptionsDrawer />
    </div>
  );
}
