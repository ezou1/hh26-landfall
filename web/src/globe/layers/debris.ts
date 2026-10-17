import { Material, PolylineCollection, type JulianDate, type Polyline, type Viewer } from "cesium";
import type { RoadStatus, ScenarioPlan } from "../../api/types";
import { cleanLine, toCartesians } from "../geo";
import { css, STATUS } from "../palette";
import { roadState } from "./roads";
import type { GlobeLayer, ScenarioFrame } from "./types";

interface Item {
  r: RoadStatus;
  line: Polyline;
  state: string;
}

/**
 * The debris layer: the edges that crews clear. Each edge turns from red to green when it opens again.
 * The crews come from CZML.
 */
export class DebrisLayer implements GlobeLayer {
  readonly id = "debris" as const;
  private coll = new PolylineCollection();
  private items: Item[] = [];
  private lastPlan: ScenarioPlan | null = null;

  init(viewer: Viewer): void {
    viewer.scene.primitives.add(this.coll);
  }

  update(_t: JulianDate, f: ScenarioFrame): void {
    const plan = f.state.planScenario?.plan ?? null;
    if (plan !== this.lastPlan) {
      this.lastPlan = plan;
      this.coll.removeAll();
      this.items = [];
      const worked = new Set<string>();
      for (const c of plan?.debris_crews ?? []) for (const w of c.waypoints ?? []) if (w.edge_id) worked.add(w.edge_id);
      for (const r of plan?.road_status ?? []) {
        // Without crew edge ids, show each blocked edge that opens again.
        if (worked.size === 0 ? r.reopen_t === null : !worked.has(r.edge_id)) continue;
        const path = cleanLine(r.path);
        if (path.length < 2) continue;
        const line = this.coll.add({
          positions: toCartesians(path, 45),
          width: r.is_critical ? 9 : 6,
          material: Material.fromType("PolylineOutline", {
            color: css(STATUS.bad, 0.9),
            outlineColor: css("#000000", 0.6),
            outlineWidth: 1.5,
          }),
          show: false,
        });
        this.items.push({ r, line, state: "" });
      }
    }
    for (const it of this.items) {
      const s = roadState(it.r, f.tMs);
      if (s === it.state) continue;
      it.state = s;
      it.line.show = s !== "clear";
      (it.line.material.uniforms as { color: unknown }).color = css(s === "reopened" ? STATUS.ok : STATUS.bad, 0.9);
    }
  }

  setVisible(v: boolean): void {
    this.coll.show = v;
  }
}
