"""Full studies against hand calculations (needs Gmsh and CalculiX)."""

import pytest
from conftest import needs_solver

from simly.convergence import run_convergence
from simly.spec import CantileverBeam, PlateWithHole
from simly.study import run_study

pytestmark = needs_solver


def test_cantilever_matches_beam_theory(tmp_path):
    spec = CantileverBeam(length=1000, width=50, height=80, load=1000, mesh="coarse")
    r = run_study(spec, tmp_path)
    for c in r.comparisons:
        assert abs(c.error_pct) < 2, (c.quantity, c.error_pct)
    assert r.summary["applied_force_check_N"] == pytest.approx(1000)


def test_plate_matches_kt(tmp_path):
    spec = PlateWithHole(length=200, width=100, thickness=5, hole_diameter=30,
                         load=10_000, mesh="coarse")
    (peak,) = run_study(spec, tmp_path).comparisons
    assert abs(peak.error_pct) < 5
    assert "hole edge" in peak.note


def test_display_payload_is_consistent(tmp_path):
    spec = CantileverBeam(length=500, width=30, height=30, load=100, mesh="coarse")
    d = run_study(spec, tmp_path).display
    n = len(d["positions"]) // 3
    assert len(d["von_mises"]) == n and len(d["displacement"]) == 3 * n
    assert max(d["indices"]) == n - 1


def test_convergence_reports_uncertainty(tmp_path):
    spec = PlateWithHole(length=200, width=100, thickness=5, hole_diameter=30, load=10_000)
    out = run_convergence(spec, tmp_path).to_dict()["convergence"]
    assert out["elements"]["fine"] > out["elements"]["medium"] > out["elements"]["coarse"]
    by_name = {q["quantity"]: q for q in out["quantities"]}
    assert set(by_name) == {"Peak stress at the hole", "Max displacement", "Peak von Mises stress"}
    assert by_name["Peak stress at the hole"]["gci_fine_pct"] < 2
    assert by_name["Peak stress at the hole"]["behaviour"] != "singular"


def test_equilibrium_is_checked(tmp_path):
    spec = PlateWithHole(length=200, width=100, thickness=5, hole_diameter=30,
                         load=10_000, mesh="coarse")
    s = run_study(spec, tmp_path).summary
    assert s["equilibrium_error_pct"] < 0.01
    assert s["reaction_N"][0] == pytest.approx(-10_000, rel=1e-4)
