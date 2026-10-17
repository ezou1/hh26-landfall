"""Compute the supply demand of each shelter and hospital in each 12-h window.

The demand formulas are:

- water (L) = people x 4.
- food (meals) = people x 3.
- medical kits = injuries x 1.2 + people x 0.01.
- generators = 1 for each 200 sheltered persons + 2 for each hospital without grid power.
- fuel (L) = generators x 24 x 10.

A site loses grid power if its gust is more than 100 mph (45 m/s).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from landfall.config import (
    FUEL_L_PER_GEN_HOUR,
    GEN_PER_HOSPITAL_OUTAGE,
    GEN_PER_SHELTERED,
    HOURS,
    KITS_PER_INJURY,
    KITS_PER_PERSON,
    MEALS_PER_PERSON_DAY,
    SUPPLY_WINDOW_H,
    WATER_L_PER_PERSON_DAY,
)

COMMODITY_IDS = ["water", "food", "med_kits", "fuel", "generators"]
N_WINDOWS = HOURS // SUPPLY_WINDOW_H


@dataclass
class SiteDemand:
    """The demand [site, commodity, window] and the site list."""

    site_ids: list[str]
    site_kind: list[str]
    demand: np.ndarray  # (J, C, W)


def window_mean(series: np.ndarray) -> np.ndarray:
    """Return the mean of an hourly series [.., H] over each 12-h window."""
    w = SUPPLY_WINDOW_H
    return np.stack([series[..., i * w : (i + 1) * w].mean(axis=-1) for i in range(N_WINDOWS)], axis=-1)


def site_demand(shelter_ids: list[str], shelter_occ: np.ndarray, hospital_ids: list[str],
                hospital_people: np.ndarray, hospital_injuries: np.ndarray,
                hospital_grid_out_h: list[int | None]) -> SiteDemand:
    """Return the demand of every open shelter and every hospital."""
    j = len(shelter_ids) + len(hospital_ids)
    d = np.zeros((j, len(COMMODITY_IDS), N_WINDOWS))
    people = np.concatenate([window_mean(shelter_occ), window_mean(hospital_people)], axis=0)
    inj = np.concatenate([np.zeros((len(shelter_ids), N_WINDOWS)), window_mean(hospital_injuries)], axis=0)
    d[:, 0] = people * WATER_L_PER_PERSON_DAY
    d[:, 1] = people * MEALS_PER_PERSON_DAY
    d[:, 2] = inj * KITS_PER_INJURY + people * KITS_PER_PERSON
    gens = np.zeros((j, N_WINDOWS))
    gens[: len(shelter_ids)] = np.ceil(people[: len(shelter_ids)] * GEN_PER_SHELTERED)
    for k, out_h in enumerate(hospital_grid_out_h):
        if out_h is not None:
            w0 = int(out_h // SUPPLY_WINDOW_H)
            gens[len(shelter_ids) + k, w0:] = GEN_PER_HOSPITAL_OUTAGE
    d[:, 4] = np.maximum(0.0, np.diff(np.concatenate([np.zeros((j, 1)), np.maximum.accumulate(gens, axis=1)], axis=1), axis=1))
    d[:, 3] = gens * 24 * FUEL_L_PER_GEN_HOUR
    kinds = ["shelter"] * len(shelter_ids) + ["hospital"] * len(hospital_ids)
    return SiteDemand(list(shelter_ids) + list(hospital_ids), kinds, d)
