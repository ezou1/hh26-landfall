import {
  Cartesian3,
  Color,
  Material,
  NearFarScalar,
  PointPrimitiveCollection,
  PolylineCollection,
  type JulianDate,
  type PointPrimitive,
  type Polyline,
  type Viewer,
} from "cesium";
import type { SarAsset, SarTask, ScenarioPlan } from "../../api/types";
import { taskAssignTimes, taskStatus, type TaskStatus } from "../../state/derive";
import { css, PRIORITY_COLORS } from "../palette";
import { currentTaskId, waypointAt } from "../track";
import type { GlobeLayer, ScenarioFrame } from "./types";

interface TaskItem {
  task: SarTask;
  point: PointPrimitive;
  status: TaskStatus | null;
}

interface AssetItem {
  asset: SarAsset;
  line: Polyline;
}

/** The rescue layer: rescue tasks as points, and a line from each asset to its current task. */
export class SarLayer implements GlobeLayer {
  readonly id = "sar" as const;
  private points = new PointPrimitiveCollection();
  private lines = new PolylineCollection();
  private tasks: TaskItem[] = [];
  private byId = new Map<string, SarTask>();
  private assets: AssetItem[] = [];
  private assign = new Map<string, number>();
  private lastPlan: ScenarioPlan | null = null;
  private lastQ = Number.NaN;
  private visible = true;

  init(viewer: Viewer): void {
    viewer.scene.primitives.add(this.points);
    viewer.scene.primitives.add(this.lines);
  }

  update(t: JulianDate, f: ScenarioFrame): void {
    const plan = f.state.planScenario?.plan ?? null;
    if (plan !== this.lastPlan) {
      this.lastPlan = plan;
      this.points.removeAll();
      this.lines.removeAll();
      this.tasks = [];
      this.assets = [];
      this.byId.clear();
      this.lastQ = Number.NaN;
      this.assign = taskAssignTimes(plan?.sar_assets);
      for (const task of plan?.sar_tasks ?? []) {
        if (!Number.isFinite(task.lon) || !Number.isFinite(task.lat)) continue;
        this.byId.set(task.id, task);
        const point = this.points.add({
          position: Cartesian3.fromDegrees(task.lon, task.lat, 30),
          pixelSize: 6,
          color: Color.WHITE,
          outlineColor: Color.BLACK.withAlpha(0.6),
          outlineWidth: 1,
          show: false,
          scaleByDistance: new NearFarScalar(1e4, 1.6, 3e5, 0.6),
          id: `task:${task.id}`,
        });
        this.tasks.push({ task, point, status: null });
      }
      for (const asset of plan?.sar_assets ?? []) {
        const line = this.lines.add({
          positions: [Cartesian3.ZERO, Cartesian3.ZERO],
          width: 1.5,
          material: Material.fromType("PolylineDash", { color: css("#ffffff", 0.85), dashLength: 10 }),
          show: false,
        });
        this.assets.push({ asset, line });
      }
    }
    const q = Math.floor(f.hourF * 4);
    if (q !== this.lastQ) {
      this.lastQ = q;
      for (const it of this.tasks) {
        const st = taskStatus(it.task, this.assign, f.tMs);
        if (st === it.status) continue;
        it.status = st;
        it.point.show = st !== "future";
        const base = PRIORITY_COLORS[it.task.priority] ?? "#ffd60a";
        it.point.color = st === "served" ? css(base, 0.22) : css(base, 0.95);
        it.point.pixelSize = st === "served" ? 4 : 5 + Math.min(6, it.task.persons);
        it.point.outlineColor = st === "assigned" ? Color.WHITE : Color.BLACK.withAlpha(0.6);
      }
    }
    // Draw a line from each asset to its current task. The CZML entity gives the best position.
    if (!this.visible) return;
    for (const it of this.assets) {
      const tid = currentTaskId(it.asset.waypoints, f.tMs);
      const task = tid ? this.byId.get(tid) : undefined;
      if (!task) {
        it.line.show = false;
        continue;
      }
      let from: Cartesian3 | undefined;
      const ent = f.czml?.entities.getById(`asset:${it.asset.id}`);
      if (ent?.position) from = ent.position.getValue(t);
      if (!from) {
        const p = waypointAt(it.asset.waypoints, f.tMs);
        if (p) from = Cartesian3.fromDegrees(p.lon, p.lat, 150);
      }
      if (!from) {
        it.line.show = false;
        continue;
      }
      it.line.positions = [from, Cartesian3.fromDegrees(task.lon, task.lat, 30)];
      it.line.show = true;
    }
  }

  setVisible(v: boolean): void {
    this.visible = v;
    this.points.show = v;
    this.lines.show = v;
  }
}
