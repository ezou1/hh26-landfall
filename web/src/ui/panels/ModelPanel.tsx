import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { VerifySummary } from "../../api/types";
import { t } from "../../i18n/t";
import { useStore } from "../../state/store";
import { fmtIso, fmtNum } from "../../time";
import { chartStyle } from "./chartStyle";
import { Section } from "./common";

const METHODS: { id: "model" | "cliper" | "ofcl"; color: string; dash?: string }[] = [
  { id: "model", color: "#3987e5" },
  { id: "cliper", color: "#d95926", dash: "5 3" },
  { id: "ofcl", color: "#199e70" },
];

function errorRows(v: VerifySummary, field: "track_km" | "intensity_kt") {
  return v.leads_h.map((lead, i) => {
    const row: Record<string, number | null> = { lead };
    for (const m of METHODS) row[m.id] = v.methods?.[m.id]?.[field]?.[i] ?? null;
    return row;
  });
}

function ErrorChart({ v, field, unit }: { v: VerifySummary; field: "track_km" | "intensity_kt"; unit: string }) {
  return (
    <div className="chart-box" style={{ height: 190 }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={errorRows(v, field)} margin={{ left: 0, right: 14, top: 8, bottom: 14 }}>
          <CartesianGrid stroke={chartStyle.grid} />
          <XAxis
            dataKey="lead"
            tick={chartStyle.axis}
            label={{ value: t("model.leadH"), position: "insideBottom", offset: -6, ...chartStyle.axis }}
          />
          <YAxis tick={chartStyle.axis} width={42} unit={unit} />
          <Tooltip
            {...chartStyle.tooltip}
            labelFormatter={(l) => t("model.leadLabel", { h: String(l) })}
            formatter={(val, name) => [`${fmtNum(Number(val), 0)} ${unit}`, t(`model.method.${String(name)}`)]}
          />
          <Legend
            verticalAlign="top"
            height={22}
            wrapperStyle={{ fontSize: 10 }}
            formatter={(name: string) => <span style={{ color: "#d7e3ee" }}>{t(`model.method.${name}`)}</span>}
          />
          {METHODS.map((m) => (
            <Line
              key={m.id}
              type="monotone"
              dataKey={m.id}
              stroke={m.color}
              strokeWidth={2}
              strokeDasharray={m.dash}
              dot={{ r: 4, strokeWidth: 0, fill: m.color }}
              activeDot={{ r: 5 }}
              connectNulls
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** The Model view: forecast error by lead time, ensemble spread, and the rank histogram. */
export function ModelPanel() {
  const v = useStore((s) => s.verify);
  const landfall = useStore((s) => s.stage1?.landfall);
  const ensemble = useStore((s) => s.stage1?.ensemble);
  const order = ["TD", "TS", "1", "2", "3", "4", "5"];
  const cats = landfall
    ? Object.entries(landfall.category_dist ?? {})
        .map(([k, p]) => ({ cat: k, p: p * 100 }))
        .sort((a, b) => order.indexOf(a.cat) - order.indexOf(b.cat))
    : [];

  return (
    <div data-testid="panel-model">
      <Section title={t("model.advisory")}>
        <table className="grid">
          <tbody>
            <tr>
              <td>{t("model.advisoryTime")}</td>
              <td className="num">{fmtIso(landfall?.advisory_time ?? ensemble?.advisory_time)}</td>
            </tr>
            <tr>
              <td>{t("model.members")}</td>
              <td className="num">
                {fmtNum(ensemble?.n_members)} ({t("model.drawn", { n: ensemble?.members.length ?? 0 })})
              </td>
            </tr>
            <tr>
              <td>{t("model.landfallWindow")}</td>
              <td className="num">
                {fmtIso(landfall?.landfall_time_p10)} – {fmtIso(landfall?.landfall_time_p90)}
              </td>
            </tr>
          </tbody>
        </table>
      </Section>
      {cats.length > 0 && (
        <Section title={t("model.categories")}>
          <div className="chart-box" style={{ height: 140 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={cats} margin={{ left: 0, right: 12, top: 8, bottom: 0 }}>
                <CartesianGrid stroke={chartStyle.grid} vertical={false} />
                <XAxis dataKey="cat" tick={chartStyle.axis} />
                <YAxis tick={chartStyle.axis} width={36} unit="%" />
                <Tooltip
                  {...chartStyle.tooltip}
                  cursor={{ fill: "rgba(79,195,247,0.08)" }}
                  formatter={(val) => [`${fmtNum(Number(val), 0)}%`, t("model.probability")]}
                />
                <Bar dataKey="p" fill="#3987e5" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Section>
      )}
      {!v && <p className="note">{t("model.noVerify")}</p>}
      {v && (
        <>
          <Section title={t("model.trackError")}>
            <ErrorChart v={v} field="track_km" unit="km" />
          </Section>
          <Section title={t("model.intensityError")}>
            <ErrorChart v={v} field="intensity_kt" unit="kt" />
          </Section>
          <Section title={t("model.spread")}>
            <div className="chart-box" style={{ height: 150 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={v.leads_h.map((lead, i) => ({ lead, spreadKm: v.spread_km?.[i] ?? null, err: v.methods?.model?.track_km?.[i] ?? null }))}
                  margin={{ left: 0, right: 14, top: 8, bottom: 14 }}
                >
                  <CartesianGrid stroke={chartStyle.grid} />
                  <XAxis
                    dataKey="lead"
                    tick={chartStyle.axis}
                    label={{ value: t("model.leadH"), position: "insideBottom", offset: -6, ...chartStyle.axis }}
                  />
                  <YAxis tick={chartStyle.axis} width={42} unit="km" />
                  <Tooltip
                    {...chartStyle.tooltip}
                    labelFormatter={(l) => t("model.leadLabel", { h: String(l) })}
                    formatter={(val, name) => [`${fmtNum(Number(val), 0)} km`, t(`model.${String(name)}`)]}
                  />
                  <Legend
                    verticalAlign="top"
            height={22}
            wrapperStyle={{ fontSize: 10 }}
                    formatter={(name: string) => <span style={{ color: "#d7e3ee" }}>{t(`model.${name}`)}</span>}
                  />
                  <Line dataKey="spreadKm" stroke="#3987e5" strokeWidth={2} dot={{ r: 4 }} connectNulls isAnimationActive={false} />
                  <Line dataKey="err" stroke="#d95926" strokeWidth={2} strokeDasharray="5 3" dot={{ r: 4 }} connectNulls isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <p className="muted" style={{ fontSize: 10 }}>
              {t("model.spreadNote")}
            </p>
          </Section>
          <Section title={t("model.rankHist")}>
            <div className="chart-box" style={{ height: 150 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={(v.rank_hist?.bins ?? []).map((b, i) => ({ bin: b, count: v.rank_hist.counts?.[i] ?? 0 }))}
                  margin={{ left: 0, right: 12, top: 8, bottom: 14 }}
                >
                  <CartesianGrid stroke={chartStyle.grid} vertical={false} />
                  <XAxis
                    dataKey="bin"
                    tick={chartStyle.axis}
                    label={{ value: t("model.rank"), position: "insideBottom", offset: -6, ...chartStyle.axis }}
                  />
                  <YAxis tick={chartStyle.axis} width={36} allowDecimals={false} />
                  <Tooltip
                    {...chartStyle.tooltip}
                    cursor={{ fill: "rgba(79,195,247,0.08)" }}
                    formatter={(val) => [fmtNum(Number(val)), t("model.cases")]}
                  />
                  <Bar dataKey="count" fill="#3987e5" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <p className="muted" style={{ fontSize: 10 }}>
              {t("model.rankNote", { n: v.n_cases })}
            </p>
          </Section>
        </>
      )}
    </div>
  );
}
