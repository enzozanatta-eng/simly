"""Template geometry and quadratic tetrahedral meshing with Gmsh (OpenCASCADE kernel).

Each template names the faces the boundary conditions act on ("fixed",
"load"), so a beginner never has to pick faces by hand.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

import numpy as np

from .spec import CantileverBeam, PlateWithHole

LEVEL_FACTOR = {"coarse": 1.5, "medium": 1.0, "fine": 1 / 1.5}
GMSH_TET10, GMSH_TRI6, GMSH_LINE3 = 11, 9, 8
EDGE = "edge:"  # prefix of named curve groups (faces are named without a prefix)
# Gmsh 10-node tet -> CalculiX C3D10 node order (last two mid-edge nodes swap)
TET10_TO_CCX = [0, 1, 2, 3, 4, 5, 6, 7, 9, 8]

# Gmsh keeps global state and is not thread-safe: one mesh at a time.
_GMSH_LOCK = threading.Lock()


@dataclass
class Mesh:
    nodes: np.ndarray  # (N, 3) coordinates, mm
    tets: np.ndarray  # (M, 10) node indices, Gmsh order
    faces: dict[str, np.ndarray] = field(default_factory=dict)  # name -> (K, 6) tri6, outward
    edges: dict[str, np.ndarray] = field(default_factory=dict)  # name -> (K, 3) line3
    skin: np.ndarray | None = None  # (K, 6) all boundary triangles, for display

    @property
    def n_elements(self) -> int:
        return len(self.tets)


def _face_by_bbox(gmsh, test) -> list[int]:
    out = []
    for dim, tag in gmsh.model.getEntities(2):
        x0, y0, z0, x1, y1, z1 = gmsh.model.getBoundingBox(dim, tag)
        if test(x0, y0, z0, x1, y1, z1):
            out.append(tag)
    return out


def _build_beam(gmsh, s: CantileverBeam) -> dict[str, list[int]]:
    gmsh.model.occ.addBox(0, 0, 0, s.length, s.width, s.height)
    gmsh.model.occ.synchronize()
    tol = 1e-6 * s.length
    size = min(s.width, s.height) / 3 * LEVEL_FACTOR[s.mesh]
    gmsh.option.setNumber("Mesh.MeshSizeMax", size)
    gmsh.option.setNumber("Mesh.MeshSizeMin", size / 3)
    return {
        "fixed": _face_by_bbox(gmsh, lambda x0, y0, z0, x1, y1, z1: abs(x1) < tol),
        "load": _face_by_bbox(gmsh, lambda x0, y0, z0, x1, y1, z1: abs(x0 - s.length) < tol),
    }


def _build_plate(gmsh, s: PlateWithHole) -> dict[str, list[int]]:
    occ = gmsh.model.occ
    box = occ.addBox(0, 0, 0, s.length, s.width, s.thickness)
    hole = occ.addCylinder(s.length / 2, s.width / 2, 0, 0, 0, s.thickness, s.hole_diameter / 2)
    occ.cut([(3, box)], [(3, hole)])
    occ.synchronize()
    tol = 1e-6 * s.length
    f = LEVEL_FACTOR[s.mesh]
    h_far = min(s.width / 8, 2 * s.thickness) * f
    h_hole = min(s.hole_diameter / 12, s.thickness) * f

    r = s.hole_diameter / 2
    hole_faces = _face_by_bbox(
        gmsh,
        lambda x0, y0, z0, x1, y1, z1: abs(x0 - (s.length / 2 - r)) < tol
        and abs(x1 - (s.length / 2 + r)) < tol and (z1 - z0) > tol,
    )
    fld = gmsh.model.mesh.field
    dist = fld.add("Distance")
    fld.setNumbers(dist, "SurfacesList", hole_faces)
    thr = fld.add("Threshold")
    fld.setNumber(thr, "InField", dist)
    fld.setNumber(thr, "SizeMin", h_hole)
    fld.setNumber(thr, "SizeMax", h_far)
    fld.setNumber(thr, "DistMin", 0.25 * s.hole_diameter)
    fld.setNumber(thr, "DistMax", 1.5 * s.hole_diameter)
    fld.setAsBackgroundMesh(thr)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
    return {
        "fixed": _face_by_bbox(gmsh, lambda x0, y0, z0, x1, y1, z1: abs(x1) < tol),
        "load": _face_by_bbox(gmsh, lambda x0, y0, z0, x1, y1, z1: abs(x0 - s.length) < tol),
    }


MAX_ELEMENTS = int(__import__("os").environ.get("SIMLY_MAX_ELEMENTS", "250000"))


class MeshError(ValueError):
    pass


def _build_custom(gmsh, s) -> dict[str, list[int]]:
    from .parts import face_groups, import_part, part_file

    import_part(gmsh, part_file(s.part_id))
    surfaces = {t for _, t in gmsh.model.getEntities(2)}
    curves = {t for _, t in gmsh.model.getEntities(1)}
    groups = face_groups(s.part_id) or {t: [t] for t in surfaces}

    def resolve(sel, name: str, named: dict) -> None:
        if sel.entity == "face":
            missing = set(sel.ids) - set(groups)
            if missing:
                raise MeshError(f"face id(s) {sorted(missing)} do not exist on this part")
            named[name] = [m for f in sel.ids for m in groups[f]]
        elif sel.entity == "edge":
            missing = set(sel.ids) - curves
            if missing:
                raise MeshError(f"edge id(s) {sorted(missing)} do not exist on this part")
            named[EDGE + name] = list(sel.ids)

    x0, y0, z0, x1, y1, z1 = gmsh.model.getBoundingBox(-1, -1)
    dims = sorted([x1 - x0, y1 - y0, z1 - z0])
    diag = sum(d * d for d in dims) ** 0.5
    # at least ~4 quadratic elements across the smallest overall dimension
    size = min(diag / 30, dims[0] / 4) * LEVEL_FACTOR[s.mesh]
    gmsh.option.setNumber("Mesh.MeshSizeMax", size)
    gmsh.option.setNumber("Mesh.MeshSizeMin", size / 10)
    is_stl = part_file(s.part_id).suffix == ".stl"
    # curvature of a faceted STL is noise; for CAD faces it resolves holes and fillets
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0 if is_stl else 12)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0 if is_stl else 1)

    named: dict[str, list[int]] = {}
    for i, sup in enumerate(s.supports):
        resolve(sup, f"sup{i}", named)
    for i, ld in enumerate(s.loads):
        resolve(ld, f"load{i}", named)
    return named


BUILDERS = {
    "cantilever_beam": _build_beam,
    "plate_with_hole": _build_plate,
    "custom_part": _build_custom,
}


def mesh_study(spec) -> Mesh:
    try:
        import gmsh
    except ImportError as e:  # pragma: no cover - environment
        raise RuntimeError("Gmsh is required: pip install gmsh") from e

    with _GMSH_LOCK:
        gmsh.initialize(interruptible=False)  # no signal handler: safe off the main thread
        try:
            gmsh.option.setNumber("General.Terminal", 0)
            gmsh.model.add(spec.template)
            named = BUILDERS[spec.template](gmsh, spec)
            for name, tags in named.items():
                if not tags:
                    raise RuntimeError(f"template {spec.template}: group '{name}' not found")
            gmsh.option.setNumber("Mesh.ElementOrder", 2)
            gmsh.option.setNumber("Mesh.SecondOrderLinear", 1)  # flat faces stay flat
            try:
                gmsh.model.mesh.generate(3)
            except Exception as e:
                raise MeshError("Meshing failed: the part may have gaps, self-intersections "
                                "or features far smaller than the part itself.") from e
            mesh = _extract(gmsh, named)
            if mesh.n_elements == 0:
                raise MeshError("No volume was meshed: is the part a closed solid?")
            if mesh.n_elements > MAX_ELEMENTS:
                raise MeshError(f"The mesh has {mesh.n_elements:,} elements, above the limit "
                                f"of {MAX_ELEMENTS:,}; use a coarser mesh level.")
            scale = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}.get(
                getattr(spec, "units", "mm"), 1.0)
            mesh.nodes = mesh.nodes * scale
            return mesh
        finally:
            gmsh.finalize()


def _extract(gmsh, named: dict[str, list[int]]) -> Mesh:
    tags, coords, _ = gmsh.model.mesh.getNodes()
    index = np.full(int(tags.max()) + 1, -1, dtype=np.int64)
    index[tags.astype(np.int64)] = np.arange(len(tags))
    nodes = coords.reshape(-1, 3)

    def elements(etype: int, entity: int = -1) -> np.ndarray:
        node_tags = gmsh.model.mesh.getElementsByType(etype, entity)[1]
        n = {GMSH_TET10: 10, GMSH_TRI6: 6, GMSH_LINE3: 3}[etype]
        return index[node_tags.astype(np.int64)].reshape(-1, n)

    tets = elements(GMSH_TET10)
    corners = tets[:, :4]

    def outward(tris: np.ndarray) -> np.ndarray:
        """Flip a surface's triangles if they point into the volume.

        One surface is consistently oriented, so one triangle decides: the
        inside node of the tetrahedron that owns it must lie behind the normal.
        """
        if len(tris) == 0:
            return tris
        tri = tris[0, :3]
        owner = corners[np.isin(corners, tri).sum(axis=1) == 3]
        if len(owner):
            inside = nodes[[v for v in owner[0] if v not in tri][0]]
            a, b, c = nodes[tri]
            if np.dot(np.cross(b - a, c - a), inside - a) > 0:
                tris = tris[:, [0, 2, 1, 5, 4, 3]]
        return tris

    faces, edges = {}, {}
    for name, group in named.items():
        if name.startswith(EDGE):
            edges[name[len(EDGE):]] = np.vstack([elements(GMSH_LINE3, t) for t in group])
        else:
            faces[name] = np.vstack([outward(elements(GMSH_TRI6, t)) for t in group])
    return Mesh(nodes=nodes, tets=tets, faces=faces, edges=edges, skin=elements(GMSH_TRI6))
