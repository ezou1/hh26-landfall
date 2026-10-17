import { home } from "../globe/controller";
import { SURGE_BANDS } from "../globe/layers/surge";
import { WIND_LEVELS } from "../globe/layers/wind";
import { t } from "../i18n/t";
import { LAYER_IDS, useStore, type LayerId } from "../state/store";

const SWATCH: Record<LayerId, string> = {
  storm: "#ffb300",
  wind: "#ff8a1c",
  surge: "#4aa8ff",
  zones: "#9aa7b4",
  evac: "#3ddc84",
  shelters: "#cfe8ff",
  hospitals: "#ff5a6a",
  supply: "#7cf29a",
  roads: "#b8c7d6",
  sar: "#ff3b30",
  debris: "#ff9f43",
  infra: "#ff3df2",
};

/** The left rail: layer toggles, camera controls, and a short legend. */
export function LayerRail() {
  const layers = useStore((s) => s.layers);
  const toggle = useStore((s) => s.toggleLayer);
  const follow = useStore((s) => s.followStorm);
  const set = useStore((s) => s.set);
  return (
    <aside className="rail">
      <h3>{t("rail.layers")}</h3>
      {LAYER_IDS.map((id) => (
        <button
          key={id}
          className={`layer-btn ${layers[id] ? "on" : ""}`}
          data-testid={`layer-${id}`}
          onClick={() => toggle(id)}
          title={t(`layerTip.${id}`)}
        >
          <span className="sw" style={{ background: layers[id] ? SWATCH[id] : "transparent" }} />
          {t(`layer.${id}`)}
        </button>
      ))}
      <div className="cam">
        <h3>{t("rail.camera")}</h3>
        <button className="btn" onClick={() => home()}>
          {t("rail.home")}
        </button>
        <button className={`btn ${follow ? "on" : ""}`} onClick={() => set({ followStorm: !follow })}>
          {t("rail.follow")}
        </button>
      </div>
      <div className="legend">
        <h3>{t("rail.legend")}</h3>
        {WIND_LEVELS.map((w) => (
          <div className="row" key={w.kt}>
            <span className="sw" style={{ background: w.color, opacity: 0.8 }} />
            {t("legend.wind", { kt: w.kt })}
          </div>
        ))}
        {SURGE_BANDS.map((b) => (
          <div className="row" key={b.m}>
            <span className="sw" style={{ background: b.color }} />
            {t("legend.surge", { m: b.m })}
          </div>
        ))}
        <div className="row">
          <span className="sw" style={{ background: "#9aa7b4" }} />
          {t("legend.zoneNone")}
        </div>
        <div className="row">
          <span className="sw" style={{ background: "var(--warn)" }} />
          {t("legend.zoneOrdered")}
        </div>
        <div className="row">
          <span className="sw" style={{ background: "var(--bad)" }} />
          {t("legend.zoneLate")}
        </div>
        <div className="row">
          <span className="sw" style={{ background: "var(--bad)", height: 3 }} />
          {t("legend.roadBlocked")}
        </div>
        <div className="row">
          <span className="sw" style={{ background: "var(--ok)", height: 3 }} />
          {t("legend.roadOpen")}
        </div>
      </div>
    </aside>
  );
}
