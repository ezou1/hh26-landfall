const cache = new Map<string, HTMLCanvasElement>();

function canvas(key: string, size: number, draw: (g: CanvasRenderingContext2D, s: number) => void): HTMLCanvasElement {
  const hit = cache.get(key);
  if (hit) return hit;
  const c = document.createElement("canvas");
  c.width = size;
  c.height = size;
  const g = c.getContext("2d");
  if (g) draw(g, size);
  cache.set(key, c);
  return c;
}

/** Return a red-cross icon for hospitals. */
export function redCrossIcon(): HTMLCanvasElement {
  return canvas("redcross", 48, (g, s) => {
    g.fillStyle = "rgba(255,255,255,0.95)";
    g.beginPath();
    g.arc(s / 2, s / 2, s / 2 - 2, 0, Math.PI * 2);
    g.fill();
    g.strokeStyle = "#7a0d12";
    g.lineWidth = 2;
    g.stroke();
    g.fillStyle = "#e0242f";
    const w = s * 0.2;
    const l = s * 0.62;
    g.fillRect((s - w) / 2, (s - l) / 2, w, l);
    g.fillRect((s - l) / 2, (s - w) / 2, l, w);
  });
}

/** Return a square depot icon with a letter. */
export function depotIcon(kind: string): HTMLCanvasElement {
  const color = kind === "state" ? "#4fc3f7" : kind === "county" ? "#81c784" : "#ffb74d";
  return canvas(`depot-${kind}`, 40, (g, s) => {
    g.fillStyle = "rgba(8,14,20,0.9)";
    g.strokeStyle = color;
    g.lineWidth = 3;
    g.beginPath();
    g.rect(4, 4, s - 8, s - 8);
    g.fill();
    g.stroke();
    g.fillStyle = color;
    g.font = "bold 20px monospace";
    g.textAlign = "center";
    g.textBaseline = "middle";
    g.fillText("D", s / 2, s / 2 + 1);
  });
}

/** Return a spiral texture for the storm disc. */
export function stormSpiral(): HTMLCanvasElement {
  return canvas("spiral", 512, (g, s) => {
    const c = s / 2;
    const grad = g.createRadialGradient(c, c, 0, c, c, c);
    grad.addColorStop(0, "rgba(255,255,255,0.0)");
    grad.addColorStop(0.08, "rgba(255,255,255,0.0)");
    grad.addColorStop(0.12, "rgba(255,255,255,0.55)");
    grad.addColorStop(0.5, "rgba(220,235,255,0.22)");
    grad.addColorStop(1, "rgba(220,235,255,0.0)");
    g.fillStyle = grad;
    g.beginPath();
    g.arc(c, c, c, 0, Math.PI * 2);
    g.fill();
    g.strokeStyle = "rgba(255,255,255,0.6)";
    g.lineCap = "round";
    for (let arm = 0; arm < 4; arm++) {
      g.beginPath();
      for (let i = 0; i <= 120; i++) {
        const f = i / 120;
        const r = c * (0.1 + 0.88 * f);
        const a = arm * (Math.PI / 2) + f * Math.PI * 1.6;
        const x = c + r * Math.cos(a);
        const y = c + r * Math.sin(a);
        if (i === 0) g.moveTo(x, y);
        else g.lineTo(x, y);
      }
      g.lineWidth = 10;
      g.globalAlpha = 0.7;
      g.stroke();
    }
    g.globalAlpha = 1;
  });
}

/** Return a small diamond icon for a rescue asset kind. */
export function assetIcon(kind: string): HTMLCanvasElement {
  const color = kind === "helo" ? "#ffd54f" : kind === "boat" ? "#4dd0e1" : "#ce93d8";
  return canvas(`asset-${kind}`, 32, (g, s) => {
    g.fillStyle = color;
    g.strokeStyle = "#000";
    g.lineWidth = 2;
    g.beginPath();
    g.moveTo(s / 2, 2);
    g.lineTo(s - 2, s / 2);
    g.lineTo(s / 2, s - 2);
    g.lineTo(2, s / 2);
    g.closePath();
    g.fill();
    g.stroke();
    g.fillStyle = "#000";
    g.font = "bold 13px monospace";
    g.textAlign = "center";
    g.textBaseline = "middle";
    g.fillText(kind === "helo" ? "H" : kind === "boat" ? "B" : "T", s / 2, s / 2 + 1);
  });
}
