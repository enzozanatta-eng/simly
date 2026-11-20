"""Mesh convergence study with the Grid Convergence Index (GCI).

Runs the study on three meshes and applies the procedure of Celik et al.
(2008), "Procedure for estimation and reporting of uncertainty due to
discretization in CFD applications", J. Fluids Eng. 130(7). Unstructured
meshes do not refine by an exact ratio, so the effective ratio comes from the
element counts: r = (N_fine / N_coarse)^(1/3).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from .study import StudyResult, run_study

SAFETY_FACTOR = 1.25  # three meshes
LEVELS = ("coarse", "medium", "fine")
CONVERGED_REL = 1e-3  # both mesh-to-mesh changes under 0.1%: converged
# Unstructured meshes add noise to the observed order; keep it in a physical
# range (quadratic elements: order 2 for stress, 3 for displacement).
P_MIN, P_MAX = 0.5, 3.0


@dataclass
class GCI:
    quantity: str
    unit: str
    values: tuple[float, float, float]  # fine, medium, coarse
    order: float | None  # observed order of accuracy p
    extrapolated: float | None
    gci_fine_pct: float  # uncertainty band of the fine-mesh value
    behaviour: str  # "monotonic", "oscillatory", "converged" or "singular"
    order_clipped: bool = False

    def to_dict(self) -> dict:
        return {
            "quantity": self.quantity,
            "unit": self.unit,
            "fine": self.values[0], "medium": self.values[1], "coarse": self.values[2],
            "observed_order": None if self.order is None else round(self.order, 2),
            "extrapolated": None if self.extrapolated is None else round(self.extrapolated, 6),
            "gci_fine_pct": round(self.gci_fine_pct, 3),
            "behaviour": self.behaviour,
            "order_clipped": self.order_clipped,
        }


def gci(f1: float, f2: float, f3: float, r21: float, r32: float,
        quantity: str = "", unit: str = "") -> GCI:
    """f1 fine, f2 medium, f3 coarse; r21 = h2/h1 > 1, r32 = h3/h2 > 1."""
    e21, e32 = f2 - f1, f3 - f2
    rel21, rel32 = abs(e21 / f1), abs(e32 / f2)
    if max(rel21, rel32) < CONVERGED_REL:
        band = SAFETY_FACTOR * max(rel21, rel32)
        return GCI(quantity, unit, (f1, f2, f3), None, None, 100 * band, "converged")

    s = math.copysign(1.0, e32 / e21)
    if s < 0:
        # oscillatory: no meaningful observed order; use the formal order 2 with
        # the conservative factor of safety 3
        band = 3.0 * abs(e21 / f1) / (r21**2 - 1)
        return GCI(quantity, unit, (f1, f2, f3), None, None, 100 * band, "oscillatory")

    p = 2.0
    for _ in range(100):  # fixed-point iteration (Celik eq. 5)
        q = math.log((r21**p - s) / (r32**p - s))
        p_new = abs(math.log(abs(e32 / e21)) + q) / math.log(r21)
        if abs(p_new - p) < 1e-8:
            break
        p = p_new
    clipped = not P_MIN <= p_new <= P_MAX
    p = min(max(p_new, P_MIN), P_MAX)
    extrapolated = (r21**p * f1 - f2) / (r21**p - 1)
    band = SAFETY_FACTOR * abs(e21 / f1) / (r21**p - 1)
    return GCI(quantity, unit, (f1, f2, f3), p, extrapolated, 100 * band, "monotonic", clipped)


@dataclass
class ConvergenceResult:
    fine: StudyResult
    elements: dict[str, int]
    ratios: tuple[float, float]
    gcis: list[GCI]

    def to_dict(self) -> dict:
        out = self.fine.to_dict()
        out["convergence"] = {
            "elements": self.elements,
            "refinement_ratios": [round(r, 3) for r in self.ratios],
            "quantities": [g.to_dict() for g in self.gcis],
            "method": "Celik et al. (2008) GCI, effective r from element counts",
        }
        return out


def run_convergence(spec, work_dir: Path) -> ConvergenceResult:
    results: dict[str, StudyResult] = {}
    for level in LEVELS:
        variant = spec.model_copy(update={"mesh": level})
        results[level] = run_study(variant, Path(work_dir) / level)

    n = {lvl: results[lvl].mesh_info["elements"] for lvl in LEVELS}
    r21 = (n["fine"] / n["medium"]) ** (1 / 3)
    r32 = (n["medium"] / n["coarse"]) ** (1 / 3)

    gcis = []
    for i, (quantity, unit, _) in enumerate(results["fine"].tracked):
        f1, f2, f3 = (results[lv].tracked[i][2] for lv in ("fine", "medium", "coarse"))
        g = gci(f1, f2, f3, r21, r32, quantity, unit)
        if "stress" in quantity.lower() and f1 > f2 > f3 and g.gci_fine_pct > 5:
            g.behaviour = "singular"
        gcis.append(g)
    if any(g.behaviour == "singular" for g in gcis):
        results["fine"].summary["warnings"].append(
            "The peak stress keeps rising as the mesh is refined: a stress singularity "
            "(sharp inside corner, or the edge of a support or load). That peak is not a "
            "real value; judge the part by the stress nearby, or add a fillet."
        )
    return ConvergenceResult(results["fine"], n, (r21, r32), gcis)
