import {
  BillboardGraphics,
  Cartesian2,
  Color,
  ColorMaterialProperty,
  ConstantProperty,
  CzmlDataSource,
  LabelGraphics,
  LabelStyle,
  NearFarScalar,
  PathGraphics,
  PointGraphics,
  type Entity,
  type JulianDate,
  type Viewer,
} from "cesium";
import type { LayerId } from "../state/store";
import { assetIcon } from "./icons";
import { css } from "./palette";

const PREFIX_LAYER: Record<string, LayerId> = { truck: "supply", asset: "sar", crew: "debris" };

const KIND_COLOR: Record<string, string> = {
  truck: "#7cf29a",
  helo: "#ffd54f",
  boat: "#4dd0e1",
  high_water_truck: "#ce93d8",
  crew: "#ff9f43",
};

/** Return the layer that owns a CZML entity, from the prefix of its id. */
export function layerOfEntity(id: string): LayerId | null {
  const p = id.split(":")[0];
  return PREFIX_LAYER[p] ?? null;
}

function kindOf(e: Entity, time: JulianDate): string {
  const v: unknown = e.properties?.getValue(time);
  if (v && typeof v === "object" && "kind" in v) {
    const k = (v as { kind: unknown }).kind;
    if (typeof k === "string") return k;
  }
  const p = e.id.split(":")[0];
  return p === "asset" ? "helo" : p;
}

function style(e: Entity, time: JulianDate): void {
  if (!e.position) return;
  const kind = kindOf(e, time);
  const color = css(KIND_COLOR[kind] ?? "#ffffff");
  const isAsset = kind === "helo" || kind === "boat" || kind === "high_water_truck";
  if (isAsset && !e.billboard) {
    e.billboard = new BillboardGraphics({
      image: assetIcon(kind),
      width: 22,
      height: 22,
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    });
    if (e.point) e.point.show = new ConstantProperty(false);
  } else if (!isAsset && !e.point && !e.billboard) {
    e.point = new PointGraphics({
      pixelSize: kind === "crew" ? 9 : 7,
      color,
      outlineColor: Color.BLACK,
      outlineWidth: 1.5,
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    });
  }
  // Many trucks move at the same time. Hide their labels to keep the map clear.
  if (kind === "truck" && e.label) e.label.show = new ConstantProperty(false);
  if (!e.path) {
    e.path = new PathGraphics({
      leadTime: 0,
      trailTime: 4 * 3600,
      width: kind === "truck" ? 1.5 : 2,
      resolution: 300,
      material: new ColorMaterialProperty(color.withAlpha(0.55)),
    });
  }
  if (isAsset && !e.label && e.name) {
    e.label = new LabelGraphics({
      text: e.name,
      font: "11px 'JetBrains Mono', monospace",
      fillColor: color,
      outlineColor: Color.BLACK,
      outlineWidth: 3,
      style: LabelStyle.FILL_AND_OUTLINE,
      pixelOffset: new Cartesian2(0, -18),
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
      translucencyByDistance: new NearFarScalar(8e4, 1.0, 2.5e5, 0.0),
    });
  }
}

/** Load the CZML file of the selected scenario and keep the old one until the new one is ready. */
export class CzmlManager {
  private current: CzmlDataSource | null = null;
  private url: string | null = null;
  private lastLayers: Record<LayerId, boolean> | null = null;

  constructor(private readonly viewer: Viewer) {}

  /** Return the active data source, or null. */
  get source(): CzmlDataSource | null {
    return this.current;
  }

  /** Load a new CZML URL if it changed. Apply layer visibility to the entities. */
  update(url: string | null, layers: Record<LayerId, boolean>): void {
    if (url !== this.url) {
      this.url = url;
      if (!url) {
        this.replace(null);
      } else {
        const want = url;
        const ds = new CzmlDataSource("plan");
        ds.load(url)
          .then(() => {
            if (this.url !== want || this.viewer.isDestroyed()) return;
            const time = this.viewer.clock.currentTime;
            for (const e of ds.entities.values) style(e, time);
            this.replace(ds);
          })
          .catch((err: unknown) => console.warn("CZML load failed", err));
      }
    }
    if (layers !== this.lastLayers && this.current) {
      this.lastLayers = layers;
      this.applyVisibility(this.current, layers);
    }
  }

  private applyVisibility(ds: CzmlDataSource, layers: Record<LayerId, boolean>): void {
    for (const e of ds.entities.values) {
      const l = layerOfEntity(e.id);
      if (l) e.show = layers[l];
    }
  }

  private replace(ds: CzmlDataSource | null): void {
    const old = this.current;
    this.current = ds;
    if (ds) {
      this.lastLayers = null;
      void this.viewer.dataSources.add(ds);
    }
    if (old) this.viewer.dataSources.remove(old, true);
  }
}
