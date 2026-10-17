import { Color, Material, PolylineCollection, type JulianDate, type Polyline, type Viewer } from "cesium";
import type { EvacEdge, ScenarioPlan } from "../../api/types";
import { cleanLine, lineLengthKm, toCartesians } from "../geo";
import { rampGoodBad } from "../palette";
import type { GlobeLayer, ScenarioFrame } from "./types";

const FLOW_SOURCE = `
czm_material czm_getMaterial(czm_materialInput materialInput) {
  czm_material m = czm_getDefaultMaterial(materialInput);
  float f = fract(materialInput.s * repeat - offset);
  float dash = smoothstep(0.0, 0.12, f) * (1.0 - smoothstep(0.45, 0.6, f));
  m.diffuse = color.rgb;
  m.alpha = color.a * (0.3 + 0.7 * dash);
  m.emission = color.rgb * 0.25 * dash;
  return m;
}
`;

function flowMaterial(color: Color, repeat: number): Material {
  return new Material({
    fabric: {
      type: "LandfallFlow",
      uniforms: { color, repeat, offset: 0 },
      source: FLOW_SOURCE,
    },
    translucent: true,
  });
}

interface Item {
  edge: EvacEdge;
  line: Polyline;
  mat: Material;
}

/** The evacuation flow layer: road edges with width by vehicles per hour and color by congestion. */
export class EvacLayer implements GlobeLayer {
  readonly id = "evac" as const;
  private coll = new PolylineCollection();
  private items: Item[] = [];
  private lastPlan: ScenarioPlan | null = null;
  private lastHour = -1;
  private maxVph = 1;

  init(viewer: Viewer): void {
    viewer.scene.primitives.add(this.coll);
  }

  update(_t: JulianDate, f: ScenarioFrame): void {
    const plan = f.state.planScenario?.plan ?? null;
    if (plan !== this.lastPlan) {
      this.lastPlan = plan;
      this.lastHour = -1;
      this.coll.removeAll();
      this.items = [];
      this.maxVph = 1;
      for (const e of plan?.evac_edges ?? []) {
        const path = cleanLine(e.path);
        if (path.length < 2) continue;
        for (const v of e.vph ?? []) if (v > this.maxVph) this.maxVph = v;
        const repeat = Math.max(1, lineLengthKm(path) / 1.2);
        const mat = flowMaterial(Color.WHITE, repeat);
        const line = this.coll.add({ positions: toCartesians(path, 60), width: 2, material: mat, show: false });
        this.items.push({ edge: e, line, mat });
      }
    }
    if (f.hour !== this.lastHour) {
      this.lastHour = f.hour;
      for (const it of this.items) {
        const i = f.hour - (it.edge.h0 ?? 0);
        const vph = i >= 0 && i < (it.edge.vph?.length ?? 0) ? it.edge.vph[i] : 0;
        if (!vph || vph <= 0) {
          it.line.show = false;
          continue;
        }
        it.line.show = true;
        it.line.width = 2 + 10 * Math.min(1, vph / this.maxVph);
        const ratio = it.edge.capacity_vph > 0 ? vph / it.edge.capacity_vph : Number.NaN;
        (it.mat.uniforms as { color: Color }).color = rampGoodBad(ratio, 0.95);
      }
    }
    // Move the dashes to show the direction of travel.
    const off = (performance.now() / 1000) * 0.8;
    for (const it of this.items) if (it.line.show) (it.mat.uniforms as { offset: number }).offset = off;
  }

  setVisible(v: boolean): void {
    this.coll.show = v;
  }
}
