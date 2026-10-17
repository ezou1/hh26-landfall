import { Color } from "cesium";

/** Make a Cesium color from a CSS string and an alpha value. */
export function css(c: string, alpha = 1): Color {
  return Color.fromCssColorString(c).withAlpha(alpha);
}

/** The status colors of the console. */
export const STATUS = {
  ok: "#3ddc84",
  warn: "#ffb300",
  bad: "#ff4d4f",
  info: "#4fc3f7",
  muted: "#7d8b99",
  magenta: "#ff3df2",
};

/** Return a color for a ratio from 0 (good) to 1 or more (bad). */
export function rampGoodBad(r: number, alpha = 1): Color {
  if (!Number.isFinite(r)) return css(STATUS.muted, alpha);
  if (r < 0.5) return css(STATUS.ok, alpha);
  if (r < 0.8) return css("#d4e157", alpha);
  if (r < 1.0) return css(STATUS.warn, alpha);
  return css(STATUS.bad, alpha);
}

/** Return the Saffir-Simpson color for a wind speed in knots. */
export function categoryColor(vmaxKt: number): string {
  if (vmaxKt >= 137) return "#ff00e5";
  if (vmaxKt >= 113) return "#ff2a2a";
  if (vmaxKt >= 96) return "#ff7b1c";
  if (vmaxKt >= 83) return "#ffb21c";
  if (vmaxKt >= 64) return "#ffe14d";
  if (vmaxKt >= 34) return "#5ee4ff";
  return "#9aa7b4";
}

/** Return the Saffir-Simpson category label for a wind speed in knots. */
export function categoryLabel(vmaxKt: number): string {
  if (vmaxKt >= 137) return "5";
  if (vmaxKt >= 113) return "4";
  if (vmaxKt >= 96) return "3";
  if (vmaxKt >= 83) return "2";
  if (vmaxKt >= 64) return "1";
  if (vmaxKt >= 34) return "TS";
  return "TD";
}

/** The colors of the rescue task priorities 1, 2, and 3. */
export const PRIORITY_COLORS: Record<number, string> = { 1: "#ff3b30", 2: "#ff9500", 3: "#ffd60a" };
