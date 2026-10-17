import type { CzmlDataSource, JulianDate, Viewer } from "cesium";
import type { AppState, LayerId } from "../../state/store";

/** The data that a layer reads for one frame. */
export interface ScenarioFrame {
  /** The clock time in milliseconds since 1970. */
  tMs: number;
  /** The hours since T0, with a fraction. */
  hourF: number;
  /** The integer hour since T0. */
  hour: number;
  /** A snapshot of the UI store. */
  state: AppState;
  /** The CZML data source of the selected scenario, or null. */
  czml: CzmlDataSource | null;
}

/** The interface that each globe layer obeys. */
export interface GlobeLayer {
  readonly id: LayerId;
  /** Make the Cesium objects of the layer. */
  init(viewer: Viewer): void;
  /** Update the layer for the clock time and the scenario data. */
  update(t: JulianDate, scenario: ScenarioFrame): void;
  /** Show or hide the layer. */
  setVisible(visible: boolean): void;
}
