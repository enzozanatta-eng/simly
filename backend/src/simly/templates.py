"""Per-template boundary conditions and hand calculations.

Every template pairs the simulation with the textbook formula it teaches, so
each result is shown next to an independent check.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from .geometry import Mesh
from .materials import MATERIALS
from .solver import Constraint, FieldResult, face_area, traction_loads
from .spec import CantileverBeam, CustomPart, PlateWithHole


@dataclass
class Comparison:
    quantity: str
    formula: str
    hand_calc: float
    simulation: float
    unit: str
    note: str = ""

    @property
    def error_pct(self) -> float:
        return 100 * (self.simulation - self.hand_calc) / self.hand_calc

    @property
    def status(self) -> str:
        e = abs(self.error_pct)
        return "PASS" if e <= 5 else "WARN" if e <= 10 else "FAIL"

    def to_dict(self) -> dict:
        return {**asdict(self), "error_pct": round(self.error_pct, 2), "status": self.status}


def _nodes_of(mesh: Mesh, face: str) -> np.ndarray:
    return np.unique(mesh.faces[face])


# ------------------------------------------------------------- cantilever beam

def beam_setup(s: CantileverBeam, mesh: Mesh) -> tuple[list[Constraint], np.ndarray]:
    traction = np.array([0.0, 0.0, -s.load / face_area(mesh, "load")])
    return [Constraint(_nodes_of(mesh, "fixed"), (1, 2, 3))], traction_loads(mesh, "load", traction)


def beam_checks(s: CantileverBeam, mesh: Mesh, res: FieldResult) -> list[Comparison]:
    mat = MATERIALS[s.material]
    E, nu = mat.youngs_modulus, mat.poisson_ratio
    b, h, L, P = s.width, s.height, s.length, s.load
    inertia = b * h**3 / 12
    shear_modulus = E / (2 * (1 + nu))
    d_bending = P * L**3 / (3 * E * inertia)
    d_shear = P * L / ((5 / 6) * shear_modulus * b * h)

    tip = _nodes_of(mesh, "load")
    d_fea = float(-res.displacement[tip, 2].mean())

    # bending stress on the top fibre at mid-span: fit sigma_xx(x) along a band
    x, z = mesh.nodes[:, 0], mesh.nodes[:, 2]
    band = (np.abs(z - h) < 1e-6 * h) & (np.abs(x - L / 2) < 0.1 * L)
    coeffs = np.polyfit(x[band], res.stress[band, 0], 1)
    s_fea = float(np.polyval(coeffs, L / 2))
    s_hand = (P * L / 2) * (h / 2) / inertia

    return [
        Comparison(
            "Tip deflection",
            "δ = PL³/(3EI) + PL/(κGA)",
            d_bending + d_shear, d_fea, "mm",
            note=f"bending {d_bending:.4g} mm + shear {d_shear:.3g} mm (Timoshenko, κ = 5/6)",
        ),
        Comparison(
            "Bending stress at mid-span (top fibre)",
            "σ = M·c/I, M = P·L/2",
            s_hand, s_fea, "MPa",
        ),
    ]


# ------------------------------------------------------------- plate with hole

def plate_setup(s: PlateWithHole, mesh: Mesh) -> tuple[list[Constraint], np.ndarray]:
    fixed = _nodes_of(mesh, "fixed")
    p = mesh.nodes[fixed]

    def closest(target) -> np.ndarray:
        return fixed[[int(np.argmin(np.linalg.norm(p - np.asarray(target), axis=1)))]]

    # x-symmetry on the left face; two points stop the remaining rigid motions
    # (translation in y and z, rotation about x) without restraining Poisson contraction
    centre = closest((0, s.width / 2, s.thickness / 2))
    corner = closest((0, 0, s.thickness / 2))
    constraints = [
        Constraint(fixed, (1,)),
        Constraint(centre, (2, 3)),
        Constraint(corner, (3,)),
    ]
    traction = np.array([s.load / face_area(mesh, "load"), 0.0, 0.0])
    return constraints, traction_loads(mesh, "load", traction)


def plate_checks(s: PlateWithHole, mesh: Mesh, res: FieldResult) -> list[Comparison]:
    ratio = s.hole_diameter / s.width
    kt = 2 + (1 - ratio) ** 3  # Heywood, net-section
    s_nom = s.load / ((s.width - s.hole_diameter) * s.thickness)
    peak = int(np.argmax(res.stress[:, 0]))
    px, py, _ = mesh.nodes[peak]
    r_peak = np.hypot(px - s.length / 2, py - s.width / 2)
    where = (
        "at the hole edge" if abs(r_peak - s.hole_diameter / 2) < 0.05 * s.hole_diameter
        else f"{r_peak:.3g} mm from the hole centre"
    )
    return [
        Comparison(
            "Peak stress at the hole",
            "σ_max = Kt·F/((W−d)·t), Kt = 2 + (1 − d/W)³",
            kt * s_nom, float(res.stress[peak, 0]), "MPa",
            note=f"Kt = {kt:.3f} (Heywood), nominal net-section stress {s_nom:.4g} MPa; "
            f"simulated peak found {where}",
        ),
    ]


# ------------------------------------------------------------- custom part

def custom_setup(s: CustomPart, mesh: Mesh) -> tuple[list[Constraint], np.ndarray]:
    forces = np.zeros_like(mesh.nodes)
    for i, ld in enumerate(s.loads):
        face = f"load{i}"
        forces += traction_loads(mesh, face, np.asarray(ld.force) / face_area(mesh, face))
    return [Constraint(_nodes_of(mesh, "fixed"), (1, 2, 3))], forces


def custom_checks(s: CustomPart, mesh: Mesh, res: FieldResult) -> list[Comparison]:
    return []  # no closed-form answer for an arbitrary shape


SETUP = {"cantilever_beam": beam_setup, "plate_with_hole": plate_setup,
         "custom_part": custom_setup}
CHECKS = {"cantilever_beam": beam_checks, "plate_with_hole": plate_checks,
          "custom_part": custom_checks}

NOTES = {
    "custom_part": (
        "An arbitrary shape has no textbook formula, so this result is checked by force "
        "equilibrium (support reactions must balance the applied loads) and, if you run "
        "it, the mesh convergence study. Peak stress at a sharp inside corner or at the "
        "edge of a support keeps rising as the mesh is refined (a singularity): judge the "
        "part by the stress a little away from such points, or add a fillet."
    ),
    "cantilever_beam": (
        "The clamped end is fully fixed, which also blocks Poisson contraction there. "
        "This creates a local stress peak at the clamp corners that beam theory does not "
        "have, so the peak von Mises value sits above M·c/I. That is why the stress is "
        "checked at mid-span."
    ),
    "plate_with_hole": (
        "The left face is held only along the load direction, so the plate can contract "
        "sideways as a real bar does; the peak stress comes from the hole alone."
    ),
}
