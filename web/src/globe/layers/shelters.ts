import {
  Cartesian2,
  Cartesian3,
  Color,
  CustomDataSource,
  Entity,
  LabelCollection,
  LabelStyle,
  NearFarScalar,
  VerticalOrigin,
  type JulianDate,
  type Label,
  type Viewer,
} from "cesium";
import type { ScenarioPlan, Shelter } from "../../api/types";
import { t } from "../../i18n/t";
import { atHour } from "../../time";
import { css, rampGoodBad } from "../palette";
import { Column } from "../prims";
import type { GlobeLayer, ScenarioFrame } from "./types";

const M_PER_PERSON = 1.2;
const MIN_H = 400;
const MAX_H = 9000;

/** Return the drawn height of a shelter for its capacity. */
export function shelterHeight(capacity: number): number {
  return Math.min(MAX_H, Math.max(MIN_H, capacity * M_PER_PERSON));
}

interface Item {
  shelter: Shelter;
  fill: Column;
  label: Label;
  height: number;
}

/** The shelter layer: an outer cylinder for capacity and an inner column for occupancy. */
export class SheltersLayer implements GlobeLayer {
  readonly id = "shelters" as const;
  private viewer!: Viewer;
  private ds = new CustomDataSource("shelters");
  private labels = new LabelCollection();
  private items: Item[] = [];
  private lastShelters: Shelter[] | null = null;
  private lastPlan: ScenarioPlan | null | undefined = undefined;
  private lastHour = -1;
  private visible = true;

  init(viewer: Viewer): void {
    this.viewer = viewer;
    void viewer.dataSources.add(this.ds);
    viewer.scene.primitives.add(this.labels);
  }

  private build(shelters: Shelter[]): void {
    for (const it of this.items) it.fill.destroy();
    this.items = [];
    this.ds.entities.removeAll();
    this.labels.removeAll();
    for (const s of shelters) {
      if (!Number.isFinite(s.lon) || !Number.isFinite(s.lat)) continue;
      const h = shelterHeight(s.capacity);
      this.ds.entities.add(
        new Entity({
          id: `shelter:${s.id}`,
          position: Cartesian3.fromDegrees(s.lon, s.lat, h / 2),
          cylinder: {
            length: h,
            topRadius: 900,
            bottomRadius: 900,
            material: css("#cfe8ff", 0.12),
            outline: true,
            outlineColor: css("#cfe8ff", 0.5),
            slices: 24,
            numberOfVerticalLines: 0,
          },
        }),
      );
      const fill = new Column(this.viewer.scene, s.lon, s.lat, 700, css("#3ddc84", 0.9));
      fill.setShow(this.visible);
      const label = this.labels.add({
        position: Cartesian3.fromDegrees(s.lon, s.lat, h + 200),
        text: s.name,
        font: "12px 'JetBrains Mono', monospace",
        fillColor: Color.WHITE,
        outlineColor: Color.BLACK,
        outlineWidth: 3,
        style: LabelStyle.FILL_AND_OUTLINE,
        verticalOrigin: VerticalOrigin.BOTTOM,
        pixelOffset: new Cartesian2(0, -2),
        scaleByDistance: new NearFarScalar(2e4, 1.0, 2e5, 0.5),
        translucencyByDistance: new NearFarScalar(1.2e5, 1.0, 3.5e5, 0.0),
      });
      this.items.push({ shelter: s, fill, label, height: h });
    }
  }

  update(_t: JulianDate, f: ScenarioFrame): void {
    const shelters = f.state.statics?.shelters ?? null;
    if (shelters !== this.lastShelters) {
      this.lastShelters = shelters;
      this.build(shelters ?? []);
      this.lastHour = -1;
    }
    const plan = f.state.planScenario?.plan ?? null;
    for (const it of this.items) it.fill.flush();
    if (plan === this.lastPlan && f.hour === this.lastHour) return;
    this.lastPlan = plan;
    this.lastHour = f.hour;
    for (const it of this.items) {
      const sp = plan?.shelters.find((x) => x.id === it.shelter.id);
      const cap = sp?.capacity || it.shelter.capacity || 1;
      const occ = sp ? (atHour(sp.occupancy, f.hour) ?? 0) : 0;
      const frac = Math.max(0, occ / cap);
      it.fill.setHeight(it.height * Math.min(1, frac));
      it.fill.setColor(sp && !sp.open ? css("#7d8b99", 0.8) : rampGoodBad(frac, 0.9));
      const pct = Math.round(frac * 100);
      it.label.text =
        sp && !sp.open
          ? t("globe.shelterClosed", { name: it.shelter.name })
          : t("globe.shelterLabel", { name: it.shelter.name, pct });
    }
  }

  setVisible(v: boolean): void {
    this.visible = v;
    this.ds.show = v;
    this.labels.show = v;
    for (const it of this.items) it.fill.setShow(v);
  }
}
