import {
  ArcType,
  Cartesian3,
  Color,
  ColorGeometryInstanceAttribute,
  CylinderGeometry,
  GeometryInstance,
  GroundPrimitive,
  Matrix4,
  PerInstanceColorAppearance,
  PolygonGeometry,
  PolygonHierarchy,
  PolylineColorAppearance,
  PolylineGeometry,
  Primitive,
  ShowGeometryInstanceAttribute,
  Transforms,
  type Scene,
} from "cesium";
import type { LonLat } from "../api/types";
import { toCartesians } from "./geo";

/** One line for a polyline primitive. */
export interface LineSpec {
  id: string;
  path: LonLat[];
  color: Color;
  width: number;
  height?: number;
  show?: boolean;
}

/** Make one Primitive that draws many polylines. The primitive builds at once, not in a worker. */
export function buildLinePrimitive(lines: LineSpec[], translucent = true): Primitive | null {
  const instances: GeometryInstance[] = [];
  for (const l of lines) {
    if (l.path.length < 2) continue;
    instances.push(
      new GeometryInstance({
        id: l.id,
        geometry: new PolylineGeometry({
          positions: toCartesians(l.path, l.height ?? 0),
          width: l.width,
          vertexFormat: PolylineColorAppearance.VERTEX_FORMAT,
          arcType: ArcType.GEODESIC,
        }),
        attributes: {
          color: ColorGeometryInstanceAttribute.fromColor(l.color),
          show: new ShowGeometryInstanceAttribute(l.show ?? true),
        },
      }),
    );
  }
  if (instances.length === 0) return null;
  return new Primitive({
    geometryInstances: instances,
    appearance: new PolylineColorAppearance({ translucent }),
    asynchronous: false,
    allowPicking: true,
  });
}

/** One polygon for a ground primitive. */
export interface AreaSpec {
  id: string;
  hierarchy: PolygonHierarchy;
  color: Color;
}

/** Make one GroundPrimitive that drapes many polygons on the ground. */
export function buildGroundPrimitive(areas: AreaSpec[]): GroundPrimitive | null {
  const instances = areas.map(
    (a) =>
      new GeometryInstance({
        id: a.id,
        geometry: new PolygonGeometry({ polygonHierarchy: a.hierarchy }),
        attributes: {
          color: ColorGeometryInstanceAttribute.fromColor(a.color),
          show: new ShowGeometryInstanceAttribute(true),
        },
      }),
  );
  if (instances.length === 0) return null;
  return new GroundPrimitive({
    geometryInstances: instances,
    appearance: new PerInstanceColorAppearance({ flat: true, translucent: true }),
    asynchronous: true,
  });
}

/** Set the color of one instance in a primitive. Do nothing if the primitive is not ready. */
export function setInstanceColor(p: Primitive | GroundPrimitive | null, id: string, c: Color): void {
  if (!p || !p.ready) return;
  const attrs = p.getGeometryInstanceAttributes(id) as { color?: Uint8Array } | undefined;
  if (attrs && attrs.color) attrs.color = ColorGeometryInstanceAttribute.toValue(c, attrs.color);
}

/** Show or hide one instance in a primitive. Do nothing if the primitive is not ready. */
export function setInstanceShow(p: Primitive | GroundPrimitive | null, id: string, v: boolean): void {
  if (!p || !p.ready) return;
  const attrs = p.getGeometryInstanceAttributes(id) as { show?: Uint8Array } | undefined;
  if (attrs && attrs.show) attrs.show = ShowGeometryInstanceAttribute.toValue(v, attrs.show);
}

/**
 * A vertical column at a site. The height changes through the model matrix,
 * so a change of height does not build new geometry.
 */
export class Column {
  private readonly prim: Primitive;
  private readonly base: Matrix4;
  private readonly scratch = new Matrix4();
  private height = -1;
  private dirty = false;
  private color: Color;
  private visible = true;

  constructor(
    private readonly scene: Scene,
    lon: number,
    lat: number,
    radiusM: number,
    color: Color,
    baseHeight = 0,
  ) {
    this.color = color;
    this.base = Transforms.eastNorthUpToFixedFrame(Cartesian3.fromDegrees(lon, lat, baseHeight));
    this.prim = new Primitive({
      geometryInstances: new GeometryInstance({
        geometry: new CylinderGeometry({
          length: 1,
          topRadius: radiusM,
          bottomRadius: radiusM,
          slices: 24,
          vertexFormat: PerInstanceColorAppearance.VERTEX_FORMAT,
        }),
        modelMatrix: Matrix4.fromTranslation(new Cartesian3(0, 0, 0.5)),
        attributes: { color: ColorGeometryInstanceAttribute.fromColor(color) },
        id: "column",
      }),
      appearance: new PerInstanceColorAppearance({ translucent: color.alpha < 1, closed: true }),
      asynchronous: false,
      modelMatrix: this.base,
    });
    scene.primitives.add(this.prim);
    this.setHeight(1);
  }

  /** Set the height of the column in metres. */
  setHeight(h: number): void {
    const v = Math.max(0, h);
    if (Math.abs(v - this.height) < 0.5) return;
    this.height = v;
    const scale = Matrix4.fromScale(new Cartesian3(1, 1, Math.max(v, 0.01)), this.scratch);
    this.prim.modelMatrix = Matrix4.multiply(this.base, scale, new Matrix4());
    this.prim.show = this.visible && v > 0.5;
  }

  /** Set the color of the column. */
  setColor(c: Color): void {
    if (Color.equals(c, this.color)) return;
    this.color = c;
    this.dirty = true;
    this.flush();
  }

  /** Apply a pending color change. The primitive gets ready only after its first frame. */
  flush(): void {
    if (!this.dirty || !this.prim.ready) return;
    const attrs = this.prim.getGeometryInstanceAttributes("column") as { color?: Uint8Array } | undefined;
    if (attrs && attrs.color) attrs.color = ColorGeometryInstanceAttribute.toValue(this.color, attrs.color);
    this.dirty = false;
  }

  /** Show or hide the column. */
  setShow(v: boolean): void {
    this.visible = v;
    this.prim.show = v && this.height > 0.5;
  }

  /** Remove the column from the scene. */
  destroy(): void {
    this.scene.primitives.remove(this.prim);
  }
}
