import {
  Cartesian3,
  Color,
  LabelCollection,
  LabelStyle,
  NearFarScalar,
  type GroundPrimitive,
  type JulianDate,
  type Viewer,
} from "cesium";
import type { ScenarioPlan, ZoneCollection } from "../../api/types";
import { t } from "../../i18n/t";
import { zoneStatus, type ZoneStatus } from "../../state/derive";
import { areaCentroid, areaToHierarchies } from "../geo";
import { css, STATUS } from "../palette";
import { buildGroundPrimitive, setInstanceColor, type AreaSpec } from "../prims";
import { SwapPrimitive } from "../swap";
import type { GlobeLayer, ScenarioFrame } from "./types";

/** The fill colors of the zone release states. */
export const ZONE_COLORS: Record<ZoneStatus, Color> = {
  none: css("#9aa7b4", 0.2),
  ordered: css(STATUS.warn, 0.3),
  late: css(STATUS.bad, 0.4),
};

/** The evacuation zone layer: zone polygons colored by release status. */
export class ZonesLayer implements GlobeLayer {
  readonly id = "zones" as const;
  private swap!: SwapPrimitive<GroundPrimitive>;
  private labels = new LabelCollection();
  private lastZones: ZoneCollection | null = null;
  private ids: { id: string; zone: string }[] = [];
  private lastKey = "";
  private lastPlan: ScenarioPlan | null = null;
  private lastPrim: GroundPrimitive | null = null;

  init(viewer: Viewer): void {
    this.swap = new SwapPrimitive<GroundPrimitive>(viewer.scene);
    viewer.scene.primitives.add(this.labels);
  }

  update(_t: JulianDate, f: ScenarioFrame): void {
    this.swap.tick();
    const zones = f.state.statics?.zones ?? null;
    if (zones !== this.lastZones) {
      this.lastZones = zones;
      this.lastKey = "";
      this.ids = [];
      this.labels.removeAll();
      const areas: AreaSpec[] = [];
      (zones?.features ?? []).forEach((feat, fi) => {
        const zone = String(feat.properties?.zone ?? "?");
        areaToHierarchies(feat.geometry).forEach((h, i) => {
          const id = `zone:${zone}:${fi}:${i}`;
          this.ids.push({ id, zone });
          areas.push({ id, hierarchy: h, color: ZONE_COLORS.none });
        });
        const c = areaCentroid(feat.geometry);
        if (c) {
          this.labels.add({
            position: Cartesian3.fromDegrees(c[0], c[1], 200),
            text: t("globe.zoneLabel", { zone }),
            font: "12px 'JetBrains Mono', monospace",
            fillColor: Color.WHITE.withAlpha(0.85),
            outlineColor: Color.BLACK,
            outlineWidth: 3,
            style: LabelStyle.FILL_AND_OUTLINE,
            scaleByDistance: new NearFarScalar(2e4, 1.0, 3e5, 0.4),
            translucencyByDistance: new NearFarScalar(2e5, 1.0, 6e5, 0.0),
          });
        }
      });
      this.swap.set(buildGroundPrimitive(areas));
    }
    const prim = this.swap.active;
    if (!prim || !prim.ready) return;
    const plan = f.state.planScenario?.plan ?? null;
    const release = f.state.planCommon?.firstStage?.release_time ?? {};
    const statuses = new Map<string, ZoneStatus>();
    for (const { zone } of this.ids) {
      if (statuses.has(zone)) continue;
      const zp = plan?.zones.find((z) => z.zone === zone);
      statuses.set(zone, zoneStatus(zp, f.tMs, release[zone] ?? null));
    }
    const key = Array.from(statuses.values()).join(",");
    if (key === this.lastKey && plan === this.lastPlan && prim === this.lastPrim) return;
    this.lastPrim = prim;
    this.lastKey = key;
    this.lastPlan = plan;
    for (const { id, zone } of this.ids) setInstanceColor(prim, id, ZONE_COLORS[statuses.get(zone) ?? "none"]);
  }

  setVisible(v: boolean): void {
    this.swap.setShow(v);
    this.labels.show = v;
  }
}
