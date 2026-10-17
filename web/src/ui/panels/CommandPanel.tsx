import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { MetricKey, ZonePlan } from "../../api/types";
import { flyToPath, flyToPoint } from "../../globe/controller";
import { areaCentroid } from "../../globe/geo";
import { hasKey, t } from "../../i18n/t";
import { useStore } from "../../state/store";
import { atHour, fmtHours, fmtIso, fmtNum } from "../../time";
import { VirtualTable, type Col } from "../VirtualTable";
import { chartStyle } from "./chartStyle";
import { PlanGate, Section } from "./common";

const KPIS: { key: MetricKey; unit: string; digits: number }[] = [
  { key: "persons_at_risk", unit: "kpi.unitPersons", digits: 0 },
  { key: "unmet_supply_kg", unit: "kpi.unitKg", digits: 0 },
  { key: "expected_rescues", unit: "kpi.unitPersons", digits: 0 },
  { key: "clearance_margin_h", unit: "kpi.unitHours", digits: 1 },
];

interface ShelterRow {
  id: string;
  name: string;
  lon: number;
  lat: number;
  open: boolean;
  pct: number;
  occ: number;
  pFull: number | null;
}

function metricLabel(key: string, labelKey?: string): string {
  if (labelKey && hasKey(labelKey)) return t(labelKey);
  if (hasKey(`metric.${key}`)) return t(`metric.${key}`);
  return key;
}

