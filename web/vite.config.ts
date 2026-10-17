import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { viteStaticCopy } from "vite-plugin-static-copy";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const cesiumSource = "node_modules/cesium/Build/Cesium";
const cesiumBaseUrl = "cesiumStatic";
const mockRoot = path.join(here, ".mock", "out");
const useMock = process.env.LANDFALL_MOCK === "1";
const backend = process.env.LANDFALL_BACKEND ?? "http://localhost:8000";

const contentTypes: Record<string, string> = {
  ".json": "application/json",
  ".geojson": "application/geo+json",
  ".czml": "application/json",
};

/** Serve the mock output folder for /out and /api when LANDFALL_MOCK=1. */
function mockBackend(): Plugin {
  const jobs = new Map<string, number>();
  return {
    name: "landfall-mock-backend",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = new URL(req.url ?? "/", "http://localhost");
        const send = (status: number, body: string, type = "application/json") => {
          res.statusCode = status;
          res.setHeader("Content-Type", type);
          res.setHeader("Cache-Control", "no-store");
          res.end(body);
        };
        if (url.pathname === "/api/meta") {
          send(200, fs.readFileSync(path.join(mockRoot, "meta.json"), "utf-8"));
          return;
        }
        if (url.pathname === "/api/health") {
          send(200, JSON.stringify({ ok: true }));
          return;
        }
        if (url.pathname === "/api/rerun" && req.method === "POST") {
          const id = `mock-${Date.now()}`;
          jobs.set(id, Date.now());
          send(200, JSON.stringify({ job_id: id, status: "started" }));
          return;
        }
        if (url.pathname.startsWith("/api/rerun/")) {
          const id = url.pathname.slice("/api/rerun/".length);
          const start = jobs.get(id);
          if (start === undefined) {
            send(404, JSON.stringify({ detail: "unknown job" }));
            return;
          }
          const progress = Math.min(1, (Date.now() - start) / 3000);
          send(
            200,
            JSON.stringify({
              job_id: id,
              status: progress >= 1 ? "done" : "running",
              progress,
              message: "mock",
            }),
          );
          return;
        }
        if (url.pathname.startsWith("/out/")) {
          const rel = decodeURIComponent(url.pathname.slice("/out/".length));
          const file = path.normalize(path.join(mockRoot, rel));
          if (!file.startsWith(mockRoot) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
            send(404, JSON.stringify({ detail: "not found" }));
            return;
          }
          send(200, fs.readFileSync(file, "utf-8"), contentTypes[path.extname(file)] ?? "text/plain");
          return;
        }
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [
    react(),
    viteStaticCopy({
      targets: [
        { src: `${cesiumSource}/ThirdParty`, dest: cesiumBaseUrl },
        { src: `${cesiumSource}/Workers`, dest: cesiumBaseUrl },
        { src: `${cesiumSource}/Assets`, dest: cesiumBaseUrl },
        { src: `${cesiumSource}/Widgets`, dest: cesiumBaseUrl },
      ],
    }),
    ...(useMock ? [mockBackend()] : []),
  ],
  server: {
    port: 5173,
    host: true,
    proxy: useMock
      ? undefined
      : {
          "/api": { target: backend, changeOrigin: true },
          "/out": { target: backend, changeOrigin: true },
        },
  },
  build: {
    chunkSizeWarningLimit: 6000,
  },
});
