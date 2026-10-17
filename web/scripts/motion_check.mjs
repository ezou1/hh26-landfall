// Check acceptance item 8: the storm, a truck, and a helicopter move when the clock moves.
// Usage: node scripts/motion_check.mjs [url]. Exits with code 1 if an entity does not move.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";

const url = process.argv[2] ?? "http://localhost:5173";
const env = { ...process.env };
const localLibs = path.join(os.homedir(), ".local/pwlibs/root/usr/lib/x86_64-linux-gnu");
if (fs.existsSync(localLibs)) {
  env.LD_LIBRARY_PATH = [localLibs, path.join(localLibs, "nss"), env.LD_LIBRARY_PATH].filter(Boolean).join(":");
  process.env.PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS = "1";
}
const browser = await chromium.launch({
  headless: true,
  env,
  args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"],
});
const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
page.setDefaultTimeout(180000);
await page.goto(url, { waitUntil: "domcontentloaded" });
await page.waitForFunction(() => !!window.__landfall && window.__landfall.ready(), null, { timeout: 180000 });
const call = (fn, ...args) => page.evaluate(([f, a]) => window.__landfall[f](...a), [fn, args]);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function at(h, fn, ...args) {
  await call("setHour", h);
  const t0 = await call("ticks");
  while ((await call("ticks")) < t0 + 3) await sleep(100);
  return call(fn, ...args);
}
// Find the first truck and helicopter sample times from the plan CZML of the default scenario.
const meta = await (await fetch(new URL("/api/meta", url))).json();
const key = meta.default_plan_advisory.slice(0, 13).replace(/[-T]/g, "");
const czml = await (await fetch(new URL(`/out/plan/${key}/s0.czml`, url))).json();
const T0 = Date.parse(meta.t0);
const mid = (p) => {
  const [a, b] = p.availability.split("/").map((s) => (Date.parse(s) - T0) / 3.6e6);
  return [a + (b - a) * 0.25, a + (b - a) * 0.75];
};
const truck = czml.find((p) => p.id.startsWith("truck:"));
const helo = czml.find((p) => p.id.startsWith("asset:a") && p.position.cartographicDegrees.length > 16);
const results = [];
const moved = (a, b) => !!a && !!b && Math.hypot(a[0] - b[0], a[1] - b[1]) > 1e-4;
const s1 = await at(60, "storm");
const s2 = await at(61, "storm");
results.push(["storm", moved([s1.lon, s1.lat], [s2.lon, s2.lat])]);
if (truck) {
  const [a, b] = mid(truck);
  results.push([truck.id, moved(await at(a, "entityLonLat", truck.id), await at(b, "entityLonLat", truck.id))]);
} else results.push(["truck", false]);
if (helo) {
  const c = helo.position.cartographicDegrees;
  const a = c[4] / 3600; // the second sample: the helicopter leaves the base
  const b = c[8] / 3600;
  results.push([helo.id, moved(await at(a + (b - a) * 0.2, "entityLonLat", helo.id), await at(a + (b - a) * 0.8, "entityLonLat", helo.id))]);
} else results.push(["helo", false]);
await browser.close();
for (const [name, ok] of results) console.log(`${ok ? "PASS" : "FAIL"} ${name} moves`);
process.exit(results.every((r) => r[1]) ? 0 : 1);
