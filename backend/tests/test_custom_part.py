"""Uploaded parts: face detection and a box checked against beam theory."""

import pytest
from conftest import needs_solver
from fastapi.testclient import TestClient
from parts_factory import make_part

from simly import api
from simly.materials import MATERIALS
from simly.parts import PartError, describe_part, save_upload
from simly.spec import CustomPart
from simly.study import run_study

pytest.importorskip("gmsh")


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMLY_RUNS", str(tmp_path / "store"))


def upload(tmp_path, suffix, shape="box"):
    f = make_part(tmp_path / f"part{suffix}", shape)
    return save_upload(f.read_bytes(), f.name)


def face_at(info, axis, value, tol=1e-3):
    hits = [f["id"] for f in info["faces"] if abs(f["centroid"][axis] - value) < tol]
    assert len(hits) == 1, hits
    return hits[0]


@pytest.mark.parametrize("suffix", [".step", ".stl"])
def test_bracket_faces_match_between_step_and_stl(tmp_path, suffix):
    info = describe_part(upload(tmp_path, suffix, "bracket"))
    assert len(info["faces"]) == 9  # the hole is its own face, not merged with its walls


@pytest.mark.parametrize("suffix", [".step", ".stl"])
def test_box_has_six_faces(tmp_path, suffix):
    info = describe_part(upload(tmp_path, suffix))
    assert len(info["faces"]) == 6
    assert info["bbox_mm"]["size"] == pytest.approx([1000, 50, 80], abs=1e-3)
    n_tris = len(info["display"]["indices"]) // 3
    assert len(info["display"]["face_of_triangle"]) == n_tris


def test_units_scale_the_part(tmp_path):
    info = describe_part(upload(tmp_path, ".step"), units="cm")
    assert info["bbox_mm"]["size"][0] == pytest.approx(10_000)


def test_rejects_other_files():
    with pytest.raises(PartError, match=".stl"):
        save_upload(b"hello", "notes.txt")


@needs_solver
@pytest.mark.parametrize("suffix", [".step", ".stl"])
def test_uploaded_box_matches_beam_theory(tmp_path, suffix):
    part = upload(tmp_path, suffix)
    info = describe_part(part)
    fixed, tip = face_at(info, 0, 0.0), face_at(info, 0, 1000.0)
    spec = CustomPart(part_id=part, fixed_faces=[fixed], material="steel", mesh="medium",
                      loads=[{"faces": [tip], "force": [0, 0, -1000]}])
    r = run_study(spec, tmp_path / "run")

    E, nu = MATERIALS["steel"].youngs_modulus, MATERIALS["steel"].poisson_ratio
    inertia = 50 * 80**3 / 12
    shear_modulus = E / (2 * (1 + nu))
    expected = 1000 * 1000**3 / (3 * E * inertia) + 1000 * 1000 / (5 / 6 * shear_modulus * 4000)
    tip_deflection = max(abs(d) for d in r.display["displacement"][2::3])
    assert tip_deflection == pytest.approx(expected, rel=0.03)
    assert r.summary["equilibrium_error_pct"] < 0.01
    assert r.comparisons == []


@needs_solver
@pytest.mark.parametrize("suffix", [".step", ".stl"])
def test_bracket_with_hole_runs(tmp_path, suffix):
    part = upload(tmp_path, suffix, "bracket")
    info = describe_part(part)
    base_end = face_at(info, 0, 80.0)          # far end of the base
    top = face_at(info, 2, 60.0)               # top of the vertical leg
    spec = CustomPart(part_id=part, fixed_faces=[base_end], material="petg",
                      loads=[{"faces": [top], "force": [50, 0, 0]}], mesh="coarse")
    r = run_study(spec, tmp_path / "run")
    assert r.summary["safety_factor_z"] < r.summary["safety_factor"]
    assert r.display["loads"][0]["direction"] == pytest.approx([1, 0, 0])


def test_missing_face_is_a_clear_error(tmp_path):
    part = upload(tmp_path, ".step")
    client = TestClient(api.app)
    r = client.post("/api/simulate", json={"spec": {
        "template": "custom_part", "part_id": part, "fixed_faces": [999],
        "loads": [{"faces": [1], "force": [0, 0, -1]}]}})
    assert r.status_code == 422
    assert "999" in r.json()["detail"]["error"]


@pytest.mark.parametrize("suffix", [".step", ".stl"])
def test_face_normals_point_out_of_the_part(tmp_path, suffix):
    info = describe_part(upload(tmp_path, suffix, "bracket"))
    # inner face of the vertical leg (x = 6): its outside is towards +x,
    # even though it faces the middle of the part's bounding box
    inner = next(f for f in info["faces"] if abs(f["centroid"][0] - 6) < 0.05)
    assert inner["normal"] == pytest.approx([1, 0, 0], abs=1e-3)
    outer = next(f for f in info["faces"] if abs(f["centroid"][0]) < 0.05)
    assert outer["normal"] == pytest.approx([-1, 0, 0], abs=1e-3)
