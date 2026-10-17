/** Return the time in milliseconds for an ISO string, or NaN if the value is null. */
export function ms(iso: string | null | undefined): number {
  if (!iso) return NaN;
  return Date.parse(iso);
}

/** Return the hours from t0 to the ISO time. */
export function hoursFrom(t0Ms: number, iso: string | null | undefined): number {
  return (ms(iso) - t0Ms) / 3_600_000;
}

const pad = (n: number) => String(n).padStart(2, "0");

/** Format a time as "DD HH:MMZ". */
export function fmtShort(msValue: number): string {
  if (!Number.isFinite(msValue)) return "—";
  const d = new Date(msValue);
  return `${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}Z`;
}

/** Format a time as "YYYY-MM-DD HH:MM:SSZ". */
export function fmtLong(msValue: number): string {
  if (!Number.isFinite(msValue)) return "—";
  const d = new Date(msValue);
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(
    d.getUTCMinutes(),
  )}:${pad(d.getUTCSeconds())}Z`;
}

/** Format an ISO time as "DD HH:MMZ". */
export function fmtIso(iso: string | null | undefined): string {
  return fmtShort(ms(iso));
}

/** Format a number with a fixed count of decimals, or a dash for null. */
export function fmtNum(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

/** Format a value of hours with a sign, for example "+3.5 h". */
export function fmtHours(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const s = v > 0 ? "+" : "";
  return `${s}${v.toFixed(1)} h`;
}

/** Return the value of an hourly series at hour h. Clamp h to the series range. */
export function atHour(series: number[] | null | undefined, h: number): number | null {
  if (!series || series.length === 0) return null;
  const i = Math.max(0, Math.min(series.length - 1, Math.floor(h)));
  const v = series[i];
  return typeof v === "number" ? v : null;
}
