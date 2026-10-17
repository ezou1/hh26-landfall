import {
  BillboardCollection,
  Cartesian2,
  Cartesian3,
  Color,
  LabelCollection,
  LabelStyle,
  NearFarScalar,
  VerticalOrigin,
  type Billboard,
  type JulianDate,
  type Label,
  type Viewer,
} from "cesium";
import type { Hospital, ScenarioPlan } from "../../api/types";
import { t } from "../../i18n/t";
import { atHour } from "../../time";
import { redCrossIcon } from "../icons";
import { css } from "../palette";
import { Column } from "../prims";
import type { GlobeLayer, ScenarioFrame } from "./types";

const M_PER_BED = 12;

interface Item {
  hospital: Hospital;
  column: Column;
  icon: Billboard;
  label: Label;
}

/** The hospital layer: a red-cross icon and a column for the beds available. */
export class HospitalsLayer implements GlobeLayer {
  readonly id = "hospitals" as const;
  private viewer!: Viewer;
  private billboards = new BillboardCollection();
  private labels = new LabelCollection();
  private items: Item[] = [];
  private lastHospitals: Hospital[] | null = null;
  private lastPlan: ScenarioPlan | null | undefined = undefined;
  private lastHour = -1;
  private visible = true;

  init(viewer: Viewer): void {
    this.viewer = viewer;
    viewer.scene.primitives.add(this.billboards);
    viewer.scene.primitives.add(this.labels);
  }

  private build(list: Hospital[]): void {
    for (const it of this.items) it.column.destroy();
    this.items = [];
    this.billboards.removeAll();
    this.labels.removeAll();
    for (const h of list) {
      if (!Number.isFinite(h.lon) || !Number.isFinite(h.lat)) continue;
      const column = new Column(this.viewer.scene, h.lon, h.lat, 450, css("#ff5a6a", 0.75));
      column.setShow(this.visible);
      const icon = this.billboards.add({
        position: Cartesian3.fromDegrees(h.lon, h.lat, 50),
        image: redCrossIcon(),
        width: 22,
        height: 22,
        verticalOrigin: VerticalOrigin.CENTER,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
        id: `hospital:${h.id}`,
      });
      const label = this.labels.add({
        position: Cartesian3.fromDegrees(h.lon, h.lat, 50),
        text: h.name,
        font: "11px 'JetBrains Mono', monospace",
        fillColor: css("#ffd0d4"),
        outlineColor: Color.BLACK,
        outlineWidth: 3,
        style: LabelStyle.FILL_AND_OUTLINE,
        verticalOrigin: VerticalOrigin.TOP,
        pixelOffset: new Cartesian2(0, 14),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
        translucencyByDistance: new NearFarScalar(5e4, 1.0, 9e4, 0.0),
      });
      this.items.push({ hospital: h, column, icon, label });
    }
  }

  update(_t: JulianDate, f: ScenarioFrame): void {
    const list = f.state.statics?.hospitals ?? null;
    if (list !== this.lastHospitals) {
      this.lastHospitals = list;
      this.build(list ?? []);
      this.lastHour = -1;
    }
    const plan = f.state.planScenario?.plan ?? null;
    for (const it of this.items) it.column.flush();
    if (plan === this.lastPlan && f.hour === this.lastHour) return;
    this.lastPlan = plan;
    this.lastHour = f.hour;
    for (const it of this.items) {
      const hp = plan?.hospitals.find((x) => x.id === it.hospital.id);
      const total = hp?.beds_total || it.hospital.beds || 0;
      const avail = hp ? (atHour(hp.beds_available, f.hour) ?? total) : total;
      it.column.setHeight(Math.max(0, avail) * M_PER_BED);
      const frac = total > 0 ? avail / total : 0;
      it.column.setColor(frac < 0.1 ? css("#ff2a2a", 0.9) : frac < 0.3 ? css("#ffb300", 0.8) : css("#ff7a8a", 0.7));
      it.label.text = t("globe.hospitalLabel", { name: it.hospital.name, beds: Math.round(avail) });
    }
  }

  setVisible(v: boolean): void {
    this.visible = v;
    this.billboards.show = v;
    this.labels.show = v;
    for (const it of this.items) it.column.setShow(v);
  }
}
