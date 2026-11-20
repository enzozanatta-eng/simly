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
GMSH_TET10, GMSH_TRI6 = 11, 9
# Gmsh 10-node tet -> CalculiX C3D10 node order (last two mid-edge nodes swap)
TET10_TO_CCX = [0, 1, 2, 3, 4, 5, 6, 7, 9, 8]

# Gmsh keeps global state and is not thread-safe: one mesh at a time.
_GMSH_LOCK = threading.Lock()


@dataclass
class Mesh:
    nodes: np.ndarray  # (N, 3) coordinates, mm
    tets: np.ndarray  # (M, 10) node indices, Gmsh order
    faces: dict[str, np.ndarray] = field(default_factory=dict)  # name -> (K, 6) tri6
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
    groups = face_groups(s.part_id) or {t: [t] for t in surfaces}
    wanted = set(s.fixed_faces) | {f for ld in s.loads for f in ld.faces}
    missing = wanted - set(groups)
    if missing:
        raise MeshError(f"face id(s) {sorted(missing)} do not exist on this part")

    def expand(face_ids: list[int]) -> list[int]:
        return [m for f in face_ids for m in groups[f]]

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
    named = {"fixed": expand(s.fixed_faces)}
    for i, ld in enumerate(s.loads):
        named[f"load{i}"] = expand(ld.faces)
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
                    raise RuntimeError(f"template {spec.template}: face '{name}' not found")
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

    def elements(dim: int, etype: int, entity: int = -1) -> np.ndarray:
        node_tags = gmsh.model.mesh.getElementsByType(etype, entity)[1]
        n = 10 if etype == GMSH_TET10 else 6
        return index[node_tags.astype(np.int64)].reshape(-1, n)

    faces = {
        name: np.vstack([elements(2, GMSH_TRI6, t) for t in tags]) for name, tags in named.items()
    }
    return Mesh(
        nodes=nodes,
        tets=elements(3, GMSH_TET10),
        faces=faces,
        skin=elements(2, GMSH_TRI6),
    )
