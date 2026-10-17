import {
  CallbackProperty,
  Cartesian2,
  Cartesian3,
  Color,
  ColorMaterialProperty,
  ConstantProperty,
  CustomDataSource,
  Entity,
  ImageMaterialProperty,
  LabelStyle,
  PolylineDashMaterialProperty,
  VerticalOrigin,
  type JulianDate,
  type Primitive,
  type Viewer,
} from "cesium";
import type { Ensemble, LonLat, Scenario, TrackFix } from "../../api/types";
import { t } from "../../i18n/t";
import { ms } from "../../time";
import { areaToHierarchies, cleanLine, toCartesians } from "../geo";
import { stormSpiral } from "../icons";
import { categoryColor, css } from "../palette";
import { buildGroundPrimitive, buildLinePrimitive, type AreaSpec, type LineSpec } from "../prims";
import { SwapPrimitive } from "../swap";
import { stormAt, type StormState } from "../track";
import type { GlobeLayer, ScenarioFrame } from "./types";

const COLUMN_M_PER_KT = 160;
const CONE_COLORS: Record<string, Color> = {
  p90: css("#ffffff", 0.1),
  p66: css("#cfe8ff", 0.14),
  p50: css("#ffe14d", 0.2),
};
const CONE_EDGE: Record<string, Color> = {
  p90: css("#ffffff", 0.45),
  p66: css("#cfe8ff", 0.65),
  p50: css("#ffe14d", 0.9),
};

function fixesToPath(fixes: TrackFix[]): LonLat[] {
  return cleanLine(fixes.map((f) => [f.lon, f.lat] as LonLat));
}

/** The storm layer: ensemble tracks, the cone, the selected track, and the storm marker. */
export class StormLayer implements GlobeLayer {
  readonly id = "storm" as const;
  private ensemble!: SwapPrimitive<Primitive>;
  private selected!: SwapPrimitive<Primitive>;
  private cone!: SwapPrimitive;
  private coneEdge!: SwapPrimitive<Primitive>;
  private ds = new CustomDataSource("storm");
  private lastEnsemble: Ensemble | null = null;
  private lastCone: unknown = null;
  private lastTrackKey = "";
  private track: TrackFix[] | null = null;
  private now: StormState | null = null;
  private visible = true;
  private observed!: Entity;
  private truthShown = false;

