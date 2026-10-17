"""Define the 6-hour step predictor and the residual bank.

The predictor is an MLP with 3 hidden layers of 256 units, GELU, and dropout 0.1.
It predicts the change of latitude, longitude, and wind speed over the next 6 h.
The residual bank holds rollout residuals for each lead-time bucket.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import torch
from torch import nn

from landfall.config import CACHE, LEAD_BUCKETS_H, MLP_DROPOUT, MLP_HIDDEN, MLP_LAYERS

MODEL_FILE = CACHE / "model.pt"
LAT_BANDS = (20.0, 26.0, 32.0, 40.0)  # band edges in degrees north
MIN_POOL = 300


def lat_band(lat: np.ndarray) -> np.ndarray:
    """Return the latitude band index of each value (0 = south of 20 N)."""
    return np.searchsorted(np.asarray(LAT_BANDS), np.nan_to_num(np.asarray(lat, dtype=float), nan=25.0))


class StepMLP(nn.Module):
    """The MLP that maps a standardised StormState vector to a standardised 6-h change."""

    def __init__(self, n_in: int, n_out: int = 3, hidden: int = MLP_HIDDEN, layers: int = MLP_LAYERS,
                 dropout: float = MLP_DROPOUT) -> None:
        super().__init__()
        mods: list[nn.Module] = []
        d = n_in
        for _ in range(layers):
            mods += [nn.Linear(d, hidden), nn.GELU(), nn.Dropout(dropout)]
            d = hidden
        mods.append(nn.Linear(d, n_out))
        self.net = nn.Sequential(*mods)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Return the standardised prediction."""
        return self.net(x)


class BaggedMLP(nn.Module):
    """The mean of several StepMLP members that train with different seeds."""

    def __init__(self, n_in: int, n_members: int) -> None:
        super().__init__()
        self.members = nn.ModuleList([StepMLP(n_in) for _ in range(n_members)])

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Return the mean prediction of the members."""
        return torch.stack([m(x) for m in self.members]).mean(0)


def bucket_of_step(step: int) -> int:
    """Return the lead-time bucket index for a rollout step (step 0 ends at 6 h)."""
    lead = 6 * (step + 1)
    for i, edge in enumerate(LEAD_BUCKETS_H):
        if lead <= edge:
            return i
    return len(LEAD_BUCKETS_H) - 1


@dataclass
class Predictor:
    """The trained step model with its scalers and the residual bank."""

    net: nn.Module
    x_mean: np.ndarray
    x_std: np.ndarray
    y_mean: np.ndarray
    y_std: np.ndarray
    # residuals[case, step, 3] with NaN where the truth track ended
    residuals: np.ndarray = field(default_factory=lambda: np.zeros((0, 20, 3), np.float32))
    bucket_std: np.ndarray = field(default_factory=lambda: np.ones((len(LEAD_BUCKETS_H), 3), np.float32))
    info: dict[str, object] = field(default_factory=dict)
    # spread scale for each bucket, calibrated on the validation storms (not on Ian)
    bucket_scale: np.ndarray = field(default_factory=lambda: np.ones(len(LEAD_BUCKETS_H), np.float32))
    # latitude of the rolled state for each residual [case, step]
    residual_lat: np.ndarray = field(default_factory=lambda: np.zeros((0, 20), np.float32))
    _pools: dict[tuple[int, int], np.ndarray] | None = None

    def pool(self, bucket: int, band: int = -1) -> np.ndarray:
        """Return the residual vectors of one lead-time bucket and one latitude band.

        Band -1 means all latitudes. A band with fewer than MIN_POOL rows uses all latitudes.
        """
        if self._pools is None:
            pools: dict[tuple[int, int], np.ndarray] = {}
            for b in range(len(LEAD_BUCKETS_H)):
                steps = [k for k in range(self.residuals.shape[1]) if bucket_of_step(k) == b]
                r = self.residuals[:, steps].reshape(-1, 3) if steps else np.zeros((0, 3))
                if self.residual_lat.shape[0] == self.residuals.shape[0] and steps:
                    la = self.residual_lat[:, steps].reshape(-1)
                else:
                    la = np.full(len(r), 25.0)
                ok = ~np.isnan(r).any(axis=1) & ~np.isnan(la)
                r, la = r[ok].astype(np.float64), la[ok]
                pools[(b, -1)] = r
                bands = lat_band(la)
                for k in range(len(LAT_BANDS) + 1):
                    sel = r[bands == k]
                    pools[(b, k)] = sel if len(sel) >= MIN_POOL else r
            self._pools = pools
        return self._pools[(bucket, band)]

    def sample_residuals(self, step: int, n: int, rng: np.random.Generator,
                         lat: np.ndarray | None = None) -> np.ndarray:
        """Draw n residual vectors for a rollout step from the bank, with a Gaussian jitter.

        If lat is given, each row draws from the pool of its latitude band.
        """
        from landfall.config import RESIDUAL_JITTER

        b = bucket_of_step(step)
        out = np.zeros((n, 3))
        bands = lat_band(lat) if lat is not None else np.full(n, -1)
        for k in np.unique(bands):
            rows = np.where(bands == k)[0]
            pool = self.pool(b, int(k))
            if len(pool) == 0:
                continue
            out[rows] = pool[rng.integers(0, len(pool), size=len(rows))]
        out = out + rng.normal(0.0, 1.0, size=(n, 3)) * self.bucket_std[b] * RESIDUAL_JITTER
        return out * float(self.bucket_scale[b])

    def predict(self, x: np.ndarray) -> np.ndarray:
        """Return the 6-h change (dlat, dlon, dv) for a batch of input rows."""
        self.net.eval()
        with torch.no_grad():
            xs = (x - self.x_mean) / self.x_std
            y = self.net(torch.from_numpy(np.nan_to_num(xs).astype(np.float32))).numpy()
        return y * self.y_std + self.y_mean

    def save(self, path: Path = MODEL_FILE) -> None:
        """Save the predictor to a file."""
        torch.save(
            {
                "state_dict": self.net.state_dict(),
                "n_in": int(self.x_mean.shape[0]),
                "n_bag": len(self.net.members) if isinstance(self.net, BaggedMLP) else 0,
                "x_mean": self.x_mean, "x_std": self.x_std,
                "y_mean": self.y_mean, "y_std": self.y_std,
                "residuals": self.residuals, "bucket_std": self.bucket_std,
                "bucket_scale": self.bucket_scale, "residual_lat": self.residual_lat, "info": self.info,
            },
            path,
        )

    @classmethod
    def load(cls, path: Path = MODEL_FILE) -> Predictor:
        """Load a predictor from a file."""
        d = torch.load(path, weights_only=False)
        net = BaggedMLP(d["n_in"], d["n_bag"]) if d.get("n_bag") else StepMLP(d["n_in"])
        net.load_state_dict(d["state_dict"])
        net.eval()
        p = cls(net, d["x_mean"], d["x_std"], d["y_mean"], d["y_std"], d["residuals"],
                d["bucket_std"], d.get("info", {}))
        if "bucket_scale" in d:
            p.bucket_scale = d["bucket_scale"]
        if "residual_lat" in d:
            p.residual_lat = d["residual_lat"]
        return p