/** The Command view: KPI cards, the zone table, plan comparison, and the harden list. */
export function CommandPanel() {
  const agg = useStore((s) => s.planCommon?.aggregate);
  const comparison = useStore((s) => s.planCommon?.comparison);
  const infra = useStore((s) => s.planCommon?.infrastructure);
  const plan = useStore((s) => s.planScenario?.plan);
  const mode = useStore((s) => s.kpiMode);
  const zonesGeo = useStore((s) => s.statics?.zones);
  const set = useStore((s) => s.set);
  const layers = useStore((s) => s.layers);
  const shelters = useStore((s) => s.statics?.shelters);
  const hour = useStore((s) => s.hour);

  const zoneCols: Col<ZonePlan>[] = [
    { key: "zone", header: t("zone.zone"), render: (z) => z.zone },
    { key: "rel", header: t("zone.release"), render: (z) => fmtIso(z.release_time) },
    { key: "clr", header: t("zone.clearance"), render: (z) => fmtIso(z.clearance_time) },
    { key: "ts", header: t("zone.tsArrival"), render: (z) => fmtIso(z.ts_arrival) },
    {
      key: "margin",
      header: t("zone.margin"),
      num: true,
      render: (z) => (
        <span className={z.margin_h === null ? "muted" : z.margin_h < 0 ? "bad" : "ok"}>{fmtHours(z.margin_h)}</span>
      ),
    },
    { key: "nc", header: t("zone.notCleared"), num: true, render: (z) => fmtNum(z.not_cleared) },
  ];

  const shelterRows: ShelterRow[] = (shelters ?? []).map((s) => {
    const sp = plan?.shelters.find((x) => x.id === s.id);
    const cap = sp?.capacity || s.capacity || 1;
    const occ = sp ? (atHour(sp.occupancy, hour) ?? 0) : 0;
    const flag = infra?.shelters_flagged?.find((x) => x.shelter_id === s.id);
    return { id: s.id, name: s.name, lon: s.lon, lat: s.lat, open: sp?.open ?? false, pct: occ / cap, occ, pFull: flag?.p_full ?? null };
  });
  const shelterCols: Col<ShelterRow>[] = [
    { key: "name", header: t("shelter.name"), render: (r) => r.name },
    { key: "open", header: t("shelter.open"), render: (r) => (r.open ? t("common.yes") : t("common.no")) },
    { key: "occ", header: t("shelter.occupancy"), num: true, render: (r) => fmtNum(r.occ) },
    {
      key: "pct",
      header: t("shelter.fill"),
      num: true,
      render: (r) => <span className={r.pct >= 1 ? "bad" : r.pct >= 0.8 ? "warn" : "ok"}>{fmtNum(r.pct * 100)}%</span>,
    },
    { key: "pf", header: t("shelter.pFull"), num: true, render: (r) => (r.pFull === null ? "—" : `${fmtNum(r.pFull * 100)}%`) },
  ];

  // A percent of the baseline has a meaning only for positive values. Show the other rows as text.
  const allRows = (comparison?.rows ?? []).filter((r) => r.baseline !== null && r.optimized !== null);
  const isIndexable = (r: { baseline: number | null; optimized: number | null }) =>
    (r.baseline ?? 0) > 0 && (r.optimized ?? 0) >= 0;
  const textRows = allRows.filter((r) => !isIndexable(r));
  const compRows = allRows
    .filter(isIndexable)
    .map((r) => {
      const b = r.baseline ?? 0;
      const o = r.optimized ?? 0;
      const base = Math.abs(b) > 1e-9 ? Math.abs(b) : Math.max(Math.abs(o), 1);
      return {
        name: metricLabel(r.metric, r.label_key),
        optimized: (o / base) * 100,
        baseline: (b / base) * 100,
        rawO: o,
        rawB: b,
        better: r.better,
      };
    });

  return (
    <div data-testid="panel-command">
      <Section title={t(mode === "expected" ? "command.kpiExpected" : "command.kpiWorst")}>
        {!agg && <p className="note">{t("common.noPlan")}</p>}
        <div className="kpis">
          {KPIS.map((k) => {
            const v = agg?.metrics?.[k.key]?.[mode] ?? null;
            const sv = plan?.kpis?.[k.key as keyof typeof plan.kpis] ?? null;
            const cls = k.key === "clearance_margin_h" && v !== null ? (v < 0 ? "bad" : "ok") : "";
            return (
              <div className="kpi" key={k.key}>
                <div className="k">{metricLabel(k.key)}</div>
                <div className={`v ${cls}`}>
                  {k.key === "clearance_margin_h" ? fmtHours(v) : fmtNum(v, k.digits)}
                  {k.key !== "clearance_margin_h" && <span className="u">{t(k.unit)}</span>}
                </div>
                <div className="s">
                  {t("command.thisScenario")}:{" "}
                  {k.key === "clearance_margin_h" ? fmtHours(sv) : fmtNum(sv, k.digits)}
                </div>
              </div>
            );
          })}
        </div>
      </Section>
      <Section title={t("command.zones")}>
        <PlanGate>
          <VirtualTable
            rows={plan?.zones ?? []}
            cols={zoneCols}
            rowKey={(z) => z.zone}
            rowClass={(z) => (z.margin_h !== null && z.margin_h < 0 ? "bad" : "")}
            onRowClick={(z) => {
              const f = zonesGeo?.features.find((x) => String(x.properties?.zone) === z.zone);
              const c = areaCentroid(f?.geometry);
              if (c) flyToPoint(c[0], c[1], 30_000);
            }}
          />
        </PlanGate>
      </Section>
      <Section title={t("command.shelters")}>
        <PlanGate>
          <VirtualTable
            rows={shelterRows}
            cols={shelterCols}
            rowKey={(r) => r.id}
            onRowClick={(r) => flyToPoint(r.lon, r.lat, 8000)}
            maxHeight={200}
          />
        </PlanGate>
      </Section>
      <Section title={t("command.compare")}>
        {compRows.length === 0 ? (
          <p className="note">{t("command.noCompare")}</p>
        ) : (
          <div className="chart-box" style={{ height: 40 + compRows.length * 34 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={compRows} layout="vertical" margin={{ left: 8, right: 16, top: 4, bottom: 4 }} barGap={2}>
                <CartesianGrid stroke={chartStyle.grid} horizontal={false} />
                <XAxis type="number" tick={chartStyle.axis} unit="%" domain={[0, "auto"]} />
                <YAxis type="category" dataKey="name" tick={chartStyle.axis} width={150} />
                <Tooltip
                  {...chartStyle.tooltip}
                  cursor={{ fill: "rgba(79,195,247,0.06)" }}
                  formatter={(_v, name, item) => {
                    const p = item.payload as { rawO: number; rawB: number };
                    return [fmtNum(name === "optimized" ? p.rawO : p.rawB, 1), t(`command.${String(name)}`)];
                  }}
                />
                <Legend
                  wrapperStyle={{ fontSize: 10 }}
                  formatter={(v: string) => <span style={{ color: "#d7e3ee" }}>{t(`command.${v}`)}</span>}
                />
                <Bar dataKey="baseline" fill="#6b7f91" radius={[0, 3, 3, 0]} barSize={9} />
                <Bar dataKey="optimized" fill="#3987e5" radius={[0, 3, 3, 0]} barSize={9} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
        {textRows.length > 0 && (
          <table className="grid" style={{ marginTop: 6 }}>
            <thead>
              <tr>
                <th>{t("command.metric")}</th>
                <th className="num">{t("command.baseline")}</th>
                <th className="num">{t("command.optimized")}</th>
              </tr>
            </thead>
            <tbody>
              {textRows.map((r) => (
                <tr key={r.metric}>
                  <td>{metricLabel(r.metric, r.label_key)}</td>
                  <td className="num">{fmtNum(r.baseline, 1)}</td>
                  <td className="num">{fmtNum(r.optimized, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted" style={{ fontSize: 10 }}>
          {t("command.compareNote")}
        </p>
      </Section>
      <Section
        title={t("command.harden")}
        right={
          <button className={`btn ${layers.infra ? "on" : ""}`} onClick={() => useStore.getState().toggleLayer("infra")}>
            {t("command.showOnGlobe")}
          </button>
        }
      >
        {(infra?.harden ?? []).length === 0 && <p className="note">{t("command.noHarden")}</p>}
        <ul className="harden">
          {[...(infra?.harden ?? [])]
            .sort((a, b) => a.rank - b.rank)
            .slice(0, 10)
            .map((h) => (
              <li
                key={h.edge_id + h.rank}
                onClick={() => {
                  if (!layers.infra) set({ layers: { ...layers, infra: true } });
                  flyToPath(h.path);
                }}
              >
                <span style={{ color: "var(--magenta)", width: 26 }}>#{h.rank}</span>
                <span style={{ flex: 1 }}>{h.name ?? h.edge_id}</span>
                <span className="muted">{t("command.pBlocked", { p: fmtNum(h.p_blocked_any * 100, 0) })}</span>
              </li>
            ))}
        </ul>
      </Section>
    </div>
  );
}
