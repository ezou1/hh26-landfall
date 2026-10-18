import { useMemo, useState } from "react";
import type { Infrastructure, LonLat, Meta, RoadStatus, ScenarioPlan, Shipment, Statics, Unmet } from "../../api/types";
import { clearHighlight, flyToPath, flyToPoint, highlightPath, highlightPoint } from "../../globe/controller";
import { areaCentroid } from "../../globe/geo";
import { t } from "../../i18n/t";
import { earliestTsArrival } from "../../state/derive";
import { VIEW_LAYERS } from "../../state/presets";
import { useStore, type LayerId } from "../../state/store";
import { fmtHours, fmtIso, fmtNum, ms } from "../../time";
import { PlanGate, Section } from "./common";

type Who = "evac" | "supply" | "both";
type Phase = "before" | "during" | "after";
type Status = "done" | "late" | "now" | "next" | "later" | "info";
type Filter = "all" | "evac" | "supply";

/** One line of the plan: an action with a time, an owner, and a place on the globe. */
interface Item {
  id: string;
  who: Who;
  tMs: number;
  title: string;
  detail: string;
  late: boolean;
  info: boolean;
  path: LonLat[] | null;
  point: LonLat | null;
  layers: LayerId[];
}

const H = 3_600_000;

function statusOf(it: Item, nowMs: number): Status {
  if (it.info) return "info";
  if (it.late) return "late";
  if (it.tMs <= nowMs) return "done";
  if (it.tMs <= nowMs + 6 * H) return "now";
  if (it.tMs <= nowMs + 24 * H) return "next";
  return "later";
}

function dueText(tMs: number, nowMs: number): string {
  const h = (tMs - nowMs) / H;
  if (Math.abs(h) < 0.5) return t("plan.due.now");
  return h < 0 ? t("plan.due.past", { h: Math.round(-h) }) : t("plan.due.in", { h: Math.round(h) });
}

function qtyText(q: Record<string, number>, unitOf: (c: string) => string): string {
  return Object.entries(q)
    .filter(([, v]) => v > 0)
    .map(([c, v]) => `${t(`commodity.${c}`)} ${fmtNum(v)} ${unitOf(c)}`)
    .join(" · ");
}

/** The Plan view: the actions of the evacuation lead and the supply lead, in time order. */
export function PlanningPanel() {
  const plan = useStore((s) => s.planScenario?.plan);
  const statics = useStore((s) => s.statics);
  const meta = useStore((s) => s.meta);
  const infra = useStore((s) => s.planCommon?.infrastructure);
  const hour = useStore((s) => s.hour);
  const t0 = useStore((s) => s.t0Ms);
  const focus = useStore((s) => s.focus);
  const set = useStore((s) => s.set);
  const [filter, setFilter] = useState<Filter>("all");
  const [copied, setCopied] = useState(false);
  const nowMs = t0 + hour * H;

  const items = useMemo(() => buildItems(plan, statics, meta, infra), [plan, statics, meta, infra]);

  const tsMs = earliestTsArrival(plan);
  const holdEnd = items.find((i) => i.id === "hold")?.tMs ?? Number.NaN;
  const phaseOf = (it: Item): Phase => {
    if (!Number.isFinite(tsMs) || it.tMs < tsMs) return "before";
    if (Number.isFinite(holdEnd) && it.tMs < holdEnd + 6 * H) return "during";
    return "after";
  };
  const shown = items.filter((i) => filter === "all" || i.who === filter || i.who === "both");
  const groups: Record<Phase, Item[]> = { before: [], during: [], after: [] };
  for (const it of shown) groups[phaseOf(it)].push(it);
  const nextUp = shown.filter((i) => !i.info && i.tMs > nowMs - 0.5 * H).slice(0, 3);
  const lateCount = shown.filter((i) => i.late).length;

  const show = (it: Item) => {
    const layers = { ...VIEW_LAYERS.plan };
    for (const id of Object.keys(layers) as LayerId[]) layers[id] = it.layers.includes(id) || id === "zones" || id === "roads";
    set({ focus: { id: it.id, label: it.title }, layers });
    if (it.path && it.path.length > 1) {
      highlightPath(it.path);
      flyToPath(it.path);
    } else if (it.point) {
      highlightPoint(it.point[0], it.point[1]);
      flyToPoint(it.point[0], it.point[1], 14_000);
    }
  };
  const showAll = () => {
    clearHighlight();
    set({ focus: null, layers: VIEW_LAYERS.plan });
  };
  const copy = () => {
    const lines = shown.map((i) => `${fmtIso(new Date(i.tMs).toISOString())}  [${t(`plan.who.${i.who}`)}] ${i.title} — ${i.detail}`);
    void navigator.clipboard?.writeText(lines.join("\n")).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    });
  };

  const row = (it: Item) => {
    const st = statusOf(it, nowMs);
    return (
      <li key={it.id} className={`plan-item ${st} ${focus?.id === it.id ? "sel" : ""}`} onClick={() => show(it)} data-testid="plan-item">
        <div className="plan-time">
          <span className="t">{fmtIso(new Date(it.tMs).toISOString())}</span>
          <span className="d">{it.info ? "" : dueText(it.tMs, nowMs)}</span>
        </div>
        <div className="plan-body">
          <div className="plan-head">
            <span className={`who ${it.who}`}>{t(`plan.who.${it.who}`)}</span>
            <span className="title">{it.title}</span>
            <span className={`st ${st}`}>{t(`plan.status.${st}`)}</span>
          </div>
          <div className="plan-detail">{it.detail}</div>
        </div>
      </li>
    );
  };

  return (
    <div data-testid="panel-plan">
      <Section title={t("plan.title")}>
        <p className="muted" style={{ fontSize: 10.5, margin: "0 0 8px" }}>
          {t("plan.intro")}
        </p>
        <div className="filters">
          {(["all", "evac", "supply"] as Filter[]).map((f) => (
            <button key={f} className={`btn ${filter === f ? "on" : ""}`} onClick={() => setFilter(f)}>
              {t(`plan.${f}`)}
            </button>
          ))}
          <span className="spacer" />
          {lateCount > 0 && <span className="chip late">{t("plan.lateCount", { n: lateCount })}</span>}
          <button className="btn" onClick={copy}>
            {copied ? t("plan.copied") : t("plan.copy")}
          </button>
        </div>
        {focus && (
          <div className="plan-focus">
            <span>{t("plan.focus", { label: focus.label })}</span>
            <button className="btn sm" onClick={showAll}>
              {t("plan.showAll")}
            </button>
          </div>
        )}
      </Section>
      <PlanGate>
        <Section title={t("plan.nextUp")}>
          {nextUp.length === 0 ? <p className="note">{t("plan.noNext")}</p> : <ul className="plan-list">{nextUp.map(row)}</ul>}
        </Section>
        {(["before", "during", "after"] as Phase[]).map((ph) =>
          groups[ph].length === 0 ? null : (
            <Section key={ph} title={t(`plan.phase.${ph}`)}>
              <ul className="plan-list">{groups[ph].map(row)}</ul>
            </Section>
          ),
        )}
      </PlanGate>
    </div>
  );
}

