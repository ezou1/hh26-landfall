import { create } from "zustand";
import type { Meta, PlanCommon, PlanScenarioBundle, Stage1Bundle, Statics, VerifySummary } from "../api/types";

/** The identifiers of the globe layers. */
export const LAYER_IDS = [
  "storm",
  "wind",
  "surge",
  "zones",
  "evac",
  "shelters",
  "hospitals",
  "supply",
  "roads",
  "sar",
  "debris",
  "infra",
] as const;
export type LayerId = (typeof LAYER_IDS)[number];

export type View = "plan" | "command" | "supply" | "rescue" | "model";

/** One plan item that the globe highlights. */
export interface Focus {
  id: string;
  label: string;
}
export type KpiMode = "expected" | "worst10";
export type Speed = 0.1 | 1 | 4 | 16;
export type PlanStatus = "idle" | "loading" | "ok" | "missing";

export interface RerunState {
  jobId: string | null;
  status: "idle" | "running" | "done" | "error";
  progress: number;
  message: string;
}

export interface AppState {
  meta: Meta | null;
  t0Ms: number;
  tEndMs: number;
  statics: Statics | null;
  verify: VerifySummary | null;
  loadError: string | null;

  /** The integer hour since T0 that the clock shows. */
  hour: number;
  playing: boolean;
  speed: Speed;
  view: View;
  scenarioId: number;
  kpiMode: KpiMode;
  followStorm: boolean;
  assumptionsOpen: boolean;
  ionToken: boolean;
  /** The plan item that the globe highlights, or null. */
  focus: Focus | null;
  layers: Record<LayerId, boolean>;

  activeAdvisory: string | null;
  activePlanAdvisory: string | null;
  stage1: Stage1Bundle | null;
  planCommon: PlanCommon | null;
  planScenario: PlanScenarioBundle | null;
  planStatus: PlanStatus;

  fallbackItems: string[];
  fallbackUrls: string[];
  rerun: RerunState;

  set: (patch: Partial<AppState>) => void;
  toggleLayer: (id: LayerId) => void;
  addFallback: (url: string, items: string[]) => void;
}

const defaultLayers: Record<LayerId, boolean> = {
  storm: true,
  wind: true,
  surge: true,
  zones: true,
  evac: true,
  shelters: true,
  hospitals: true,
  supply: true,
  roads: true,
  sar: true,
  debris: true,
  infra: false,
};

/** The global UI store. */
export const useStore = create<AppState>((set) => ({
  meta: null,
  t0Ms: 0,
  tEndMs: 0,
  statics: null,
  verify: null,
  loadError: null,
  hour: 0,
  playing: false,
  speed: 1,
  view: "command",
  scenarioId: 0,
  kpiMode: "expected",
  followStorm: false,
  assumptionsOpen: false,
  ionToken: false,
  focus: null,
  layers: defaultLayers,
  activeAdvisory: null,
  activePlanAdvisory: null,
  stage1: null,
  planCommon: null,
  planScenario: null,
  planStatus: "idle",
  fallbackItems: [],
  fallbackUrls: [],
  rerun: { jobId: null, status: "idle", progress: 0, message: "" },
  set: (patch) => set(patch),
  toggleLayer: (id) => set((s) => ({ layers: { ...s.layers, [id]: !s.layers[id] } })),
  addFallback: (url, items) =>
    set((s) => {
      if (s.fallbackUrls.includes(url)) return {};
      const merged = Array.from(new Set([...s.fallbackItems, ...items]));
      return { fallbackUrls: [...s.fallbackUrls, url], fallbackItems: merged };
    }),
}));