  init(viewer: Viewer): void {
    this.ensemble = new SwapPrimitive(viewer.scene);
    this.selected = new SwapPrimitive(viewer.scene);
    this.cone = new SwapPrimitive(viewer.scene);
    this.coneEdge = new SwapPrimitive(viewer.scene);
    void viewer.dataSources.add(this.ds);
    const pos = new CallbackProperty(() => {
      const s = this.now;
      return s ? Cartesian3.fromDegrees(s.lon, s.lat, 300) : undefined;
    }, false);
    const disc = new Entity({
      id: "storm:disc",
      position: pos,
      ellipse: {
        semiMajorAxis: new CallbackProperty(() => Math.max(5, this.now?.rmaxKm ?? 40) * 1000 * 2.2, false),
        semiMinorAxis: new CallbackProperty(() => Math.max(5, this.now?.rmaxKm ?? 40) * 1000 * 2.2, false),
        height: 300,
        material: new ImageMaterialProperty({ image: stormSpiral(), transparent: true }),
        stRotation: new CallbackProperty(() => -(performance.now() / 1000) * 0.6, false),
      },
    });
    const column = new Entity({
      id: "storm:column",
      position: new CallbackProperty(() => {
        const s = this.now;
        return s ? Cartesian3.fromDegrees(s.lon, s.lat, (s.vmax * COLUMN_M_PER_KT) / 2) : undefined;
      }, false),
      cylinder: {
        length: new CallbackProperty(() => Math.max(1, (this.now?.vmax ?? 0) * COLUMN_M_PER_KT), false),
        topRadius: 2500,
        bottomRadius: 2500,
        material: new ColorMaterialProperty(
          new CallbackProperty(() => css(categoryColor(this.now?.vmax ?? 0), 0.75), false),
        ),
        slices: 24,
      },
    });
    const label = new Entity({
      id: "storm:label",
      position: new CallbackProperty(() => {
        const s = this.now;
        return s ? Cartesian3.fromDegrees(s.lon, s.lat, s.vmax * COLUMN_M_PER_KT + 1500) : undefined;
      }, false),
      label: {
        text: new CallbackProperty(() => {
          const s = this.now;
          return s ? t("globe.stormLabel", { kt: Math.round(s.vmax) }) : "";
        }, false),
        font: "13px 'JetBrains Mono', monospace",
        fillColor: Color.WHITE,
        outlineColor: Color.BLACK,
        outlineWidth: 3,
        style: LabelStyle.FILL_AND_OUTLINE,
        verticalOrigin: VerticalOrigin.BOTTOM,
        pixelOffset: new Cartesian2(0, -4),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    });
    this.observed = new Entity({
      id: "storm:observed",
      show: false,
      polyline: {
        positions: [],
        width: 2,
        material: new PolylineDashMaterialProperty({ color: Color.WHITE.withAlpha(0.9), dashLength: 12 }),
      },
    });
    this.ds.entities.add(disc);
    this.ds.entities.add(column);
    this.ds.entities.add(label);
    this.ds.entities.add(this.observed);
  }

  /** Return the storm state at the last update, or null. */
  current(): StormState | null {
    return this.now;
  }

  update(_t: JulianDate, f: ScenarioFrame): void {
    this.ensemble.tick();
    this.selected.tick();
    this.cone.tick();
    this.coneEdge.tick();
    const stage1 = f.state.stage1;
    const ens = stage1?.ensemble ?? null;
    if (ens !== this.lastEnsemble) {
      this.lastEnsemble = ens;
      this.ensemble.set(this.buildEnsemble(ens));
    }
    const cone = stage1?.cone ?? null;
    if (cone !== this.lastCone) {
      this.lastCone = cone;
      const areas: AreaSpec[] = [];
      for (const feat of cone?.features ?? []) {
        const lvl = feat.properties?.level ?? "p66";
        areaToHierarchies(feat.geometry).forEach((h, i) =>
          areas.push({ id: `cone:${lvl}:${i}`, hierarchy: h, color: CONE_COLORS[lvl] ?? CONE_COLORS.p66 }),
        );
      }
      // Draw the widest level first.
      areas.sort((a, b) => b.id.localeCompare(a.id));
      this.cone.set(buildGroundPrimitive(areas));
      const edges: LineSpec[] = [];
      for (const feat of cone?.features ?? []) {
        const lvl = feat.properties?.level ?? "p66";
        const g = feat.geometry;
        const polys = g?.type === "Polygon" ? [g.coordinates] : g?.type === "MultiPolygon" ? g.coordinates : [];
        polys.forEach((rings, i) => {
          const ring = cleanLine(rings[0] ?? []);
          if (ring.length >= 2)
            edges.push({ id: `coneEdge:${lvl}:${i}`, path: ring, color: CONE_EDGE[lvl] ?? CONE_EDGE.p66, width: lvl === "p50" ? 2 : 1.5, height: 800 });
        });
      }
      this.coneEdge.set(buildLinePrimitive(edges, true));
    }
    const sc: Scenario | undefined = stage1?.scenarios?.scenarios.find((s) => s.id === f.state.scenarioId);
    const key = `${stage1?.advisory ?? ""}|${sc?.id ?? -1}`;
    if (key !== this.lastTrackKey) {
      this.lastTrackKey = key;
      this.track = sc?.track ?? null;
      const path = sc ? fixesToPath(sc.track) : [];
      this.selected.set(
        path.length >= 2
          ? buildLinePrimitive([{ id: "selected", path, color: css("#ffb300", 1), width: 3, height: 1500 }], false)
          : null,
      );
    }
    this.now = stormAt(this.track, f.tMs);
    if (!this.now && stage1?.ensemble?.observed?.length) {
      this.now = stormAt(stage1.ensemble.observed, f.tMs);
    }
    // Show the observed best track after the clock passes the observed landfall.
    const truth = f.state.statics?.truth?.track ?? [];
    const lf = f.state.meta?.truth_landfall?.time;
    const showTruth = !!lf && f.tMs >= ms(lf) && truth.length > 1;
    if (showTruth !== this.truthShown) {
      this.truthShown = showTruth;
      if (showTruth && this.observed.polyline) {
        this.observed.polyline.positions = new ConstantProperty(toCartesians(fixesToPath(truth), 1800));
      }
      this.observed.show = showTruth && this.visible;
    }
  }

  private buildEnsemble(ens: Ensemble | null): Primitive | null {
    if (!ens) return null;
    const lines: LineSpec[] = [];
    const color = css("#bfe9ff", 0.15);
    ens.members.forEach((m, i) => {
      if (!Array.isArray(m)) return;
      const path = cleanLine(m.map((p) => [p[0], p[1]] as LonLat));
      if (path.length >= 2) lines.push({ id: `ens:${i}`, path, color, width: 1, height: 1000 });
    });
    const mean = cleanLine((ens.mean ?? []).map((p) => [p[0], p[1]] as LonLat));
    if (mean.length >= 2) lines.push({ id: "ens:mean", path: mean, color: css("#ffffff", 0.55), width: 1.5, height: 1100 });
    return buildLinePrimitive(lines, true);
  }

  setVisible(v: boolean): void {
    this.visible = v;
    this.ensemble.setShow(v);
    this.selected.setShow(v);
    this.cone.setShow(v);
    this.coneEdge.setShow(v);
    this.ds.show = v;
    this.observed.show = v && this.truthShown;
  }
}
