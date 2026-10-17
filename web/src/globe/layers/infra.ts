import {
  Cartesian3,
  Color,
  LabelCollection,
  LabelStyle,
  Material,
  PolylineCollection,
  type JulianDate,
  type Viewer,
} from "cesium";
import type { Infrastructure } from "../../api/types";
import { cleanLine, lineMid, toCartesians } from "../geo";
import { css, STATUS } from "../palette";
import type { GlobeLayer, ScenarioFrame } from "./types";

/** The infrastructure layer: the top ten edges to harden, drawn in pulsing magenta. */
export class InfraLayer implements GlobeLayer {
  readonly id = "infra" as const;
  private coll = new PolylineCollection();
  private labels = new LabelCollection();
  private mats: Material[] = [];
  private last: Infrastructure | null = null;
  private visible = false;

  init(viewer: Viewer): void {
    viewer.scene.primitives.add(this.coll);
    viewer.scene.primitives.add(this.labels);
  }

  update(_t: JulianDate, f: ScenarioFrame): void {
    const infra = f.state.planCommon?.infrastructure ?? null;
    if (infra !== this.last) {
      this.last = infra;
      this.coll.removeAll();
      this.labels.removeAll();
      this.mats = [];
      const list = [...(infra?.harden ?? [])].sort((a, b) => a.rank - b.rank).slice(0, 10);
      for (const h of list) {
        const path = cleanLine(h.path);
        if (path.length < 2) continue;
        const mat = Material.fromType("PolylineGlow", { color: css(STATUS.magenta, 1), glowPower: 0.25 });
        this.mats.push(mat);
        this.coll.add({ positions: toCartesians(path, 60), width: 14, material: mat });
        const mid = lineMid(path);
        if (mid) {
          this.labels.add({
            position: Cartesian3.fromDegrees(mid[0], mid[1], 80),
            text: `#${h.rank}`,
            font: "bold 12px 'JetBrains Mono', monospace",
            fillColor: css(STATUS.magenta),
            outlineColor: Color.BLACK,
            outlineWidth: 3,
            style: LabelStyle.FILL_AND_OUTLINE,
            disableDepthTestDistance: Number.POSITIVE_INFINITY,
          });
        }
      }
    }
    if (!this.visible) return;
    const a = 0.45 + 0.55 * (0.5 + 0.5 * Math.sin(performance.now() / 260));
    for (const m of this.mats) (m.uniforms as { color: Color }).color = css(STATUS.magenta, a);
  }

  setVisible(v: boolean): void {
    this.visible = v;
    this.coll.show = v;
    this.labels.show = v;
  }
}
