// Take screenshots of the LANDFALL UI with headless Chromium.
// Usage: node scripts/screenshot.mjs [url] [outDir] [--extra] [--command-hour=66] [--rescue-hour=102]
//   url    default http://localhost:5173
//   outDir default ../docs/media (relative to the web folder)
//   Writes command.png, supply.png, rescue.png, model.png, cone_t0.png, cone_0927.png
//   (and x_*.png with --extra).
// Exit code 1 if the page throws an error or logs a console error.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium } from "playwright";

const positional = process.argv.slice(2).filter((a) => !a.startsWith("--"));
const flag = (name, def) => {
  const hit = process.argv.find((a) => a.startsWith(`--${name}=`));
  return hit ? Number(hit.split("=")[1]) : def;
};
const opt = {
  extra: process.argv.includes("--extra"),
  commandHour: flag("command-hour", 66),
  rescueHour: flag("rescue-hour", 102),
};
const url = positional[0] ?? "http://localhost:5173";
const outDir = path.resolve(positional[1] ?? "../docs/media");
fs.mkdirSync(outDir, { recursive: true });

// Chromium needs libnss3 and libasound. Without sudo, unpack them to ~/.local/pwlibs (see .dev/frontend_notes.md).
const env = { ...process.env };
const localLibs = path.join(os.homedir(), ".local/pwlibs/root/usr/lib/x86_64-linux-gnu");
if (fs.existsSync(localLibs)) {
  env.LD_LIBRARY_PATH = [localLibs, path.join(localLibs, "nss"), env.LD_LIBRARY_PATH].filter(Boolean).join(":");
  process.env.LD_LIBRARY_PATH = env.LD_LIBRARY_PATH;
  process.env.PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS = "1";
}

const errors = [];
const warnings = [];
const IGNORE = [/Failed to load resource/i, /net::ERR_/i, /favicon/i];

const browser = await chromium.launch({
  headless: true,
  env,
  args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"],
});
const page = await browser.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1 });
page.setDefaultTimeout(120000);
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
page.on("console", (m) => {
  const text = m.text();
  if (m.type() === "error" && !IGNORE.some((r) => r.test(text))) errors.push(`console.error: ${text}`);
  if (m.type() === "warning") warnings.push(text);
});

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function settle(maxMs = 45000) {
  const t0 = Date.now();
  await sleep(800);
  await waitTicks(4, 60000);
  while (Date.now() - t0 < maxMs) {
    const ok = await page.evaluate(() => {
      const l = window.__landfall;
      return !!l && l.ready() && l.tilesLoaded();
    });
    if (ok) break;
    await sleep(400);
  }
  await sleep(900);
}
async function shot(name) {
  const f = path.join(outDir, `${name}.png`);
  await page.screenshot({ path: f, timeout: 120000 });
  console.log(`saved ${f}`);
}
const call = (fn, ...args) => page.evaluate(([f, a]) => window.__landfall[f](...a), [fn, args]);
async function waitTicks(n, maxMs = 30000) {
  const start = await call("ticks");
  const t0 = Date.now();
  while ((await call("ticks")) < start + n && Date.now() - t0 < maxMs) await sleep(100);
}
async function waitCameraMove(before, maxMs = 30000) {
  const t0 = Date.now();
  while (Date.now() - t0 < maxMs) {
    const c = await call("camera");
    if (c && before && Math.abs(c.height - before.height) > 1000) break;
    await sleep(250);
  }
  await waitTicks(30);
}
async function fps() {
  const a = await call("ticks");
  await sleep(3000);
  return ((await call("ticks")) - a) / 3;
}

console.log(`open ${url}`);
await page.goto(url, { waitUntil: "domcontentloaded" });
try {
  await page.waitForFunction(() => !!window.__landfall && window.__landfall.ready(), null, { timeout: 90000 });
} catch (err) {
  await shot("00_timeout");
  const st = await page.evaluate(() => (window.__landfall ? window.__landfall.state() : null)).catch(() => null);
  console.error("the page did not get ready", err.message, JSON.stringify(st));
  console.error(`errors:\n  ${errors.join("\n  ")}\nwarnings:\n  ${warnings.slice(0, 20).join("\n  ")}`);
  await browser.close();
  process.exit(1);
}
await settle(40000);


