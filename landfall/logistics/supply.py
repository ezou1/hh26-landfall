"""Solve the supply plan with HiGHS: the two-stage stochastic LP and the recourse LP.

First stage: the units of each commodity to stage at each depot.
Recourse, for each scenario: the shipments from depots to sites in each 12-h window,
limited by the staged stock and by the truck hours of each depot. A site can store
supplies, so a delivery before the storm can cover the demand of a later window. The objective is the
staging cost, plus the expected W2 x unmet kg and W5 x transported tonne-km.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix

from landfall.config import SUPPLY_WINDOW_H, TRUCK_CAPACITY_KG, W2_UNMET_SUPPLY, W5_TRANSPORT

STAGE_COST_PER_KG = {"state": 0.05, "county": 0.02, "retail": 0.02}
LOAD_UNLOAD_H = 1.0


@dataclass
class SupplyScenario:
    """The data of one scenario for the supply LP."""

    probability: float
    demand: np.ndarray  # (J, C, W)
    reach: np.ndarray  # (D, J, W) bool
    travel_h: np.ndarray  # (D, J, W)
    dist_km: np.ndarray  # (D, J)


@dataclass
class SupplySolution:
    """The LP solution."""

    stage: np.ndarray  # (D, C)
    ship: list[np.ndarray]  # per scenario (D, J, C, W)
    unmet: list[np.ndarray]  # per scenario (J, C, W)
    objective: float
    status: str


def solve(scen: list[SupplyScenario], inventory: np.ndarray, trucks: np.ndarray, kg: np.ndarray,
          depot_kind: list[str], fixed_stage: np.ndarray | None = None) -> SupplySolution:
    """Solve the two-stage LP. If fixed_stage is given, solve the recourse only."""
    d_n, c_n = inventory.shape
    j_n, _, w_n = scen[0].demand.shape
    stage_cost = np.array([STAGE_COST_PER_KG.get(k, 0.02) for k in depot_kind])[:, None] * kg[None, :]
    n_stage = d_n * c_n
    cols_cost = [stage_cost.ravel()]
    lb = [np.zeros(n_stage)]
    ub = [inventory.ravel().astype(float)]
    if fixed_stage is not None:
        lb[0] = fixed_stage.ravel().astype(float)
        ub[0] = fixed_stage.ravel().astype(float)
        cols_cost[0] = np.zeros(n_stage)
    offset = n_stage
    ship_idx: list[tuple[np.ndarray, int]] = []
    unmet_off: list[int] = []
    ub_rows, ub_cols, ub_vals, ub_rhs = [], [], [], []
    r_ub = 0
    for sc in scen:
        future = np.cumsum(sc.demand[:, :, ::-1], axis=2)[:, :, ::-1] > 0  # demand now or later
        dd, jj, cc, ww = np.nonzero(np.broadcast_to(sc.reach[:, :, None, :], (d_n, j_n, c_n, w_n))
                                    & future[None])
        n_ship = len(dd)
        ship_idx.append((np.stack([dd, jj, cc, ww], axis=1), offset))
        tkm = kg[cc] * sc.dist_km[dd, jj] / 1000.0
        cols_cost.append(sc.probability * W5_TRANSPORT * tkm)
        lb.append(np.zeros(n_ship))
        ub.append(np.full(n_ship, np.inf))
        ship_cols = offset + np.arange(n_ship)
        offset += n_ship
        unmet_off.append(offset)
        cols_cost.append(
            sc.probability * W2_UNMET_SUPPLY * np.broadcast_to(kg[None, :, None], (j_n, c_n, w_n)).ravel()
        )
        lb.append(np.zeros(j_n * c_n * w_n))
        ub.append(np.full(j_n * c_n * w_n, np.inf))
        unmet_cols = offset + np.arange(j_n * c_n * w_n)
        offset += j_n * c_n * w_n
        # (1) stock: sum over j, w of ship[d, j, c, w] - stage[d, c] <= 0
        stock_row = r_ub + dd * c_n + cc
        ub_rows += [stock_row, r_ub + np.arange(n_stage)]
        ub_cols += [ship_cols, np.arange(n_stage)]
        ub_vals += [np.ones(n_ship), -np.ones(n_stage)]
        ub_rhs.append(np.zeros(n_stage))
        r_ub += n_stage
        # (3) truck hours: sum kg * (2 t + 1) / window * ship <= trucks * capacity
        th = kg[cc] * (2 * sc.travel_h[dd, jj, ww] + LOAD_UNLOAD_H) / SUPPLY_WINDOW_H
        truck_row = r_ub + dd * w_n + ww
        ub_rows.append(truck_row)
        ub_cols.append(ship_cols)
        ub_vals.append(th)
        ub_rhs.append(np.repeat(trucks.astype(float) * TRUCK_CAPACITY_KG, w_n))
        r_ub += d_n * w_n
        # (2) cumulative balance (sites store supplies): for each window w, the sum of
        # ship + unmet up to w must be at least the sum of the demand up to w.
        reps = w_n - ww
        if n_ship:
            rows_s = np.repeat((jj * c_n + cc) * w_n, reps) + np.concatenate([np.arange(a, w_n) for a in ww])
        else:
            rows_s = np.zeros(0, int)
        cols_s = np.repeat(ship_cols, reps)
        jcw = np.arange(j_n * c_n * w_n)
        w_of = jcw % w_n
        rows_u = np.repeat(jcw - w_of, w_n - w_of) + np.concatenate([np.arange(a, w_n) for a in w_of])
        cols_u = np.repeat(unmet_cols, w_n - w_of)
        ub_rows += [r_ub + rows_s, r_ub + rows_u]
        ub_cols += [cols_s, cols_u]
        ub_vals += [-np.ones(len(cols_s)), -np.ones(len(cols_u))]
        ub_rhs.append(-np.cumsum(sc.demand, axis=2).ravel())
        r_ub += j_n * c_n * w_n
    n_var = offset
    a_ub = coo_matrix((np.concatenate(ub_vals), (np.concatenate(ub_rows), np.concatenate(ub_cols))),
                      shape=(r_ub, n_var)).tocsr()
    res = linprog(
        c=np.concatenate(cols_cost), A_ub=a_ub, b_ub=np.concatenate(ub_rhs),
        bounds=np.stack([np.concatenate(lb), np.concatenate(ub)], axis=1), method="highs",
    )
    if res.x is None:
        raise RuntimeError(f"supply LP failed: {res.message}")
    x = res.x
    stage = x[:n_stage].reshape(d_n, c_n)
    ships, unmets = [], []
    for s in range(len(scen)):
        idx, off = ship_idx[s]
        sh = np.zeros((d_n, j_n, c_n, w_n))
        sh[idx[:, 0], idx[:, 1], idx[:, 2], idx[:, 3]] = x[off : off + len(idx)]
        ships.append(sh)
        u0 = unmet_off[s]
        unmets.append(x[u0 : u0 + j_n * c_n * w_n].reshape(j_n, c_n, w_n))
    return SupplySolution(stage, ships, unmets, float(res.fun), str(res.message))
