"""Linear static analysis with CalculiX: input deck, run, read results."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .geometry import TET10_TO_CCX, Mesh


class SolverError(RuntimeError):
    pass


@dataclass
class Constraint:
    """Fix the listed degrees of freedom (1=x, 2=y, 3=z) on a set of nodes."""

    nodes: np.ndarray
    dofs: tuple[int, ...]


@dataclass
class FieldResult:
    displacement: np.ndarray  # (N, 3) mm
    stress: np.ndarray  # (N, 6) MPa: xx yy zz xy yz zx

    @property
    def von_mises(self) -> np.ndarray:
        sxx, syy, szz, sxy, syz, szx = self.stress.T
        return np.sqrt(
            0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2)
            + 3 * (sxy**2 + syz**2 + szx**2)
        )


def traction_loads(mesh: Mesh, face: str, traction: np.ndarray) -> np.ndarray:
    """Consistent nodal forces (N, 3) for a uniform traction (N/mm^2) on a tri6 face.

    For a straight-sided 6-node triangle under uniform traction the corner
    nodes take nothing and each mid-side node takes one third of the force.
    """
    forces = np.zeros_like(mesh.nodes)
    tris = mesh.faces[face]
    p = mesh.nodes
    a, b, c = p[tris[:, 0]], p[tris[:, 1]], p[tris[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    share = (area / 3.0)[:, None] * np.asarray(traction)[None, :]
    for col in (3, 4, 5):
        np.add.at(forces, tris[:, col], share)
    return forces


def face_area(mesh: Mesh, face: str) -> float:
    tris = mesh.faces[face]
    p = mesh.nodes
    a, b, c = p[tris[:, 0]], p[tris[:, 1]], p[tris[:, 2]]
    return float(0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1).sum())


def write_input(
    path: Path,
    mesh: Mesh,
    youngs_modulus: float,
    poisson_ratio: float,
    constraints: list[Constraint],
    forces: np.ndarray,
) -> None:
    lines = ["*HEADING", "Simly static study", "*NODE"]
    lines += [f"{i + 1}, {x:.9g}, {y:.9g}, {z:.9g}" for i, (x, y, z) in enumerate(mesh.nodes)]
    lines.append("*ELEMENT, TYPE=C3D10, ELSET=EALL")
    tets = mesh.tets[:, TET10_TO_CCX] + 1
    lines += [f"{e + 1}, " + ", ".join(map(str, row)) for e, row in enumerate(tets)]
    def nset(name: str, nodes: np.ndarray) -> None:
        ids = np.unique(nodes) + 1
        lines.append(f"*NSET, NSET={name}")
        lines.extend(", ".join(map(str, ids[i:i + 16])) for i in range(0, len(ids), 16))

    for k, c in enumerate(constraints):
        nset(f"FIX{k}", c.nodes)
    # every supported node once, so the total reaction is not double counted
    nset("ALLFIX", np.concatenate([c.nodes for c in constraints]))
    lines += [
        "*MATERIAL, NAME=MAT",
        "*ELASTIC",
        f"{youngs_modulus:g}, {poisson_ratio:g}",
        "*SOLID SECTION, ELSET=EALL, MATERIAL=MAT",
        "*STEP",
        "*STATIC",
        "*BOUNDARY",
    ]
    for k, c in enumerate(constraints):
        lines += [f"FIX{k}, {d}, {d}" for d in c.dofs]
    lines.append("*CLOAD")
    for node, f in enumerate(forces):
        for dof in range(3):
            if f[dof] != 0.0:
                lines.append(f"{node + 1}, {dof + 1}, {f[dof]:.9g}")
    lines += ["*NODE FILE", "U", "*EL FILE", "S",
              "*NODE PRINT, NSET=ALLFIX, TOTALS=ONLY", "RF", "*END STEP", ""]
    Path(path).write_text("\n".join(lines))


def run_ccx(job_dir: Path, job: str = "job", timeout_s: float = 300) -> None:
    exe = shutil.which("ccx") or shutil.which("ccx_2.21") or shutil.which("ccx_2.22")
    if exe is None:
        raise SolverError("CalculiX (ccx) not found. Install it: sudo apt install calculix-ccx")
    proc = subprocess.run(
        [exe, "-i", job], cwd=job_dir, capture_output=True, text=True, timeout=timeout_s
    )
    (Path(job_dir) / f"{job}.log").write_text(proc.stdout + proc.stderr)
    if proc.returncode != 0 or "*ERROR" in proc.stdout:
        tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-15:])
        raise SolverError(f"CalculiX failed:\n{tail}")


def read_frd(path: Path, n_nodes: int) -> FieldResult:
    """Read nodal DISP and STRESS blocks from a CalculiX .frd file (fixed-width format)."""
    disp = np.zeros((n_nodes, 3))
    stress = np.zeros((n_nodes, 6))
    target = None
    for line in Path(path).read_text().splitlines():
        if line.startswith(" -4"):
            name = line.split()[1]
            target = {"DISP": (disp, 3), "STRESS": (stress, 6)}.get(name)
        elif line.startswith(" -1") and target is not None:
            arr, n = target
            node = int(line[3:13]) - 1
            arr[node] = [float(line[13 + 12 * i: 25 + 12 * i]) for i in range(n)]
        elif line.startswith(" -3"):
            target = None
    return FieldResult(disp, stress)


def read_total_reaction(path: Path) -> np.ndarray:
    """Total reaction force (N) on the supports, from the CalculiX .dat file."""
    lines = Path(path).read_text().splitlines()
    for i, line in enumerate(lines):
        if "total force" in line.lower():
            for nxt in lines[i + 1:]:
                if nxt.strip():
                    return np.array([float(v) for v in nxt.split()[:3]])
    raise SolverError("no reaction totals in the CalculiX output")
