import { useMemo, useState } from "react";
import type { Depot, Shipment, Unmet } from "../../api/types";
import { flyToEntity, flyToPath, flyToPoint } from "../../globe/controller";
import { t } from "../../i18n/t";
import { useStore } from "../../state/store";
import { fmtIso, fmtNum, ms } from "../../time";
import { VirtualTable, type Col } from "../VirtualTable";
import { PlanGate, Section } from "./common";

type ShipStatus = "planned" | "enRoute" | "delivered";

function shipStatus(s: Shipment, tMs: number): ShipStatus {
  if (tMs < ms(s.depart_t)) return "planned";
  if (tMs < ms(s.arrive_t)) return "enRoute";
  return "delivered";
}

/** The Supply view: depot stock, the shipments, and the unmet demand. */
export function SupplyPanel() {
  const meta = useStore((s) => s.meta);
  const statics = useStore((s) => s.statics);
  const plan = useStore((s) => s.planScenario?.plan);
  const firstStage = useStore((s) => s.planCommon?.firstStage);
  const hour = useStore((s) => s.hour);
  const t0 = useStore((s) => s.t0Ms);
  const scenarioId = useStore((s) => s.scenarioId);
  const scenarios = useStore((s) => s.stage1?.scenarios?.scenarios);
  const [commodity, setCommodity] = useState<string>("all");
  const [selected, setSelected] = useState<string | null>(null);
  const tMs = t0 + hour * 3_600_000;
  const commodities = meta?.commodities?.map((c) => c.id) ?? [];
  const scLabel = scenarios?.find((s) => s.id === scenarioId)?.label ?? `S${scenarioId}`;

  const siteName = useMemo(() => {
    const m = new Map<string, string>();
    for (const s of statics?.shelters ?? []) m.set(s.id, s.name);
    for (const h of statics?.hospitals ?? []) m.set(h.id, h.name);
    for (const d of statics?.depots ?? []) m.set(d.id, d.name);
    return m;
  }, [statics]);

  const staged = useMemo(() => {
    const m = new Map<string, Record<string, number>>();
    for (const d of plan?.depots ?? []) m.set(d.id, d.staged ?? {});
    if (m.size === 0) {
      for (const s of firstStage?.staging ?? []) {
        const r = m.get(s.depot_id) ?? {};
        r[s.commodity] = (r[s.commodity] ?? 0) + s.qty;
        m.set(s.depot_id, r);
      }
    }
    return m;
  }, [plan, firstStage]);

  // One row for each commodity and one column for each depot, so that the table fits the panel.
  const depotList: Depot[] = statics?.depots ?? [];
  const depotCols: Col<string>[] = [
    { key: "c", header: t("supply.commodity"), render: (c) => (c === "__trucks" ? t("supply.trucks") : t(`commodity.${c}`)) },
    ...depotList.map(
      (d): Col<string> => ({
        key: d.id,
        header: d.name.length > 18 ? `${d.name.slice(0, 17)}…` : d.name,
        num: true,
        render: (c) =>
          c === "__trucks" ? (
            fmtNum(d.trucks)
          ) : (
            <span title={t("supply.stagedTip")}>
              <span className="ok">{fmtNum(staged.get(d.id)?.[c] ?? 0)}</span>
              <span className="muted"> / {fmtNum(d.inventory?.[c] ?? 0)}</span>
            </span>
          ),
      }),
    ),
  ];

  const ships = (plan?.shipments ?? []).filter((s) => commodity === "all" || s.commodity === commodity);
  const shipCols: Col<Shipment>[] = [
    { key: "id", header: t("supply.shipment"), render: (s) => s.id },
    { key: "c", header: t("supply.commodity"), render: (s) => t(`commodity.${s.commodity}`) },
    { key: "qty", header: t("supply.qty"), num: true, render: (s) => `${fmtNum(s.qty)} ${s.unit}` },
    { key: "to", header: t("supply.to"), render: (s) => siteName.get(s.site_id) ?? s.site_id },
    {
      key: "dep",
      header: t("supply.depart"),
      render: (s) => <span title={`${t("supply.truck")} ${s.truck_id} · ${t("supply.arrive")} ${fmtIso(s.arrive_t)}`}>{fmtIso(s.depart_t)}</span>,
    },
    {
      key: "st",
      header: t("supply.status"),
      render: (s) => {
        const st = shipStatus(s, tMs);
        return <span className={st === "enRoute" ? "warn" : st === "delivered" ? "ok" : "muted"}>{t(`shipStatus.${st}`)}</span>;
      },
    },
  ];

  const unmetCols: Col<Unmet>[] = [
    { key: "site", header: t("supply.site"), render: (u) => siteName.get(u.site_id) ?? u.site_id },
    { key: "w", header: t("supply.window"), render: (u) => fmtIso(u.window_start) },
    { key: "c", header: t("supply.commodity"), render: (u) => t(`commodity.${u.commodity}`) },
    { key: "q", header: t("supply.qty"), num: true, render: (u) => <span className="bad">{`${fmtNum(u.qty)} ${u.unit}`}</span> },
    { key: "sc", header: t("supply.scenario"), render: () => scLabel },
  ];

  const flyShipment = (s: Shipment) => {
    setSelected(s.id);
    if (flyToEntity(`truck:${s.truck_id}`)) return;
    const st = shipStatus(s, tMs);
    const p = st === "planned" ? s.path[0] : st === "delivered" ? s.path[s.path.length - 1] : null;
    if (p) flyToPoint(p[0], p[1], 9000);
    else flyToPath(s.path);
  };

  return (
    <div data-testid="panel-supply">
      <Section title={t("supply.depots")}>
        <VirtualTable rows={[...commodities, "__trucks"]} cols={depotCols} rowKey={(c) => c} />
        <div className="filters" style={{ marginTop: 6 }}>
          {depotList.map((d) => (
            <button key={d.id} className="btn" onClick={() => flyToPoint(d.lon, d.lat, 9000)}>
              {t("supply.flyDepot", { name: d.name })}
            </button>
          ))}
        </div>
        <p className="muted" style={{ fontSize: 10 }}>
          {t("supply.depotNote")}
        </p>
      </Section>
      <PlanGate>
        <Section title={t("supply.shipments", { n: ships.length })}>
          <div className="filters">
            {["all", ...commodities].map((c) => (
              <button key={c} className={`btn ${commodity === c ? "on" : ""}`} onClick={() => setCommodity(c)}>
                {c === "all" ? t("common.all") : t(`commodity.${c}`)}
              </button>
            ))}
          </div>
          <VirtualTable
            rows={ships}
            cols={shipCols}
            rowKey={(s) => s.id}
            rowClass={(s) => (s.id === selected ? "sel" : "")}
            onRowClick={flyShipment}
            maxHeight={300}
            empty={t("supply.noShipments")}
          />
        </Section>
        <Section title={t("supply.unmet")}>
          <VirtualTable
            rows={plan?.unmet ?? []}
            cols={unmetCols}
            rowKey={(u) => `${u.site_id}|${u.window_start}|${u.commodity}`}
            onRowClick={(u) => {
              const s =
                statics?.shelters.find((x) => x.id === u.site_id) ?? statics?.hospitals.find((x) => x.id === u.site_id);
              if (s) flyToPoint(s.lon, s.lat, 9000);
            }}
            empty={t("supply.noUnmet")}
          />
        </Section>
      </PlanGate>
    </div>
  );
}
