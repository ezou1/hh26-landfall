import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { SarAsset, SarTask } from "../../api/types";
import { flyToEntity, flyToPoint } from "../../globe/controller";
import { PRIORITY_COLORS } from "../../globe/palette";
import { t } from "../../i18n/t";
import { assetState, taskAssignTimes, taskStatus, type TaskStatus } from "../../state/derive";
import { useStore } from "../../state/store";
import { atHour, fmtIso, fmtNum } from "../../time";
import { VirtualTable, type Col } from "../VirtualTable";
import { chartStyle } from "./chartStyle";
import { PlanGate, Section } from "./common";

type Filter = "all" | Exclude<TaskStatus, "future">;
const FILTERS: Filter[] = ["all", "waiting", "assigned", "served"];

/** The Rescue view: the task board, the asset board, hospital gauges, and time to rescue. */
export function RescuePanel() {
  const plan = useStore((s) => s.planScenario?.plan);
  const statics = useStore((s) => s.statics);
  const hour = useStore((s) => s.hour);
  const t0 = useStore((s) => s.t0Ms);
  const [filter, setFilter] = useState<Filter>("all");
  const tMs = t0 + hour * 3_600_000;
  const assign = useMemo(() => taskAssignTimes(plan?.sar_assets), [plan]);

  const tasks = useMemo(() => {
    const rows = (plan?.sar_tasks ?? []).map((task) => ({ task, status: taskStatus(task, assign, tMs) }));
    return rows
      .filter((r) => r.status !== "future" && (filter === "all" || r.status === filter))
      .sort((a, b) => a.task.priority - b.task.priority || a.task.created_t.localeCompare(b.task.created_t));
  }, [plan, assign, tMs, filter]);

  const counts = useMemo(() => {
    const c: Record<TaskStatus, number> = { future: 0, waiting: 0, assigned: 0, served: 0 };
    for (const task of plan?.sar_tasks ?? []) c[taskStatus(task, assign, tMs)]++;
    return c;
  }, [plan, assign, tMs]);

  const baseById = useMemo(() => new Map((statics?.assets ?? []).map((a) => [a.id, a])), [statics]);
  const assets = (plan?.sar_assets ?? []).map((a) => ({ a, st: assetState(a, baseById.get(a.id), tMs) }));

  const taskCols: Col<{ task: SarTask; status: TaskStatus }>[] = [
    { key: "id", header: t("rescue.task"), render: (r) => r.task.id },
    {
      key: "p",
      header: t("rescue.priority"),
      render: (r) => <span style={{ color: PRIORITY_COLORS[r.task.priority] }}>P{r.task.priority}</span>,
    },
    { key: "type", header: t("rescue.type"), render: (r) => t(`assetKindShort.${r.task.asset_type}`) },
    { key: "n", header: t("rescue.persons"), num: true, render: (r) => fmtNum(r.task.persons) },
    { key: "isl", header: t("rescue.island"), render: (r) => r.task.island ?? "—" },
    {
      key: "st",
      header: t("rescue.status"),
      render: (r) => (
        <span className={r.status === "served" ? "ok" : r.status === "assigned" ? "warn" : "bad"}>
          {t(`taskStatus.${r.status}`)}
        </span>
      ),
    },
    { key: "a", header: t("rescue.asset"), render: (r) => r.task.asset_id ?? "—" },
  ];

  const assetCols: Col<{ a: SarAsset; st: ReturnType<typeof assetState> }>[] = [
    { key: "name", header: t("rescue.asset"), render: (r) => r.a.name || r.a.id },
    { key: "kind", header: t("rescue.type"), render: (r) => t(`assetKindShort.${r.a.kind}`) },
    { key: "st", header: t("rescue.status"), render: (r) => t(`assetStatus.${r.st.status}`) },
    { key: "task", header: t("rescue.currentTask"), render: (r) => r.st.taskId ?? "—" },
    {
      key: "end",
      header: t("rescue.endurance"),
      num: true,
      render: (r) => {
        const v = r.st.enduranceLeftH;
        const tot = r.a.endurance_h || 1;
        const cls = v === null ? "muted" : v / tot < 0.25 ? "bad" : v / tot < 0.5 ? "warn" : "ok";
        return <span className={cls}>{v === null ? "—" : `${v.toFixed(1)} h`}</span>;
      },
    },
  ];

  const hist = (plan?.time_to_rescue_hist ?? []).map((b) => ({ bin: b.bin_h, count: b.count }));
  const rescued = atHour(plan?.rescued_by_hour, hour);

  return (
    <div data-testid="panel-rescue">
      <PlanGate>
        <Section title={t("rescue.summary")}>
          <div className="kpis">
            <div className="kpi">
              <div className="k">{t("rescue.rescuedNow")}</div>
              <div className="v ok">
                {fmtNum(rescued)}
                <span className="u">{t("kpi.unitPersons")}</span>
              </div>
            </div>
            <div className="kpi">
              <div className="k">{t("rescue.openTasks")}</div>
              <div className="v warn">{fmtNum(counts.waiting + counts.assigned)}</div>
              <div className="s">{t("rescue.waitingAssigned", { w: counts.waiting, a: counts.assigned })}</div>
            </div>
            <div className="kpi">
              <div className="k">{t("rescue.median")}</div>
              <div className="v">
                {fmtNum(plan?.median_time_to_rescue_h, 1)}
                <span className="u">h</span>
              </div>
            </div>
            <div className="kpi">
              <div className="k">{t("rescue.unmet72")}</div>
              <div className={`v ${(plan?.unmet_tasks_72h ?? 0) > 0 ? "bad" : "ok"}`}>{fmtNum(plan?.unmet_tasks_72h)}</div>
            </div>
          </div>
        </Section>
        <Section title={t("rescue.tasks", { n: tasks.length })}>
          <div className="filters">
            {FILTERS.map((f) => (
              <button key={f} className={`btn ${filter === f ? "on" : ""}`} onClick={() => setFilter(f)}>
                {f === "all" ? t("common.all") : t(`taskStatus.${f}`)}
              </button>
            ))}
          </div>
          <VirtualTable
            rows={tasks}
            cols={taskCols}
            rowKey={(r) => r.task.id}
            onRowClick={(r) => flyToPoint(r.task.lon, r.task.lat, 6000)}
            maxHeight={240}
            empty={t("rescue.noTasks")}
          />
        </Section>
        <Section title={t("rescue.assets")}>
          <VirtualTable
            rows={assets}
            cols={assetCols}
            rowKey={(r) => r.a.id}
            onRowClick={(r) => {
              if (!flyToEntity(`asset:${r.a.id}`) && r.st.lon !== null && r.st.lat !== null)
                flyToPoint(r.st.lon, r.st.lat, 9000);
            }}
            maxHeight={200}
          />
        </Section>
        <Section title={t("rescue.hospitals")}>
          {(plan?.hospitals ?? []).map((h) => {
            const site = statics?.hospitals.find((x) => x.id === h.id);
            const avail = atHour(h.beds_available, hour) ?? 0;
            const frac = h.beds_total > 0 ? avail / h.beds_total : 0;
            const color = frac < 0.1 ? "var(--bad)" : frac < 0.3 ? "var(--warn)" : "var(--ok)";
            const gridOut = h.grid_out_h !== null && h.grid_out_h !== undefined && hour >= h.grid_out_h;
            return (
              <div
                className="gauge-row"
                key={h.id}
                onClick={() => site && flyToPoint(site.lon, site.lat, 6000)}
                title={gridOut ? t("rescue.gridOut") : undefined}
              >
                <span>
                  {site?.name ?? h.id}
                  {gridOut && <span className="warn"> ⚡</span>}
                </span>
                <div className="bar">
                  <i style={{ width: `${Math.max(0, Math.min(100, frac * 100))}%`, background: color }} />
                </div>
                <span className="muted" style={{ textAlign: "right" }}>
                  {fmtNum(avail)}/{fmtNum(h.beds_total)}
                </span>
              </div>
            );
          })}
        </Section>
        <Section title={t("rescue.histogram")}>
          {hist.length === 0 ? (
            <p className="note">{t("rescue.noHist")}</p>
          ) : (
            <div className="chart-box" style={{ height: 170 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={hist} margin={{ left: 0, right: 12, top: 8, bottom: 14 }}>
                  <CartesianGrid stroke={chartStyle.grid} vertical={false} />
                  <XAxis
                    dataKey="bin"
                    tick={chartStyle.axis}
                    label={{ value: t("rescue.histX"), position: "insideBottom", offset: -6, ...chartStyle.axis }}
                  />
                  <YAxis tick={chartStyle.axis} width={36} allowDecimals={false} />
                  <Tooltip
                    {...chartStyle.tooltip}
                    cursor={{ fill: "rgba(79,195,247,0.08)" }}
                    labelFormatter={(v) => t("rescue.histBin", { h: String(v) })}
                    formatter={(v) => [fmtNum(Number(v)), t("rescue.histY")]}
                  />
                  <Bar dataKey="count" fill="#3987e5" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
          <p className="muted" style={{ fontSize: 10 }}>
            {t("rescue.histNote", { time: fmtIso(new Date(tMs).toISOString()) })}
          </p>
        </Section>
      </PlanGate>
    </div>
  );
}
