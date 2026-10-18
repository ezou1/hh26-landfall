import {
  entityLonLat,
  flyToEntity,
  flyToPoint,
  getHourF,
  getTickCount,
  getViewer,
  home,
  pause,
  play,
  setHour,
  setSpeed,
  stormNow,
} from "./globe/controller";
import { selectScenario } from "./state/data";
import { setView } from "./state/presets";
import { useStore, type LayerId, type Speed, type View } from "./state/store";

/** The debug hooks on window.__landfall for tests and screenshots. */
export interface LandfallDebug {
  setHour: (h: number) => void;
  getHour: () => number;
  play: () => void;
  pause: () => void;
  setSpeed: (s: Speed) => void;
  setView: (v: View) => void;
  selectScenario: (id: number) => void;
  setLayer: (id: LayerId, on: boolean) => void;
  home: () => void;
  flyTo: (lon: number, lat: number, range?: number) => void;
  flyToEntity: (id: string) => boolean;
  entityLonLat: (id: string) => [number, number] | null;
  storm: () => { lon: number; lat: number; vmax: number } | null;
  camera: () => { lon: number; lat: number; height: number } | null;
  ready: () => boolean;
  ticks: () => number;
  tilesLoaded: () => boolean;
  state: () => Record<string, unknown>;
}

/** Add the debug hooks to the window object. */
export function installDebug(): void {
  const api: LandfallDebug = {
    setHour,
    getHour: getHourF,
    play,
    pause,
    setSpeed,
    setView,
    selectScenario,
    setLayer: (id, on) => {
      const s = useStore.getState();
      if (s.layers[id] !== on) s.toggleLayer(id);
    },
    home: () => home(0),
    flyTo: flyToPoint,
    flyToEntity,
    entityLonLat,
    storm: () => {
      const s = stormNow();
      return s ? { lon: s.lon, lat: s.lat, vmax: s.vmax } : null;
    },
    camera: () => {
      const v = getViewer();
      if (!v) return null;
      const c = v.camera.positionCartographic;
      return { lon: (c.longitude * 180) / Math.PI, lat: (c.latitude * 180) / Math.PI, height: c.height };
    },
    ready: () => {
      const s = useStore.getState();
      return !!getViewer() && !!s.meta && !!s.stage1 && s.planStatus !== "loading" && s.planStatus !== "idle";
    },
    ticks: getTickCount,
    tilesLoaded: () => !!getViewer()?.scene.globe.tilesLoaded,
    state: () => {
      const s = useStore.getState();
      return {
        hour: s.hour,
        view: s.view,
        scenarioId: s.scenarioId,
        activeAdvisory: s.activeAdvisory,
        activePlanAdvisory: s.activePlanAdvisory,
        planStatus: s.planStatus,
        fallbackItems: s.fallbackItems,
        playing: s.playing,
        layers: s.layers,
      };
    },
  };
  (window as unknown as { __landfall: LandfallDebug }).__landfall = api;
}
