import { LAYER_IDS, useStore, type LayerId, type View } from "./store";

function only(on: LayerId[]): Record<LayerId, boolean> {
  const out = {} as Record<LayerId, boolean>;
  for (const id of LAYER_IDS) out[id] = on.includes(id);
  return out;
}

/** The layers that each view shows when it opens. The rail can change them after that. */
export const VIEW_LAYERS: Record<View, Record<LayerId, boolean>> = {
  plan: only(["storm", "zones", "evac", "shelters", "supply", "roads"]),
  command: only(["storm", "wind", "surge", "zones", "evac", "shelters", "hospitals", "supply", "roads", "sar", "debris"]),
  supply: only(["storm", "zones", "shelters", "hospitals", "supply", "roads", "debris"]),
  rescue: only(["storm", "surge", "hospitals", "roads", "sar", "debris"]),
  model: only(["storm", "wind"]),
};

/** Open a view and apply its layer preset. Clear the plan focus. */
export function setView(view: View): void {
  const s = useStore.getState();
  if (s.view === view) return;
  s.set({ view, layers: VIEW_LAYERS[view], focus: null });
}
