"""Solver pieces that need neither Gmsh nor CalculiX."""

import numpy as np
import pytest

from simly.convergence import gci
from simly.geometry import Mesh
from simly.solver import FieldResult, read_frd, traction_loads


def unit_square_face() -> Mesh:
    # two straight-sided tri6 covering the unit square in z = 0
    p = {(0, 0): 0, (1, 0): 1, (1, 1): 2, (0, 1): 3, (.5, 0): 4, (1, .5): 5,
         (.5, .5): 6, (0, .5): 7, (.5, 1): 8}
    nodes = np.array([[x, y, 0.0] for (x, y) in p])
    tris = np.array([[0, 1, 2, 4, 5, 6], [0, 2, 3, 6, 8, 7]])
    return Mesh(nodes=nodes, tets=np.zeros((0, 10), int), faces={"load": tris}, skin=tris)


def test_traction_total_and_corner_nodes():
    mesh = unit_square_face()
    f = traction_loads(mesh, "load", np.array([0.0, 0.0, -2.0]))
    assert f.sum(axis=0) == pytest.approx([0, 0, -2.0])  # traction x area
    assert np.all(f[[0, 1, 2, 3]] == 0)  # quadratic triangles: corners carry nothing


def test_read_frd_fixed_width(tmp_path):
    frd = tmp_path / "job.frd"
    frd.write_text(
        "    1PSTEP                         1           1           1\n"
        "  100CL  101 1.000000000           2                     0    1           1\n"
        " -4  DISP        4    1\n"
        " -5  D1          1    2    1    0\n"
        " -1         1 1.00000E-01-2.00000E-02 0.00000E+00\n"
        " -1         2 3.00000E-01 0.00000E+00-4.00000E-03\n"
        " -3\n"
        " -4  STRESS      6    1\n"
        " -1         1 1.00000E+02 0.00000E+00 0.00000E+00 0.00000E+00 0.00000E+00 0.00000E+00\n"
        " -1         2 0.00000E+00 0.00000E+00 0.00000E+00 5.00000E+01 0.00000E+00 0.00000E+00\n"
        " -3\n"
    )
    r = read_frd(frd, 2)
    assert r.displacement[0] == pytest.approx([0.1, -0.02, 0])
    assert r.displacement[1, 2] == pytest.approx(-0.004)
    vm = r.von_mises
    assert vm[0] == pytest.approx(100.0)  # uniaxial
    assert vm[1] == pytest.approx(np.sqrt(3) * 50)  # pure shear


def test_von_mises_hydrostatic_is_zero():
    r = FieldResult(np.zeros((1, 3)), np.array([[80.0, 80.0, 80.0, 0, 0, 0]]))
    assert r.von_mises[0] == pytest.approx(0.0)


def test_gci_recovers_known_order():
    h = np.array([1.0, 1.5, 2.25])
    f = 10 + 2 * h**2  # exact value 10, second order
    g = gci(*f, 1.5, 1.5)
    assert g.order == pytest.approx(2.0)
    assert g.extrapolated == pytest.approx(10.0)
    assert g.behaviour == "monotonic"


def test_gci_flags_oscillation_and_convergence():
    assert gci(10.0, 10.2, 9.9, 1.5, 1.5).behaviour == "oscillatory"
    assert gci(10.0, 10.0001, 10.0002, 1.5, 1.5).behaviour == "converged"
