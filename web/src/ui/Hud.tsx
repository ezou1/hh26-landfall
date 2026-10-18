import { useEffect, useState } from "react";
import { getHourF, pause, play, setSpeed } from "../globe/controller";
import { t } from "../i18n/t";
import { rerunPlan } from "../state/data";
import { earliestTsArrival, windEta } from "../state/derive";
import { setView } from "../state/presets";
import { useStore, type Speed, type View } from "../state/store";
import { fmtIso, fmtLong, fmtNum } from "../time";

const VIEWS: View[] = ["plan", "command", "supply", "rescue", "model"];
const SPEEDS: Speed[] = [0.1, 1, 4, 16];


function useClockMs(): number {
  const t0 = useStore((s) => s.t0Ms);
  const [v, setV] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setV(getHourF()), 250);
    return () => window.clearInterval(id);
  }, []);
  return t0 + v * 3_600_000;
}

/** The top HUD strip: clock, scenario, landfall chance, wind arrival, replay controls, and view tabs. */
export function Hud() {
  const s = useStore();
  const nowMs = useClockMs();
  const sc = s.stage1?.scenarios?.scenarios.find((x) => x.id === s.scenarioId);
  const p = s.stage1?.landfall?.p_landfall_county;
  let eta = earliestTsArrival(s.planScenario?.plan);
  if (!Number.isFinite(eta)) eta = windEta(s.planScenario?.wind, s.meta?.county?.bbox);
  const etaH = (eta - nowMs) / 3_600_000;
  const etaText = !Number.isFinite(eta)
    ? t("hud.etaNone")
    : etaH > 0
      ? t("hud.etaIn", { h: etaH.toFixed(0), time: fmtIso(new Date(eta).toISOString()) })
      : t("hud.etaPassed");
  const fallback = s.fallbackItems.length > 0 || s.fallbackUrls.length > 0;

  return (
    <header className="hud">
      <span className="brand">{t("app.name")}</span>
      <div className="hud-sep" />
      <div className="hud-item">
        <span className="k">{t("hud.clock")}</span>
        <span className="v" data-testid="clock">
          {fmtLong(nowMs).slice(0, 16)}Z
        </span>
      </div>
      <div className="hud-item">
        <span className="k">{t("hud.scenario")}</span>
        <span className="v warn">
          {sc ? `${sc.label} · ${fmtNum(sc.probability * 100, 0)}%` : t("hud.noScenario")}
        </span>
      </div>
      <div className="hud-item">
        <span className="k" title={t("hud.pLandfallTip")}>{t("hud.pLandfall")}</span>
        <span className="v">{p === undefined || p === null ? "—" : `${fmtNum(p * 100, 0)}%`}</span>
      </div>
      <div className="hud-item">
        <span className="k">{t("hud.eta")}</span>
        <span className={`v ${Number.isFinite(eta) && etaH <= 12 ? "bad" : ""}`}>{etaText}</span>
      </div>
      <div className="hud-item">
        <span className="k">{t("hud.advisoryPlan")}</span>
        <span className="v">
          {s.activeAdvisory ? fmtIso(s.activeAdvisory) : "—"}
          <span className="muted"> / </span>
          <span style={{ color: "var(--magenta)" }}>{s.activePlanAdvisory ? fmtIso(s.activePlanAdvisory) : "—"}</span>
        </span>
      </div>
      <div className="hud-sep" />
      <button
        className="btn"
        title={s.playing ? t("hud.pause") : t("hud.play")}
        aria-label={s.playing ? t("hud.pause") : t("hud.play")}
        onClick={() => (s.playing ? pause() : play())}
      >
        {s.playing ? "⏸" : "▶"}
      </button>
      {SPEEDS.map((sp) => (
        <button key={sp} className={`btn sm ${s.speed === sp ? "on" : ""}`} onClick={() => setSpeed(sp)}>
          {sp}×
        </button>
      ))}
      <div className="spacer" />
      <nav className="tabs">
        {VIEWS.map((v) => (
          <button
            key={v}
            className={`tab ${s.view === v ? "on" : ""}`}
            data-testid={`tab-${v}`}
            onClick={() => setView(v)}
          >
            {t(`view.${v}`)}
          </button>
        ))}
      </nav>
      <div className="hud-sep" />
      {fallback && (
        <span
          className="chip fallback"
          data-testid="fallback-chip"
          title={`${t("hud.fallbackTip")} ${s.fallbackItems.join(", ")}`}
        >
          {t("hud.fallback")}
        </span>
      )}
      {!s.ionToken && (
        <span className="chip grey" title={t("hud.noIonTip")}>
          {t("hud.noIon")}
        </span>
      )}
      <button
        className="btn"
        disabled={!s.activeAdvisory || s.rerun.status === "running"}
        title={t("hud.replanTip")}
        onClick={() => void rerunPlan()}
      >
        {s.rerun.status === "running"
          ? t("hud.replanRunning", { pct: Math.round(s.rerun.progress * 100) })
          : s.rerun.status === "error"
            ? t("hud.replanError")
            : t("hud.replan")}
      </button>
      <button className={`btn ${s.assumptionsOpen ? "on" : ""}`} onClick={() => s.set({ assumptionsOpen: !s.assumptionsOpen })}>
        {t("hud.assumptions")}
      </button>
    </header>
  );
}