// Main screenshots. Names match docs/media.
const plan = [
  { hour: opt.commandHour, view: "command", name: "command" },
  { hour: opt.commandHour, view: "supply", name: "supply" },
  { hour: opt.rescueHour, view: "rescue", name: "rescue" },
  { hour: 30, view: "model", name: "model" },
];
for (const p of plan) {
  await call("home");
  await call("setHour", p.hour);
  await page.click(`[data-testid="tab-${p.view}"]`, { force: true, timeout: 120000 });
  await waitTicks(10, 120000);
  await settle();
  await shot(p.name);
}

// The cone narrows at each new advisory. Show a wide view at hour 0 and hour 48.
await page.click('[data-testid="tab-command"]', { force: true, timeout: 120000 });
for (const [h, name] of [
  [0, "cone_t0"],
  [48, "cone_0927"],
]) {
  await call("setHour", h);
  await call("flyTo", -81.5, 21.0, 2_000_000);
  await waitTicks(40, 120000);
  await settle(30000);
  await shot(name);
}
await call("home");

console.log(`frames per second at the home view: ${(await fps()).toFixed(1)}`);
// Check that the storm, a truck, and a helicopter move when the clock moves.
const checks = {};
const firstLive = async (prefix, hours) => {
  for (const h of hours) {
    await call("setHour", h);
    await waitTicks(3);
    const hit = await page.evaluate((pre) => {
      const st = window.__landfall;
      for (let i = 0; i <= 120; i++) {
        for (const id of [`${pre}${String(i).padStart(3, "0")}`, `${pre}${String(i).padStart(2, "0")}`]) {
          const p = st.entityLonLat(id);
          if (p) return { id, p };
        }
      }
      return null;
    }, prefix);
    if (hit) return { h, ...hit };
  }
  return null;
};
await call("setHour", 60);
await waitTicks(3);
checks.storm60 = await call("storm");
await call("setHour", 60.5);
await waitTicks(3);
checks.storm605 = await call("storm");
const truck = await firstLive("truck:tr", [52, 60, 70, 80, 100]);
if (truck) {
  checks.truck = truck;
  await call("setHour", truck.h + 0.25);
  await waitTicks(3);
  checks.truckLater = await call("entityLonLat", truck.id);
}
const helo = await firstLive("asset:a", [98, 102, 106, 110]);
if (helo) {
  checks.helo = helo;
  await call("setHour", helo.h + 0.5);
  await waitTicks(3);
  checks.heloLater = await call("entityLonLat", helo.id);
}
console.log("motion checks", JSON.stringify(checks));

// Click a shipment row of a truck on the road and check that the camera moves.
await call("setHour", truck ? truck.h : 64);
await page.click('[data-testid="tab-supply"]', { force: true, timeout: 120000 });
await settle(8000);
const camBefore = await call("camera");
const rows = page.locator('[data-testid="panel-supply"] table.grid').nth(1).locator("tbody tr.click");
if ((await rows.count()) > 0) {
  const onRoad = rows.filter({ hasText: /on road/ }).first();
  const row = (await onRoad.count()) > 0 ? onRoad : rows.first();
  await row.click({ force: true, timeout: 120000 });
  await waitCameraMove(camBefore);
  await settle(10000);
  const camAfter = await call("camera");
  console.log("camera before", JSON.stringify(camBefore), "after", JSON.stringify(camAfter));
  if (opt.extra) await shot("x_fly_to_truck");
} else {
  errors.push("no shipment row to click");
}
await call("home");

if (opt.extra) {
  // The worst case, and a later hour.
  await call("setHour", 54);
  await page.click('[data-testid="tab-command"]', { force: true, timeout: 120000 });
  await page.click('[data-testid="mode-worst"]', { force: true, timeout: 120000 });
  await settle(8000);
  await shot("x_worst10");
  await page.click('[data-testid="mode-expected"]', { force: true, timeout: 120000 });
  await call("setHour", 110);
  await settle(8000);
  await shot("x_h110_command");
}

const state = await call("state");
console.log("state", JSON.stringify(state));
await browser.close();

if (warnings.length) console.log(`warnings (${warnings.length}):\n  ${warnings.slice(0, 15).join("\n  ")}`);
if (errors.length) {
  console.error(`errors (${errors.length}):\n  ${errors.join("\n  ")}`);
  process.exit(1);
}
console.log("screenshot run: OK");