function buildItems(
  plan: ScenarioPlan | null | undefined,
  statics: Statics | null,
  meta: Meta | null,
  infra: Infrastructure | null | undefined,
): Item[] {
  if (!plan) return [];
  const out: Item[] = [];
  const unitOf = (c: string) => meta?.commodities?.find((x) => x.id === c)?.unit ?? "";
  const advMs = ms(plan.advisory_time);
  const releases = plan.zones.map((z) => ms(z.release_time)).filter(Number.isFinite);
  const firstRelease = releases.length ? Math.min(...releases) : advMs;

  // Zones
  for (const z of plan.zones) {
    const feat = statics?.zones?.features.find((f) => String(f.properties?.zone) === z.zone);
    const point = areaCentroid(feat?.geometry);
    const rel = ms(z.release_time);
    if (Number.isFinite(rel)) {
      out.push({
        id: `zone:${z.zone}`,
        who: "evac",
        tMs: rel,
        title: t("plan.item.orderZone", { zone: z.zone }),
        detail: t("plan.item.orderZoneDetail", { n: fmtNum(z.evacuees), clear: fmtIso(z.clearance_time), ts: fmtIso(z.ts_arrival), margin: fmtHours(z.margin_h) }),
        late: z.margin_h !== null && z.margin_h < 0,
        info: false,
        path: null,
        point,
        layers: ["zones", "evac", "shelters"],
      });
    } else {
      out.push({
        id: `zone:${z.zone}`,
        who: "evac",
        tMs: firstRelease,
        title: t("plan.item.noOrder", { zone: z.zone }),
        detail: t("plan.item.noOrderDetail", { n: fmtNum(z.population) }),
        late: false,
        info: true,
        path: null,
        point,
        layers: ["zones"],
      });
    }
  }
  // Shelters
  for (const sp of plan.shelters) {
    if (!sp.open) continue;
    const s = statics?.shelters.find((x) => x.id === sp.id);
    const peak = Math.max(0, ...(sp.occupancy ?? [0]));
    const flag = infra?.shelters_flagged?.find((x) => x.shelter_id === sp.id);
    out.push({
      id: `shelter:${sp.id}`,
      who: "evac",
      tMs: firstRelease,
      title: t("plan.item.openShelter", { name: s?.name ?? sp.id }),
      detail: t("plan.item.openShelterDetail", { cap: fmtNum(sp.capacity), peak: fmtNum(peak) }) + (flag ? ` ${t("plan.item.pFull", { p: fmtNum(flag.p_full * 100) })}` : ""),
      late: false,
      info: false,
      path: null,
      point: s ? [s.lon, s.lat] : null,
      layers: ["shelters"],
    });
  }
  // Staging
  for (const d of plan.depots) {
    const dep = statics?.depots.find((x) => x.id === d.id);
    const text = qtyText(d.staged ?? {}, unitOf);
    if (!text) continue;
    out.push({
      id: `stage:${d.id}`,
      who: "supply",
      tMs: Math.min(advMs + 6 * H, firstRelease),
      title: t("plan.item.stage", { name: dep?.name ?? d.id }),
      detail: text,
      late: false,
      info: false,
      path: null,
      point: dep ? [dep.lon, dep.lat] : null,
      layers: ["supply"],
    });
  }
  // Deliveries grouped by depot and site
  const groups = new Map<string, Shipment[]>();
  for (const s of plan.shipments) {
    const k = `${s.depot_id}|${s.site_id}`;
    groups.set(k, [...(groups.get(k) ?? []), s]);
  }
  const siteName = (id: string) =>
    statics?.shelters.find((x) => x.id === id)?.name ?? statics?.hospitals.find((x) => x.id === id)?.name ?? id;
  for (const [k, list] of groups) {
    list.sort((a, b) => ms(a.depart_t) - ms(b.depart_t));
    const q: Record<string, number> = {};
    for (const s of list) q[s.commodity] = (q[s.commodity] ?? 0) + s.qty;
    const dep = statics?.depots.find((x) => x.id === list[0].depot_id);
    out.push({
      id: `deliver:${k}`,
      who: "supply",
      tMs: ms(list[0].depart_t),
      title: t("plan.item.deliver", { site: siteName(list[0].site_id) }),
      detail: `${t("plan.item.deliverDetail", { n: list.length, depot: dep?.name ?? list[0].depot_id, t: fmtIso(list[0].depart_t) })} ${qtyText(q, unitOf)}`,
      late: false,
      info: false,
      path: list[0].path,
      point: null,
      layers: ["supply", "roads"],
    });
  }
  // Hold window
  const tsMs = earliestTsArrival(plan);
  if (Number.isFinite(tsMs)) {
    const before = plan.shipments.filter((s) => ms(s.arrive_t) <= tsMs).map((s) => ms(s.arrive_t));
    out.push({
      id: "hold",
      who: "both",
      tMs: tsMs,
      title: t("plan.item.hold"),
      detail: t("plan.item.holdDetail", { t: before.length ? fmtIso(new Date(Math.max(...before)).toISOString()) : "—" }),
      late: false,
      info: false,
      path: null,
      point: null,
      layers: ["storm", "wind"],
    });
  }
  // Critical road blocks, one line for each critical link
  const blocks = new Map<string, RoadStatus[]>();
  for (const r of plan.road_status) {
    if (!r.is_critical) continue;
    const k = r.critical_name ?? r.edge_id;
    blocks.set(k, [...(blocks.get(k) ?? []), r]);
  }
  for (const [name, list] of blocks) {
    list.sort((a, b) => ms(a.blocked_t) - ms(b.blocked_t));
    const r = list[0];
    const reopen = list.map((x) => ms(x.reopen_t)).filter(Number.isFinite);
    const detail = reopen.length === list.length
      ? t("plan.item.blockedDetail", { cause: t(`plan.cause.${r.cause}`), t: fmtIso(new Date(Math.max(...reopen)).toISOString()) })
      : t("plan.item.blockedNever", { cause: t(`plan.cause.${r.cause}`) });
    out.push({
      id: `road:${name}`,
      who: "both",
      tMs: ms(r.blocked_t),
      title: t("plan.item.blocked", { name }),
      detail: list.length > 1 ? `${detail} ${t("plan.item.segments", { n: list.length })}` : detail,
      late: false,
      info: false,
      path: r.path,
      point: null,
      layers: ["roads", "debris"],
    });
  }
  // Unmet demand, one line for each site
  const unmet = new Map<string, Unmet[]>();
  for (const u of plan.unmet) unmet.set(u.site_id, [...(unmet.get(u.site_id) ?? []), u]);
  for (const [siteId, list] of unmet) {
    list.sort((a, b) => ms(a.window_start) - ms(b.window_start));
    const q: Record<string, number> = {};
    for (const u of list) q[u.commodity] = (q[u.commodity] ?? 0) + u.qty;
    const s = statics?.shelters.find((x) => x.id === siteId) ?? statics?.hospitals.find((x) => x.id === siteId);
    out.push({
      id: `unmet:${siteId}`,
      who: "supply",
      tMs: ms(list[0].window_start),
      title: t("plan.item.unmet", { site: siteName(siteId) }),
      detail: t("plan.item.unmetDetail", { n: list.length, t: fmtIso(list[0].window_start) }) + " " + qtyText(q, unitOf),
      late: true,
      info: false,
      path: null,
      point: s ? [s.lon, s.lat] : null,
      layers: ["supply", "shelters", "hospitals"],
    });
  }
  return out.filter((i) => Number.isFinite(i.tMs)).sort((a, b) => a.tMs - b.tMs || Number(a.info) - Number(b.info));
}
