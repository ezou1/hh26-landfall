import {
  Color,
  Credit,
  createGooglePhotorealistic3DTileset,
  EllipsoidTerrainProvider,
  ImageryLayer,
  Ion,
  UrlTemplateImageryProvider,
  type Viewer as CesiumViewer,
} from "cesium";
import { useEffect, useRef } from "react";
import { Viewer, type CesiumComponentRef } from "resium";
import { attachViewer } from "./controller";

const token = (import.meta.env.VITE_CESIUM_ION_TOKEN ?? "").trim();

/** Return true if the build has a Cesium ion token. */
export const HAS_ION_TOKEN = token.length > 0;

if (HAS_ION_TOKEN) Ion.defaultAccessToken = token;

function esriLayer(): ImageryLayer {
  return new ImageryLayer(
    new UrlTemplateImageryProvider({
      url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      maximumLevel: 19,
      credit: new Credit("Esri, Maxar, Earthstar Geographics, and the GIS User Community"),
    }),
  );
}

// Resium reads these options one time. Keep them constant.
const viewerOptions = HAS_ION_TOKEN
  ? {}
  : { baseLayer: esriLayer(), terrainProvider: new EllipsoidTerrainProvider() };

async function addGoogleTiles(v: CesiumViewer): Promise<void> {
  try {
    const tiles = await createGooglePhotorealistic3DTileset();
    if (v.isDestroyed()) return;
    v.scene.primitives.add(tiles);
    v.scene.globe.show = false;
  } catch (err) {
    console.warn("Google Photorealistic 3D Tiles did not load. The globe imagery stays on.", err);
  }
}

/** The Cesium globe. It hides the default widgets and attaches the LANDFALL layers. */
export function GlobeView() {
  const ref = useRef<CesiumComponentRef<CesiumViewer>>(null);

  useEffect(() => {
    // Resium can create the viewer after this effect runs. Wait for it.
    let raf = 0;
    const tryAttach = () => {
      const v = ref.current?.cesiumElement;
      if (v) setup(v);
      else raf = requestAnimationFrame(tryAttach);
    };
    tryAttach();
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <Viewer
      ref={ref}
      full={false}
      className="globe"
      animation={false}
      timeline={false}
      baseLayerPicker={false}
      geocoder={false}
      homeButton={false}
      sceneModePicker={false}
      navigationHelpButton={false}
      fullscreenButton={false}
      infoBox={false}
      selectionIndicator={false}
      automaticallyTrackDataSourceClocks={false}
      shouldAnimate={false}
      {...viewerOptions}
    />
  );
}

function setup(v: CesiumViewer): void {
  {
    const scene = v.scene;
    scene.globe.enableLighting = false;
    scene.globe.depthTestAgainstTerrain = false;
    scene.globe.baseColor = Color.fromCssColorString("#0b1a2a");
    if (scene.skyAtmosphere) scene.skyAtmosphere.show = true;
    scene.fog.enabled = true;
    v.resolutionScale = Math.min(window.devicePixelRatio || 1, 1.5);
    const credits = v.cesiumWidget.creditContainer as HTMLElement;
    credits.style.fontSize = "9px";
    credits.style.opacity = "0.6";
    if (HAS_ION_TOKEN) void addGoogleTiles(v);
    attachViewer(v);
    const w = window as unknown as { __landfallViewer?: CesiumViewer };
    w.__landfallViewer = v;
  }
}
