"""Spec -> mesh -> CalculiX -> results, hand calculations and display data."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .geometry import Mesh, mesh_study
from .materials import MATERIALS, Material
from .solver import FieldResult, read_frd, read_total_reaction, run_ccx, write_input
from .templates import CHECKS, NOTES, SETUP, Comparison


@dataclass
class StudyResult:
    spec: dict
    mesh_info: dict
    summary: dict
    comparisons: list[Comparison]
    note: str
    display: dict = field(repr=False)
    timings: dict = field(default_factory=dict)
    tracked: list[tuple[str, str, float]] = field(default_factory=list)  # for mesh studies

    def to_dict(self) -> dict:
        return {
            "spec": self.spec,
            "mesh": self.mesh_info,
            "summary": self.summary,
            "comparisons": [c.to_dict() for c in self.comparisons],
            "note": self.note,
            "display": self.display,
            "timings": self.timings,
        }


def run_study(spec, work_dir: Path) -> StudyResult:
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    mat = MATERIALS[spec.material]
    t0 = time.perf_counter()

    mesh = mesh_study(spec)
    t1 = time.perf_counter()

    constraints, forces = SETUP[spec.template](spec, mesh)
    write_input(work_dir / "job.inp", mesh, mat.youngs_modulus, mat.poisson_ratio,
                constraints, forces)
    run_ccx(work_dir)
    res = read_frd(work_dir / "job.frd", len(mesh.nodes))
    reaction = read_total_reaction(work_dir / "job.dat")
    t2 = time.perf_counter()
    applied = forces.sum(axis=0)
    equilibrium_error = float(np.linalg.norm(reaction + applied) / np.linalg.norm(applied))

    vm = res.von_mises
    disp_mag = np.linalg.norm(res.displacement, axis=1)
    i_vm = int(np.argmax(vm))
    summary = {
        "material": mat.name,
        "material_key": mat.key,
        "max_von_mises_MPa": round(float(vm[i_vm]), 4),
        "max_von_mises_at_mm": [round(float(v), 3) for v in mesh.nodes[i_vm]],
        "max_displacement_mm": round(float(disp_mag.max()), 6),
        "applied_load_N": spec.load,
        "applied_force_check_N": round(float(np.linalg.norm(applied)), 3),
        "reaction_N": np.round(reaction, 4).tolist(),
        "equilibrium_error_pct": round(100 * equilibrium_error, 5),
        **strength_check(mat, float(vm[i_vm])),
    }
    if equilibrium_error > 1e-3:
        summary["warnings"].append(
            f"Support reactions miss the applied load by {100 * equilibrium_error:.2f}%: "
            "the result should not be trusted."
        )
    comparisons = CHECKS[spec.template](spec, mesh, res)
    return StudyResult(
        spec=spec.model_dump(mode="json"),
        mesh_info={"nodes": len(mesh.nodes), "elements": mesh.n_elements,
                   "element_type": "C3D10 (quadratic tetrahedron)"},
        summary=summary,
        comparisons=comparisons,
        note=NOTES[spec.template],
        display={**surface_display(mesh, res), **markers(mesh, forces, res)},
        timings={"mesh_s": round(t1 - t0, 2), "solve_s": round(t2 - t1, 2)},
        tracked=[(c.quantity, c.unit, c.simulation) for c in comparisons] + [
            ("Max displacement", "mm", float(disp_mag.max())),
            ("Peak von Mises stress", "MPa", float(vm[i_vm])),
        ],
    )


def surface_display(mesh: Mesh, res: FieldResult) -> dict:
    """Boundary surface for the 3D viewer: each 6-node triangle split into 4."""
    t = mesh.skin
    tris = np.vstack([
        t[:, [0, 3, 5]], t[:, [3, 1, 4]], t[:, [5, 4, 2]], t[:, [3, 4, 5]],
    ])
    used, inverse = np.unique(tris, return_inverse=True)
    vm = res.von_mises[used]
    return {
        "positions": np.round(mesh.nodes[used], 4).ravel().tolist(),
        "indices": inverse.astype(int).ravel().tolist(),
        "displacement": np.round(res.displacement[used], 7).ravel().tolist(),
        "von_mises": np.round(vm, 4).tolist(),
        "range": [round(float(vm.min()), 4), round(float(vm.max()), 4)],
    }


def markers(mesh: Mesh, forces: np.ndarray, res: FieldResult) -> dict:
    """Where to draw support and load symbols, and how loaded faces move."""
    corners = mesh.tets[:, :4]

    def face_info(face: str) -> tuple[np.ndarray, np.ndarray]:
        tris = mesh.faces[face]
        p = mesh.nodes
        a, b, c = p[tris[:, 0]], p[tris[:, 1]], p[tris[:, 2]]
        n = np.cross(b - a, c - a).sum(axis=0)
        n /= np.linalg.norm(n) or 1.0
        centre = p[np.unique(tris)].mean(axis=0)
        # outward: away from the inside node of the tetrahedron that owns a face triangle
        tri = tris[0, :3]
        owner = corners[np.isin(corners, tri).sum(axis=1) == 3]
        if len(owner):
            inside = p[[v for v in owner[0] if v not in tri][0]]
            if np.dot(n, inside - p[tri[0]]) > 0:
                n = -n
        return centre, n

    loads = []
    for name in sorted(k for k in mesh.faces if k.startswith("load")):
        nodes = np.unique(mesh.faces[name])
        f = forces[nodes].sum(axis=0)
        centre, normal = face_info(name)
        direction = f / (np.linalg.norm(f) or 1.0)
        loads.append({
            "centre": np.round(centre, 4).tolist(),
            "direction": np.round(direction, 6).tolist(),
            "pulling": bool(np.dot(direction, normal) > 0.5),
            "displacement": np.round(res.displacement[nodes].mean(axis=0), 7).tolist(),
        })
    centre, normal = face_info("fixed")
    return {
        "loads": loads,
        "fixed": [{"centre": np.round(centre, 4).tolist(), "normal": np.round(normal, 5).tolist()}],
        "size": float(np.ptp(mesh.nodes, axis=0).max()),
    }


LINEAR_STRAIN_LIMIT = 0.05


def strength_check(mat: Material, peak_vm: float) -> dict:
    """Safety factors and validity warnings for the peak stress."""
    out: dict = {
        "strength_basis": "yield strength" if mat.yield_strength else "tensile strength",
        "strength_MPa": mat.design_strength,
        "safety_factor": round(mat.design_strength / peak_vm, 3),
        "warnings": [],
    }
    if mat.is_printed:
        out["strength_z_MPa"] = mat.tensile_strength_z
        out["safety_factor_z"] = round(mat.weakest_strength / peak_vm, 3)
        out["warnings"].append(
            "3D-printed part: the stiffness uses the in-layer (X-Y) modulus. If the "
            "peak stress pulls layers apart (Z), use the lower safety factor."
        )
    worst = out.get("safety_factor_z", out["safety_factor"])
    if worst < 1:
        out["warnings"].append(
            "The peak stress exceeds the material strength: the part would yield or "
            "break, and a linear-elastic result past that point is not physical."
        )
    strain = peak_vm / mat.youngs_modulus
    if strain > LINEAR_STRAIN_LIMIT:
        out["warnings"].append(
            f"Peak strain is about {100 * strain:.0f}%: beyond the small-strain range of a "
            "linear analysis, so treat the numbers as a rough indication only."
        )
    return out
