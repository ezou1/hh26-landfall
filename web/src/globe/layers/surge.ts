import type { JulianDate, Viewer } from "cesium";
import type { SurgeCollection } from "../../api/types";
import { ms } from "../../time";
import { areaToHierarchies } from "../geo";
import { css } from "../palette";
import { buildGroundPrimitive, type AreaSpec } from "../prims";
import { SwapPrimitive } from "../swap";
import type { GlobeLayer, ScenarioFrame } from "./types";

/** The surge depth bands in metres and their colors. */
export const SURGE_BANDS: { m: number; color: string; alpha: number }[] = [
  { m: 0.3, color: "#9fd8ff", alpha: 0.3 },
  { m: 1, color: "#4aa8ff", alpha: 0.35 },
  { m: 2, color: "#1f6fe0", alpha: 0.42 },
  { m: 3, color: "#1636a8", alpha: 0.5 },
];

function bandStyle(m: number) {
  let best = SURGE_BANDS[0];
  for (const b of SURGE_BANDS) if (m >= b.m - 1e-6) best = b;
  return best;
}

/** The surge layer: depth bands that show from six hours before the peak time. */
export class SurgeLayer implements GlobeLayer {
  readonly id = "surge" as const;
  private swap!: SwapPrimitive;
  private last: SurgeCollection | null = null;
  private showFromMs = Number.NEGATIVE_INFINITY;
  private visible = true;
  private timeOk: boolean | null = null;

  init(viewer: Viewer): void {
    this.swap = new SwapPrimitive(viewer.scene);
  }

  update(_t: JulianDate, f: ScenarioFrame): void {
    this.swap.tick();
    const surge = f.state.planScenario?.surge ?? null;
    if (surge !== this.last) {
      this.last = surge;
      const areas: AreaSpec[] = [];
      let peak = Number.POSITIVE_INFINITY;
      const feats = [...(surge?.features ?? [])].sort((a, b) => (a.properties?.band_m ?? 0) - (b.properties?.band_m ?? 0));
      feats.forEach((feat, fi) => {
        const m = feat.properties?.band_m ?? 0.3;
        const p = ms(feat.properties?.peak_time ?? null);
        if (Number.isFinite(p)) peak = Math.min(peak, p);
        const st = bandStyle(m);
        areaToHierarchies(feat.geometry).forEach((h, i) =>
          areas.push({ id: `surge:${fi}:${i}`, hierarchy: h, color: css(st.color, st.alpha) }),
        );
      });
      this.showFromMs = Number.isFinite(peak) ? peak - 6 * 3_600_000 : Number.NEGATIVE_INFINITY;
      this.swap.set(buildGroundPrimitive(areas));
    }
    const ok = f.tMs >= this.showFromMs;
    if (ok !== this.timeOk) {
      this.timeOk = ok;
      this.swap.setShow(this.visible && ok);
    }
  }

  setVisible(v: boolean): void {
    this.visible = v;
    this.swap.setShow(v && this.timeOk === true);
  }
}
