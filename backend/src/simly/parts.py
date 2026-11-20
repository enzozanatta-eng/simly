"""User-uploaded parts: storage, import into Gmsh, and face classification.

Faces are what the user clicks to place supports and loads. A STEP file
already has CAD faces. An STL is only triangles, so its faces are recovered
by splitting the surface along sharp edges (angle above FACE_ANGLE_DEG): flat
sides and cylinders come out as separate faces, which is what people expect
to click on.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import uuid
from pathlib import Path

import numpy as np

from .geometry import _GMSH_LOCK, GMSH_TRI6

FACE_ANGLE_DEG = 40
MAX_UPLOAD_BYTES = 30 * 1024 * 1024
UNIT_SCALE = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}
_ID = re.compile(r"^[0-9a-f]{16}$")


class PartError(ValueError):
    pass


def store_dir() -> Path:
    root = Path(os.environ.get("SIMLY_RUNS", Path(tempfile.gettempdir()) / "simly-runs"))
    d = root / "parts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_upload(data: bytes, filename: str) -> str:
    ext = Path(filename).suffix.lower()
    kind = {".stl": "stl", ".step": "step", ".stp": "step"}.get(ext)
    if kind is None:
        raise PartError("Upload an .stl, .step or .stp file.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise PartError("File too large (limit 30 MB).")
    part_id = uuid.uuid4().hex[:16]
    d = store_dir() / part_id
    d.mkdir()
    (d / f"part.{kind}").write_bytes(data)
    return part_id


def part_file(part_id: str) -> Path:
    if not _ID.match(part_id):
        raise PartError("Invalid part id.")
    d = store_dir() / part_id
    files = list(d.glob("part.*")) if d.is_dir() else []
    if not files:
        raise PartError("Part not found; it may have expired. Upload it again.")
    return files[0]


def import_part(gmsh, path: Path) -> None:
    """Load a part as one closed volume in the current Gmsh model."""
    if path.suffix == ".step":
        gmsh.model.occ.importShapes(str(path))
        gmsh.model.occ.synchronize()
        volumes = gmsh.model.getEntities(3)
        if not volumes:
            raise PartError("The STEP file has no solid body.")
        if len(volumes) > 1:
            gmsh.model.occ.fuse([volumes[0]], volumes[1:])
            gmsh.model.occ.synchronize()
        return

    try:
        gmsh.merge(str(path))
    except Exception as e:
        raise PartError("Could not read the STL file.") from e
    angle = math.radians(FACE_ANGLE_DEG)
    gmsh.model.mesh.classifySurfaces(angle, True, True, math.pi)
    gmsh.model.mesh.createGeometry()
    surfaces = [t for _, t in gmsh.model.getEntities(2)]
    loop = gmsh.model.geo.addSurfaceLoop(surfaces)
    gmsh.model.geo.addVolume([loop])
    gmsh.model.geo.synchronize()


def group_smooth_patches(surface_tris: dict[int, np.ndarray], nodes: np.ndarray,
                         angle_deg: float = FACE_ANGLE_DEG) -> dict[int, list[int]]:
    """Merge neighbouring STL patches that meet without a sharp edge.

    Gmsh splits an STL surface into patches it can parametrise, so one flat side
    may come out as several patches. Two patches are one face for the user when
    the dihedral angle across the edges they share stays below ``angle_deg``
    (median over the shared edges). Returns {face id: [patch ids]}, the face id
    being the smallest patch id.
    """
    edge_owner: dict[tuple[int, int], list[tuple[int, np.ndarray]]] = {}
    for sid, tris in surface_tris.items():
        a, b, c = nodes[tris[:, 0]], nodes[tris[:, 1]], nodes[tris[:, 2]]
        n = np.cross(b - a, c - a)
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-30)
        for tri, normal in zip(tris, n, strict=True):
            for i, j in ((0, 1), (1, 2), (2, 0)):
                key = (min(tri[i], tri[j]), max(tri[i], tri[j]))
                edge_owner.setdefault(key, []).append((sid, normal))

    dots: dict[tuple[int, int], list[float]] = {}
    for owners in edge_owner.values():
        if len(owners) == 2 and owners[0][0] != owners[1][0]:
            (sa, na), (sb, nb) = owners
            # neighbouring triangles of a closed surface are consistently oriented,
            # so |n_a . n_b| measures the bend across the edge
            dots.setdefault((min(sa, sb), max(sa, sb)), []).append(abs(float(na @ nb)))

    parent = {sid: sid for sid in surface_tris}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    cos_limit = math.cos(math.radians(angle_deg))
    for (a, b), values in dots.items():
        if float(np.median(values)) > cos_limit:
            parent[find(b)] = find(a)

    groups: dict[int, list[int]] = {}
    for sid in surface_tris:
        groups.setdefault(find(sid), []).append(sid)
    return {min(members): sorted(members) for members in groups.values()}


def winding_number(points: np.ndarray, tris: np.ndarray, nodes: np.ndarray) -> np.ndarray:
    """Generalised winding number of a closed triangle surface at each point.

    About 1 inside and 0 outside, whatever the orientation of individual
    patches, as long as the triangles of the surface are consistently oriented.
    (Van Oosterom and Strackee solid angle formula.)
    """
    out = np.zeros(len(points))
    for k, q in enumerate(points):
        a, b, c = (nodes[tris[:, i]] - q for i in range(3))
        la, lb, lc = (np.linalg.norm(v, axis=1) for v in (a, b, c))
        det = np.einsum("ij,ij->i", a, np.cross(b, c))
        den = (la * lb * lc + np.einsum("ij,ij->i", a, b) * lc
               + np.einsum("ij,ij->i", b, c) * la + np.einsum("ij,ij->i", c, a) * lb)
        out[k] = np.sum(2 * np.arctan2(det, den)) / (4 * np.pi)
    return out


def face_groups(part_id: str) -> dict[int, list[int]] | None:
    f = part_file(part_id).parent / "faces.json"
    if not f.exists():
        return None
    return {int(k): v for k, v in json.loads(f.read_text()).items()}


def _feature_edges(gmsh, groups, nodes, index, scale):
    """Curves where two different user faces meet (or the boundary of an open face).

    Curves that only separate patches of the same face are not offered for picking.
    """
    group_of = {m: g for g, members in groups.items() for m in members}
    edges, segments, owner, corner_tags = [], [], [], set()
    for _, curve in gmsh.model.getEntities(1):
        up, _down = gmsh.model.getAdjacencies(1, curve)
        faces_here = {group_of.get(int(t), int(t)) for t in up}
        if len(faces_here) < 2 and len(up) != 1:
            continue
        _, node_tags = gmsh.model.mesh.getElementsByType(1, curve)
        if len(node_tags) == 0:
            continue
        seg = np.array([index[int(t)] for t in node_tags]).reshape(-1, 2)
        a, b = nodes[seg[:, 0]], nodes[seg[:, 1]]
        lengths = np.linalg.norm(b - a, axis=1)
        mid = ((a + b) / 2 * lengths[:, None]).sum(axis=0) / lengths.sum()
        chord = nodes[seg[-1, 1]] - nodes[seg[0, 0]]
        straight = abs(np.linalg.norm(chord) - lengths.sum()) < 1e-3 * lengths.sum()
        edges.append({
            "id": int(curve),
            "length_mm": round(float(lengths.sum()), 4),
            "midpoint": np.round(mid, 4).tolist(),
            "direction": np.round(chord / (np.linalg.norm(chord) or 1.0), 5).tolist()
            if straight else None,
            "faces": sorted(faces_here),
        })
        segments.extend(np.round(np.hstack([a, b]), 4).ravel().tolist())
        owner.extend([int(curve)] * len(seg))
        _, down = gmsh.model.getAdjacencies(1, curve)
        corner_tags.update(int(t) for t in down)
    vertices = []
    for tag in sorted(corner_tags):
        x, y, z = gmsh.model.getValue(0, tag, [])
        vertices.append({"id": tag, "point": [round(v * scale, 4) for v in (x, y, z)]})
    return edges, segments, owner, vertices


def bbox(gmsh) -> np.ndarray:
    x0, y0, z0, x1, y1, z1 = gmsh.model.getBoundingBox(-1, -1)
    return np.array([[x0, y0, z0], [x1, y1, z1]])


def describe_part(part_id: str, units: str = "mm") -> dict:
    """Faces of the part with a light surface mesh, for display and picking."""
    import gmsh

    scale = UNIT_SCALE[units]
    path = part_file(part_id)
    with _GMSH_LOCK:
        gmsh.initialize(interruptible=False)
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            import_part(gmsh, path)
            box = bbox(gmsh)
            size = float(np.linalg.norm(box[1] - box[0])) / 40
            gmsh.option.setNumber("Mesh.MeshSizeMax", size)
            gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 12)
            try:
                gmsh.model.mesh.generate(2)
            except Exception as e:
                raise PartError("The surface could not be meshed; is the part a closed "
                                "solid without self-intersections?") from e
            tags, coords, _ = gmsh.model.mesh.getNodes()
            index = {int(t): i for i, t in enumerate(tags)}
            nodes = coords.reshape(-1, 3) * scale

            surface_tris = {}
            for _, surf in gmsh.model.getEntities(2):
                _, node_tags = gmsh.model.mesh.getElementsByType(2, surf)  # 3-node tris
                tris = np.array([index[int(t)] for t in node_tags]).reshape(-1, 3)
                if len(tris):
                    surface_tris[int(surf)] = tris
            if path.suffix == ".stl":
                groups = group_smooth_patches(surface_tris, nodes)
            else:
                groups = {sid: [sid] for sid in surface_tris}

            all_tris = np.vstack(list(surface_tris.values()))
            diag = float(np.linalg.norm(nodes.max(axis=0) - nodes.min(axis=0)))
            faces, positions_idx, face_of_tri = [], [], []
            for fid, members in sorted(groups.items()):
                tris = np.vstack([surface_tris[m] for m in members])
                a, b, c = nodes[tris[:, 0]], nodes[tris[:, 1]], nodes[tris[:, 2]]
                cross = np.cross(b - a, c - a)
                areas = 0.5 * np.linalg.norm(cross, axis=1)
                normal = cross.sum(axis=0)
                normal = normal / (np.linalg.norm(normal) or 1.0)
                centroid = ((a + b + c) / 3 * areas[:, None]).sum(axis=0) / areas.sum()
                # orient outwards: a point just off the biggest triangle along the
                # normal must be outside the solid (winding number near 0)
                big = int(np.argmax(areas))
                probe = (a[big] + b[big] + c[big]) / 3 + 1e-3 * diag * normal
                if winding_number(probe[None], all_tris, nodes)[0] > 0.5:
                    normal = -normal
                faces.append({
                    "id": fid,
                    "area_mm2": round(float(areas.sum()), 4),
                    "centroid": np.round(centroid, 4).tolist(),
                    "normal": np.round(normal, 5).tolist(),
                })
                positions_idx.append(tris)
                face_of_tri += [fid] * len(tris)
            edges, edge_segments, edge_of_segment, vertices = _feature_edges(
                gmsh, groups, nodes, index, scale)
        finally:
            gmsh.finalize()

    shown = np.vstack(positions_idx)
    used, inverse = np.unique(shown, return_inverse=True)
    lo, hi = box * scale
    info = {
        "part_id": part_id,
        "units": units,
        "bbox_mm": {"min": np.round(lo, 4).tolist(), "max": np.round(hi, 4).tolist(),
                    "size": np.round(hi - lo, 4).tolist()},
        "faces": faces,
        "edges": edges,
        "vertices": vertices,
        "display": {
            "positions": np.round(nodes[used], 4).ravel().tolist(),
            "indices": inverse.astype(int).ravel().tolist(),
            "face_of_triangle": face_of_tri,
            "edge_segments": edge_segments,
            "edge_of_segment": edge_of_segment,
        },
    }
    (path.parent / "faces.json").write_text(json.dumps({str(k): v for k, v in groups.items()}))
    return info


__all__ = ["GMSH_TRI6", "PartError", "describe_part", "face_groups", "import_part",
           "part_file", "save_upload"]
