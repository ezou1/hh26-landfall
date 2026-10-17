import {
  BillboardCollection,
  Cartesian2,
  Cartesian3,
  Color,
  LabelCollection,
  LabelStyle,
  Material,
  NearFarScalar,
  PolylineCollection,
  type JulianDate,
  type Polyline,
  type Viewer,
} from "cesium";
import type { Depot, ScenarioPlan, Shipment } from "../../api/types";
import { ms } from "../../time";
import { cleanLine, toCartesians } from "../geo";
import { depotIcon } from "../icons";
import { css } from "../palette";
import type { GlobeLayer, ScenarioFrame } from "./types";

interface Route {
  s: Shipment;
  line: Polyline;
  depart: number;
  arrive: number;
}

/** The supply layer: depot icons and the routes of trucks on the road. The trucks come from CZML. */
export class SupplyLayer implements GlobeLayer {
  readonly id = "supply" as const;
  private billboards = new BillboardCollection();
  private labels = new LabelCollection();
  private routes = new PolylineCollection();
  private items: Route[] = [];
  private lastDepots: Depot[] | null = null;
  private lastPlan: ScenarioPlan | null = null;
  private lastHourF = Number.NaN;

  init(viewer: Viewer): void {
    viewer.scene.primitives.add(this.routes);
    viewer.scene.primitives.add(this.billboards);
    viewer.scene.primitives.add(this.labels);
  }

  update(_t: JulianDate, f: ScenarioFrame): void {
    const depots = f.state.statics?.depots ?? null;
    if (depots !== this.lastDepots) {
      this.lastDepots = depots;
      this.billboards.removeAll();
      this.labels.removeAll();
      for (const d of depots ?? []) {
        if (!Number.isFinite(d.lon) || !Number.isFinite(d.lat)) continue;
        const pos = Cartesian3.fromDegrees(d.lon, d.lat, 50);
        this.billboards.add({
          position: pos,
          image: depotIcon(d.kind),
          width: 22,
          height: 22,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
          id: `depot:${d.id}`,
        });
        this.labels.add({
          position: pos,
          text: d.name,
          font: "11px 'JetBrains Mono', monospace",
          fillColor: css("#bfe9ff"),
          outlineColor: Color.BLACK,
          outlineWidth: 3,
          style: LabelStyle.FILL_AND_OUTLINE,
          pixelOffset: new Cartesian2(0, 18),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
          translucencyByDistance: new NearFarScalar(5e4, 1.0, 9e4, 0.0),
        });
      }
    }
    const plan = f.state.planScenario?.plan ?? null;
    if (plan !== this.lastPlan) {
      this.lastPlan = plan;
      this.routes.removeAll();
      this.items = [];
      this.lastHourF = Number.NaN;
      for (const s of plan?.shipments ?? []) {
        const path = cleanLine(s.path);
        if (path.length < 2) continue;
        const line = this.routes.add({
          positions: toCartesians(path, 40),
          width: 2,
          material: Material.fromType("Color", { color: css("#7cf29a", 0.35) }),
          show: false,
        });
        this.items.push({ s, line, depart: ms(s.depart_t), arrive: ms(s.arrive_t) });
      }
    }
    // Show the route of each truck while it travels.
    const q = Math.floor(f.hourF * 4);
    if (q === this.lastHourF) return;
    this.lastHourF = q;
    for (const r of this.items) r.line.show = f.tMs >= r.depart && f.tMs <= r.arrive;
  }

  setVisible(v: boolean): void {
    this.billboards.show = v;
    this.labels.show = v;
    this.routes.show = v;
  }
}
