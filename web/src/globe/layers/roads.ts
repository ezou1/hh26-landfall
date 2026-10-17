import type { JulianDate, Primitive, Viewer } from "cesium";
import type { RoadCollection, RoadStatus, ScenarioPlan } from "../../api/types";
import { ms } from "../../time";
import { cleanLine, lineGeomToPaths } from "../geo";
import { css, STATUS } from "../palette";
import { buildLinePrimitive, setInstanceColor, setInstanceShow, type LineSpec } from "../prims";
import { SwapPrimitive } from "../swap";
import type { GlobeLayer, ScenarioFrame } from "./types";

export type RoadState = "clear" | "blocked" | "reopened";

/** Return the state of a road edge at a time. */
export function roadState(r: RoadStatus, tMs: number): RoadState {
  const b = ms(r.blocked_t);
  if (!Number.isFinite(b) || tMs < b) return "clear";
  const o = ms(r.reopen_t);
  if (Number.isFinite(o) && tMs >= o) return "reopened";
  return "blocked";
}

const BLOCKED = css(STATUS.bad, 1);
const REOPENED = css(STATUS.ok, 1);

/** The road layer: the display network, and edge status from the selected scenario. */
export class RoadsLayer implements GlobeLayer {
  readonly id = "roads" as const;
  private base!: SwapPrimitive<Primitive>;
  private status!: SwapPrimitive<Primitive>;
  private lastRoads: RoadCollection | null = null;
  private lastPlan: ScenarioPlan | null = null;
  private lastKey = "";
  private lastPrim: Primitive | null = null;

  init(viewer: Viewer): void {
    this.base = new SwapPrimitive<Primitive>(viewer.scene);
    this.status = new SwapPrimitive<Primitive>(viewer.scene);
  }

  update(_t: JulianDate, f: ScenarioFrame): void {
    this.base.tick();
    this.status.tick();
    const roads = f.state.statics?.roads ?? null;
    if (roads !== this.lastRoads) {
      this.lastRoads = roads;
      const lines: LineSpec[] = [];
      (roads?.features ?? []).forEach((feat, fi) => {
        const p = feat.properties;
        const crit = !!p?.is_critical;
        const major = p?.highway === "motorway" || p?.highway === "trunk";
        lineGeomToPaths(feat.geometry).forEach((path, i) =>
          lines.push({
            id: `road:${p?.edge_id ?? fi}:${i}`,
            path,
            color: crit ? css("#e6f1ff", 0.85) : css(major ? "#b8c7d6" : "#8a9bab", major ? 0.7 : 0.5),
            width: crit ? 3.5 : major ? 2 : 1.2,
            height: 20,
          }),
        );
      });
      this.base.set(buildLinePrimitive(lines, true));
    }
    const plan = f.state.planScenario?.plan ?? null;
    if (plan !== this.lastPlan) {
      this.lastPlan = plan;
      this.lastKey = "";
      const lines: LineSpec[] = [];
      (plan?.road_status ?? []).forEach((r, i) => {
        const path = cleanLine(r.path);
        if (path.length < 2) return;
        lines.push({ id: `rs:${i}`, path, color: BLOCKED, width: r.is_critical ? 6 : 3.5, height: 35, show: false });
      });
      this.status.set(buildLinePrimitive(lines, false));
    }
    const prim = this.status.active;
    if (!prim || !prim.ready || !plan) return;
    const states = plan.road_status.map((r) => roadState(r, f.tMs));
    const key = states.join("");
    if (key === this.lastKey && prim === this.lastPrim) return;
    this.lastKey = key;
    this.lastPrim = prim;
    states.forEach((s, i) => {
      const id = `rs:${i}`;
      setInstanceShow(prim, id, s !== "clear");
      if (s !== "clear") setInstanceColor(prim, id, s === "blocked" ? BLOCKED : REOPENED);
    });
  }

  setVisible(v: boolean): void {
    this.base.setShow(v);
    this.status.setShow(v);
  }
}
