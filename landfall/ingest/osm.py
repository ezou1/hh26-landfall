"""Download the Lee County drive network with OSMnx and build the routing graph.

The routing graph keeps the major road classes, every bridge, and the critical links.
It is the largest strongly connected part of that network.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field

import networkx as nx
import numpy as np

from landfall.config import BBOX, CACHE, CRITICAL_LINKS, EXITS
from landfall.log import clear_fallback, get_logger, record_fallback

GRAPHML = CACHE / "lee_drive.graphml"
ROUTING_PKL = CACHE / "routing_graph.pkl"
PLACE = "Lee County, Florida, USA"
OVERPASS_URLS = [
    "https://overpass-api.de/api",
    "https://overpass.kumi.systems/api",
    "https://overpass.private.coffee/api",
    "https://maps.mail.ru/osm/tools/overpass/api",
]

MAJOR = {
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link",
}
DISPLAY = {"motorway", "trunk", "primary", "secondary", "motorway_link", "trunk_link"}
DEFAULT_SPEED_KPH = {
    "motorway": 105, "motorway_link": 70, "trunk": 90, "trunk_link": 60, "primary": 75,
    "primary_link": 55, "secondary": 65, "secondary_link": 50, "tertiary": 55,
    "tertiary_link": 45, "residential": 40, "unclassified": 45,
}
DEFAULT_LANES = {"motorway": 3, "trunk": 2, "primary": 2, "secondary": 1, "tertiary": 1}

# OSM names that identify the critical links, together with the bbox in config.CRITICAL_LINKS.
CRITICAL_NAME_HINTS = {
    "Sanibel Causeway": ("causeway", "sanibel"),
    "Matlacha Pass Bridge": ("pine island", "matlacha", "78"),
    "Pine Island Road": ("pine island", "stringfellow", "78"),
    "Fort Myers Beach Bridge": ("san carlos", "matanzas", "estero", "865"),
    "Big Carlos Pass Bridge": ("estero", "865", "carlos"),
    "Boca Grande Causeway": ("gasparilla", "boca grande", "771", "causeway"),
}


@dataclass
class RoadGraph:
    """A compact road graph with edge attributes for the logistics models."""

    g: nx.MultiDiGraph
    node_xy: dict[int, tuple[float, float]]
    edges: list[dict[str, object]] = field(default_factory=list)  # one dict for each (u, v, k)
    exit_nodes: dict[str, int] = field(default_factory=dict)
    used_fallback: bool = False

    def edge_index(self) -> dict[tuple[int, int, int], int]:
        """Return a map from (u, v, k) to the position in self.edges."""
        return {(e["u"], e["v"], e["k"]): i for i, e in enumerate(self.edges)}


def _first(v: object) -> object:
    return v[0] if isinstance(v, list) and v else v


def _as_float(v: object, default: float) -> float:
    v = _first(v)
    try:
        return float(str(v).split()[0].replace("mph", ""))
    except (TypeError, ValueError, IndexError):
        return default


def download_graph() -> nx.MultiDiGraph | None:
    """Download the drive network with OSMnx and cache it as GraphML."""
    import osmnx as ox

    if GRAPHML.exists():
        return ox.load_graphml(GRAPHML)
    import time

    last: Exception | None = None
    for attempt, url in enumerate(OVERPASS_URLS * 2):
        try:
            ox.settings.overpass_url = url
            ox.settings.cache_folder = str(CACHE / "osmnx")
            ox.settings.requests_timeout = 300
            get_logger().info("osmnx download", place=PLACE, overpass=url, attempt=attempt + 1)
            g = ox.graph_from_place(PLACE, network_type="drive", simplify=True, retain_all=False)
            ox.save_graphml(g, GRAPHML)
            clear_fallback("road_network")
            return g
        except Exception as exc:  # noqa: BLE001
            last = exc
            get_logger().warning("osmnx retry", overpass=url, error=str(exc)[:200])
            time.sleep(min(60, 5 * 2**attempt))
    record_fallback("road_network", f"OSMnx download failed: {str(last)[:300]}")
    return None


def _in_bbox(x: float, y: float, bb: tuple[float, float, float, float]) -> bool:
    return bb[0] <= x <= bb[2] and bb[1] <= y <= bb[3]


def _critical_name(name: str, ref: str, xs: list[float], ys: list[float], bridge: bool) -> str | None:
    text = f"{name} {ref}".lower()
    mx, my = float(np.mean(xs)), float(np.mean(ys))
    for cname, bb in CRITICAL_LINKS.items():
        if not _in_bbox(mx, my, bb):
            continue
        hints = CRITICAL_NAME_HINTS[cname]
        if any(h in text for h in hints) and (bridge or "causeway" in text or "Road" in cname):
            return cname
    return None


def synthetic_graph() -> nx.MultiDiGraph:
    """Return a labelled synthetic grid road network over the county bbox."""
    w, s, e, n = BBOX
    g = nx.MultiDiGraph()
    xs = np.linspace(w + 0.05, e - 0.02, 18)
    ys = np.linspace(s + 0.02, n - 0.02, 12)
    nid = 0
    ids = {}
    for i, x in enumerate(xs):
        for j, y in enumerate(ys):
            ids[(i, j)] = nid
            g.add_node(nid, x=float(x), y=float(y))
            nid += 1
    for (i, j), u in ids.items():
        for di, dj in ((1, 0), (0, 1)):
            if (i + di, j + dj) in ids:
                v = ids[(i + di, j + dj)]
                hw = "primary" if (i % 4 == 0 or j % 4 == 0) else "tertiary"
                length = 111000 * float(np.hypot((xs[1] - xs[0]) * di * 0.9, (ys[1] - ys[0]) * dj))
                for a, b in ((u, v), (v, u)):
                    g.add_edge(a, b, highway=hw, length=length, name="Synthetic Road", lanes="2")
    g.graph["crs"] = "epsg:4326"
    return g


def build_routing_graph(refresh: bool = False) -> RoadGraph:
    """Return the routing graph. Build it from the cached OSM graph if necessary."""
    if ROUTING_PKL.exists() and not refresh:
        with ROUTING_PKL.open("rb") as fh:
            return pickle.load(fh)
    raw = download_graph()
    used_fallback = raw is None
    if raw is None:
        raw = synthetic_graph()
    keep = nx.MultiDiGraph()
    for u, v, k, d in raw.edges(keys=True, data=True):
        hw = str(_first(d.get("highway", "unclassified")))
        bridge = str(_first(d.get("bridge", "no"))) not in ("no", "None", "nan", "")
        name = str(_first(d.get("name", "")) or "")
        if name == "nan":
            name = ""
        ref = str(_first(d.get("ref", "")) or "")
        if hw in MAJOR or bridge or "causeway" in name.lower():
            keep.add_edge(u, v, k, **d)
    for n in keep.nodes:
        keep.nodes[n].update(raw.nodes[n])
    comp = max(nx.strongly_connected_components(keep), key=len)
    g = keep.subgraph(comp).copy()
    node_xy = {n: (float(g.nodes[n]["x"]), float(g.nodes[n]["y"])) for n in g.nodes}
    edges: list[dict[str, object]] = []
    for u, v, k, d in g.edges(keys=True, data=True):
        hw = str(_first(d.get("highway", "unclassified")))
        if "geometry" in d and d["geometry"] is not None:
            coords = list(d["geometry"].coords)
        else:
            coords = [node_xy[u], node_xy[v]]
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        bridge = str(_first(d.get("bridge", "no"))) not in ("no", "None", "nan", "")
        name = str(_first(d.get("name", "")) or "")
        name = "" if name == "nan" else name
        ref = str(_first(d.get("ref", "")) or "")
        ref = "" if ref == "nan" else ref
        lanes = _as_float(d.get("lanes"), DEFAULT_LANES.get(hw.replace("_link", ""), 1))
        if "_link" in hw:
            lanes = 1.0
        oneway = bool(_first(d.get("oneway", False)))
        if not oneway:
            lanes = max(1.0, lanes / 2.0)  # OSM lanes counts both directions on two-way roads
        speed = _as_float(d.get("maxspeed"), DEFAULT_SPEED_KPH.get(hw, 45) / 1.609) * 1.609
        if d.get("maxspeed") is None:
            speed = DEFAULT_SPEED_KPH.get(hw, 45)
        length = float(d.get("length", 100.0))
        crit = _critical_name(name, ref, xs, ys, bridge)
        edges.append(
            {
                "u": int(u), "v": int(v), "k": int(k),
                "edge_id": f"{u}-{v}-{k}",
                "name": name or ref or hw,
                "ref": ref,
                "highway": hw,
                "lanes": float(lanes),
                "speed_kph": float(speed),
                "length_m": length,
                "tt_h": length / 1000.0 / max(speed, 5.0),
                "bridge": bridge,
                "is_critical": crit is not None,
                "critical_name": crit,
                "coords": [(round(x, 5), round(y, 5)) for x, y in coords],
                "mid": (float(np.mean(xs)), float(np.mean(ys))),
                "display": hw in DISPLAY or crit is not None or bridge,
            }
        )
    rg = RoadGraph(g=g, node_xy=node_xy, edges=edges, used_fallback=used_fallback)
    nodes = np.array(list(node_xy.keys()))
    pts = np.array([node_xy[n] for n in nodes])
    for name, (x, y) in EXITS.items():
        d2 = (pts[:, 0] - x) ** 2 + (pts[:, 1] - y) ** 2
        rg.exit_nodes[name] = int(nodes[int(np.argmin(d2))])
    with ROUTING_PKL.open("wb") as fh:
        pickle.dump(rg, fh)
    get_logger().info(
        "routing graph", nodes=g.number_of_nodes(), edges=g.number_of_edges(),
        critical=sum(1 for e in edges if e["is_critical"]), fallback=used_fallback,
    )
    return rg


def nearest_node(rg: RoadGraph, lon: float, lat: float) -> int:
    """Return the routing-graph node nearest to a point."""
    nodes = getattr(rg, "_nodes_arr", None)
    if nodes is None:
        nodes = np.array(list(rg.node_xy.keys()))
        pts = np.array([rg.node_xy[n] for n in nodes])
        rg._nodes_arr = nodes  # type: ignore[attr-defined]
        rg._pts_arr = pts  # type: ignore[attr-defined]
    pts = rg._pts_arr  # type: ignore[attr-defined]
    d2 = ((pts[:, 0] - lon) * np.cos(np.radians(lat))) ** 2 + (pts[:, 1] - lat) ** 2
    return int(nodes[int(np.argmin(d2))])
