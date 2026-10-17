import "cesium/Build/Cesium/Widgets/widgets.css";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { installDebug } from "./debug";
import "./styles.css";

installDebug();

const el = document.getElementById("root");
if (el) {
  // StrictMode is off: it mounts the Cesium viewer two times in development.
  createRoot(el).render(<App />);
}
