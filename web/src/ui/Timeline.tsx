import { useEffect, useRef, type PointerEvent as RPointerEvent } from "react";
import { getHourF, setHour } from "../globe/controller";
import { t } from "../i18n/t";
import { selectScenario } from "../state/data";
import { useStore } from "../state/store";
import { fmtNum, fmtShort, hoursFrom } from "../time";

function hoursOf(meta: { hours?: number } | null): number {
  return meta?.hours ?? 120;
}

/** The timeline: a scrubber with advisory ticks, landfall markers, and the scenario strip. */
export function Timeline() {
  const meta = useStore((s) => s.meta);
  const t0 = useStore((s) => s.t0Ms);
  const hour = useStore((s) => s.hour);
  const stage1 = useStore((s) => s.stage1);
  const planCommon = useStore((s) => s.planCommon);
  const planAdv = useStore((s) => s.activePlanAdvisory);
  const scenarioId = useStore((s) => s.scenarioId);
  const kpiMode = useStore((s) => s.kpiMode);
  const set = useStore((s) => s.set);
  const trackRef = useRef<HTMLDivElement>(null);
  const knobRef = useRef<HTMLDivElement>(null);
  const fillRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const total = hoursOf(meta);

  useEffect(() => {
    let raf = 0;
    const loop = () => {
      const pct = `${(Math.max(0, Math.min(total, getHourF())) / total) * 100}%`;
      if (knobRef.current) knobRef.current.style.left = pct;
      if (fillRef.current) fillRef.current.style.width = pct;
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [total]);

  const hourAt = (clientX: number) => {
    const el = trackRef.current;
    if (!el) return 0;
    const r = el.getBoundingClientRect();
    return (Math.max(0, Math.min(r.width, clientX - r.left)) / r.width) * total;
  };
  const onDown = (e: RPointerEvent<HTMLDivElement>) => {
    dragging.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    setHour(hourAt(e.clientX));
  };
  const onMove = (e: RPointerEvent<HTMLDivElement>) => {
    if (dragging.current) setHour(hourAt(e.clientX));
  };
  const onUp = (e: RPointerEvent<HTMLDivElement>) => {
    if (!dragging.current) return;
    dragging.current = false;
    // Snap to the nearest whole hour when the drag stops.
    setHour(Math.round(hourAt(e.clientX)));
  };

  const pos = (h: number) => `${(Math.max(0, Math.min(total, h)) / total) * 100}%`;
  const days = Array.from({ length: Math.floor(total / 6) + 1 }, (_v, i) => i * 6);
  const p50 = stage1?.landfall?.landfall_time_p50 ?? null;
  const p10 = stage1?.landfall?.landfall_time_p10 ?? null;
  const p90 = stage1?.landfall?.landfall_time_p90 ?? null;
  const truth = meta?.truth_landfall?.time ?? null;
  const truthH = truth ? hoursFrom(t0, truth) : Number.NaN;
  const scenarios = stage1?.scenarios?.scenarios ?? [];
  const worstId = planCommon?.aggregate?.worst_case ?? null;
  const sameAdv = stage1?.advisory === planAdv;

  return (
    <footer className="timebar">
      <div
        className="track-wrap"
        ref={trackRef}
        data-testid="timeline"
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight") setHour(Math.floor(getHourF()) + 1);
          if (e.key === "ArrowLeft") setHour(Math.ceil(getHourF()) - 1);
        }}
        tabIndex={0}
        role="slider"
        aria-label={t("time.scrub")}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={hour}
      >
        <div className="track-line" />
        {p10 && p90 && (
          <div
            style={{
              position: "absolute",
              top: 16,
              height: 7,
              left: pos(hoursFrom(t0, p10)),
              width: `calc(${pos(hoursFrom(t0, p90))} - ${pos(hoursFrom(t0, p10))})`,
              background: "rgba(255,179,0,0.25)",
              borderRadius: 3,
            }}
            title={t("time.landfallWindow")}
          />
        )}
        <div className="track-fill" ref={fillRef} />
        {days.map((h) => (
          <div key={h}>
            <div className={`tick ${h % 24 === 0 ? "day" : ""}`} style={{ left: pos(h) }} />
            {h % 12 === 0 && (
              <div className="tick-label" style={{ left: pos(h) }}>
                {h === 0 ? t("time.t0") : `${fmtShort(t0 + h * 3_600_000)}`}
              </div>
            )}
          </div>
        ))}
        {(meta?.advisories ?? []).map((a) => (
          <div
            key={a}
            className={`adv-tick ${meta?.plan_advisories?.includes(a) ? "plan" : ""}`}
            style={{ left: pos(hoursFrom(t0, a)) }}
            title={`${t("time.advisory")} ${fmtShort(Date.parse(a))}`}
          />
        ))}
        {p50 && (
          <div className="marker warn left" style={{ left: pos(hoursFrom(t0, p50)) }}>
            {t("time.p50Landfall")}
          </div>
        )}
        {truth && hour >= truthH && (
          <div className="marker right" style={{ left: pos(truthH), color: "#fff" }}>
            {t("time.observed")}
          </div>
        )}
        <div className="knob" ref={knobRef} />
      </div>
      <div className="time-row">
        <span className="muted">{t("time.scenarios")}</span>
        <div className="scen" data-testid="scenarios">
          {scenarios.length === 0 && <span className="muted">{t("time.noScenarios")}</span>}
          {scenarios.map((sc) => {
            const worst = sc.is_worst || (sameAdv && worstId === sc.id);
            return (
              <button
                key={sc.id}
                className={`sc ${sc.id === scenarioId ? "on" : ""} ${worst ? "worst" : ""}`}
                onClick={() => selectScenario(sc.id)}
                title={t("time.scenarioTip", {
                  label: sc.label,
                  p: fmtNum(sc.probability * 100, 1),
                  cat: sc.category ?? "—",
                })}
              >
                {sc.label}
                {worst ? ` ${t("time.worstMark")}` : ""} <span className="muted">{fmtNum(sc.probability * 100, 0)}%</span>
                <span className="p" style={{ width: `${Math.min(100, sc.probability * 400)}%` }} />
              </button>
            );
          })}
        </div>
        <button
          className={`btn ${kpiMode === "expected" ? "on" : ""}`}
          data-testid="mode-expected"
          onClick={() => set({ kpiMode: "expected" })}
        >
          {t("time.expected")}
        </button>
        <button
          className={`btn ${kpiMode === "worst10" ? "on" : ""}`}
          data-testid="mode-worst"
          onClick={() => {
            set({ kpiMode: "worst10" });
            if (worstId !== null && worstId !== undefined) selectScenario(worstId);
          }}
        >
          {t("time.worst10")}
        </button>
      </div>
    </footer>
  );
}
