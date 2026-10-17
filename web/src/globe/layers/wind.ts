import type { JulianDate, Viewer } from "cesium";
import type { WindField, WindThreshold } from "../../api/types";
import { ms } from "../../time";
import { ringsToHierarchy } from "../geo";
import { css } from "../palette";
import { buildGroundPrimitive, type AreaSpec } from "../prims";
import { SwapPrimitive } from "../swap";
import { bracket } from "../track";
import type { GlobeLayer, ScenarioFrame } from "./types";

/** The wind thresholds in knots and their fill colors. */
export const WIND_LEVELS: { kt: WindThreshold; color: string; alpha: number }[] = [
  { kt: "34", color: "#5ee4ff", alpha: 0.14 },
  { kt: "50", color: "#ffe14d", alpha: 0.18 },
  { kt: "64", color: "#ff8a1c", alpha: 0.22 },
  { kt: "96", color: "#ff2a6a", alpha: 0.28 },
];

const timesCache = new WeakMap<WindField, number[]>();

/** The wind field layer: rings of 34, 50, 64, and 96 kt for the selected scenario and hour. */
export class WindLayer implements GlobeLayer {
  readonly id = "wind" as const;
  private swap!: SwapPrimitive;
  private lastWind: WindField | null = null;
  private lastIndex = -2;

  init(viewer: Viewer): void {
    this.swap = new SwapPrimitive(viewer.scene);
  }

  update(_t: JulianDate, f: ScenarioFrame): void {
    this.swap.tick();
    const wind = f.state.planScenario?.wind ?? null;
    let idx = -1;
    if (wind && Array.isArray(wind.times) && wind.times.length > 0) {
      let times = timesCache.get(wind);
      if (!times) {
        times = wind.times.map((x) => ms(x));
        timesCache.set(wind, times);
      }
      idx = bracket(times, f.tMs + 1);
      if (idx >= 0 && f.tMs - times[idx] > 3 * 3_600_000) idx = -1;
    } else if (wind) {
      idx = f.hour;
    }
    if (wind === this.lastWind && idx === this.lastIndex) return;
    this.lastWind = wind;
    this.lastIndex = idx;
    if (!wind || idx < 0) {
      this.swap.set(null);
      return;
    }
    const areas: AreaSpec[] = [];
    for (const lvl of WIND_LEVELS) {
      const ring = wind.rings?.[lvl.kt]?.[idx];
      if (!ring) continue;
      const h = ringsToHierarchy([ring]);
      if (h) areas.push({ id: `wind:${lvl.kt}`, hierarchy: h, color: css(lvl.color, lvl.alpha) });
    }
    this.swap.set(buildGroundPrimitive(areas));
  }

  setVisible(v: boolean): void {
    this.swap.setShow(v);
  }
}
