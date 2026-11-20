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
    spec = CustomPart(part_id=part, material="steel", mesh="medium",
                      supports=[{"entity": "face", "ids": [fixed]}],
                      loads=[{"entity": "face", "ids": [tip], "vector": [0, 0, -1000]}])
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
    spec = CustomPart(part_id=part, material="petg", mesh="coarse",
                      supports=[{"entity": "face", "ids": [base_end]}],
                      loads=[{"entity": "face", "ids": [top], "vector": [50, 0, 0]}])
    r = run_study(spec, tmp_path / "run")
    assert r.summary["safety_factor_z"] < r.summary["safety_factor"]
    assert r.display["loads"][0]["direction"] == pytest.approx([1, 0, 0])


def test_missing_face_is_a_clear_error(tmp_path):
    part = upload(tmp_path, ".step")
    client = TestClient(api.app)
    r = client.post("/api/simulate", json={"spec": {
        "template": "custom_part", "part_id": part,
        "supports": [{"entity": "face", "ids": [999]}],
        "loads": [{"entity": "face", "ids": [1], "vector": [0, 0, -1]}]}})
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


def beam_deflection():
    E, nu = MATERIALS["steel"].youngs_modulus, MATERIALS["steel"].poisson_ratio
    inertia = 50 * 80**3 / 12
    return 1000 * 1000**3 / (3 * E * inertia) + 1000 * 1000 / (5 / 6 * E / (2 * (1 + nu)) * 4000)


def tip_of(result):
    return max(abs(d) for d in result.display["displacement"][2::3])


@needs_solver
def test_box_reports_edges_and_corners(tmp_path):
    info = describe_part(upload(tmp_path, ".step"))
    assert len(info["edges"]) == 12 and len(info["vertices"]) == 8
    long_edges = [e for e in info["edges"] if abs(e["length_mm"] - 1000) < 1e-3]
    assert len(long_edges) == 4 and all(e["direction"] for e in long_edges)
    assert len(info["display"]["edge_of_segment"]) * 6 == len(info["display"]["edge_segments"])


@needs_solver
def test_line_load_on_tip_edge_and_point_load(tmp_path):
    part = upload(tmp_path, ".step")
    info = describe_part(part)
    fixed = face_at(info, 0, 0.0)
    # top edge at the tip: x = 1000, z = 80, running along y
    tip_edge = next(e["id"] for e in info["edges"]
                    if abs(e["midpoint"][0] - 1000) < 1e-3 and abs(e["midpoint"][2] - 80) < 1e-3)
    for load in ({"entity": "edge", "ids": [tip_edge], "vector": [0, 0, -1000]},
                 {"entity": "point", "point": [1000, 25, 80], "vector": [0, 0, -1000]}):
        spec = CustomPart(part_id=part, material="steel", mesh="coarse",
                          supports=[{"entity": "face", "ids": [fixed]}], loads=[load])
        r = run_study(spec, tmp_path / load["entity"])
        assert r.summary["equilibrium_error_pct"] < 0.01
        # load on the top edge instead of spread over the end face: same beam answer
        assert tip_of(r) == pytest.approx(beam_deflection(), rel=0.05), load["entity"]


@needs_solver
def test_pressure_on_top_face_equals_its_resultant(tmp_path):
    part = upload(tmp_path, ".step")
    info = describe_part(part)
    fixed, top = face_at(info, 0, 0.0), face_at(info, 2, 80.0)
    p = 0.02  # MPa on 1000 x 50 mm = 1000 N downwards
    spec = CustomPart(part_id=part, material="steel", mesh="coarse",
                      supports=[{"entity": "face", "ids": [fixed]}],
                      loads=[{"entity": "face", "ids": [top], "kind": "pressure", "pressure": p}])
    r = run_study(spec, tmp_path / "run")
    assert r.summary["applied_force_check_N"] == pytest.approx(1000, abs=1e-6)
    assert r.summary["equilibrium_error_pct"] < 0.01
    (mark,) = r.display["loads"]
    assert mark["direction"] == pytest.approx([0, 0, -1], abs=1e-6)  # into the face


@needs_solver
def test_torque_on_shaft_matches_torsion_theory(tmp_path):
    part = upload(tmp_path, ".step", "shaft")
    info = describe_part(part)
    fixed, end = face_at(info, 0, 0.0), face_at(info, 0, 200.0)
    torque = 50_000.0  # N mm
    spec = CustomPart(part_id=part, material="steel", mesh="fine",
                      supports=[{"entity": "face", "ids": [fixed]}],
                      loads=[{"entity": "face", "ids": [end], "kind": "moment",
                              "vector": [torque, 0, 0]}])
    r = run_study(spec, tmp_path / "run")
    assert r.summary["equilibrium_error_pct"] < 0.01  # pure moment: no net force

    E, nu = MATERIALS["steel"].youngs_modulus, MATERIALS["steel"].poisson_ratio
    G, d, L = E / (2 * (1 + nu)), 20.0, 200.0
    twist = torque * L / (G * 3.141592653589793 * d**4 / 32)  # rad
    # rim of the loaded end: tangential displacement = twist x radius
    import numpy as np
    pos = np.array(r.display["positions"]).reshape(-1, 3)
    disp = np.array(r.display["displacement"]).reshape(-1, 3)
    rim = (np.abs(pos[:, 0] - L) < 1e-6) & (np.abs(np.hypot(pos[:, 1], pos[:, 2]) - 10) < 0.05)
    tangential = (pos[rim, 1] * disp[rim, 2] - pos[rim, 2] * disp[rim, 1]) / 10
    assert tangential.mean() / 10 == pytest.approx(twist, rel=0.03)

    # peak shear stress 16 T / (pi d^3) -> von Mises sqrt(3) tau, away from the clamp
    tau = 16 * torque / (3.141592653589793 * d**3)
    vm = np.array(r.display["von_mises"])
    mid = (np.abs(pos[:, 0] - L / 2) < 15) & (np.abs(np.hypot(pos[:, 1], pos[:, 2]) - 10) < 0.05)
    assert vm[mid].mean() == pytest.approx(3**0.5 * tau, rel=0.05)


def test_moment_at_a_point_is_rejected():
    with pytest.raises(ValueError, match="moment"):
        CustomPart(part_id="0" * 16, supports=[{"entity": "face", "ids": [1]}],
                   loads=[{"entity": "point", "point": [0, 0, 0], "kind": "moment",
                           "vector": [1, 0, 0]}])


def test_ai_sets_up_an_uploaded_part(tmp_path):
    from simly.ai import plan_part
    from simly.llm import ToolCall, ToolResult

    part = upload(tmp_path, ".step")
    info = describe_part(part)
    fixed, tip = face_at(info, 0, 0.0), face_at(info, 0, 1000.0)

    class Scripted:
        def __init__(self):
            self.seen = []
            self.calls = [
                ToolCall("a", "propose_part_setup", {   # face 999 does not exist
                    "supports": [{"entity": "face", "ids": [999]}],
                    "loads": [{"entity": "face", "ids": [tip], "vector": [0, 0, -98.1]}],
                    "material": "petg", "rationale": "first try"}),
                ToolCall("b", "propose_part_setup", {
                    "supports": [{"entity": "face", "ids": [fixed]}],
                    "loads": [{"entity": "face", "ids": [tip], "vector": [0, 0, -98.1]}],
                    "material": "petg", "rationale": "Clamped at the left end, 10 kg on the tip."}),
            ]

        def call(self, system, history, tools):
            self.seen.append(list(history))
            return self.calls.pop(0)

    llm = Scripted()
    plan = plan_part("clamped at the left end, 10 kg hanging at the tip", info, llm)
    assert plan.spec.supports[0].ids == [fixed] and plan.spec.material == "petg"
    assert "Clamped" in plan.rationale
    assert "999" in plan.attempts[0]["error"]
    assert isinstance(llm.seen[1][-1], ToolResult)
    assert f"\n  face {tip}: plane" in llm.seen[0][0].text  # the model sees the part's faces


@pytest.mark.parametrize("suffix", [".step", ".stl"])
def test_hole_and_cylinder_are_recognised(tmp_path, suffix):
    bracket = describe_part(upload(tmp_path, suffix, "bracket"))
    (hole,) = [f for f in bracket["faces"] if f["kind"] == "hole"]
    assert hole["diameter_mm"] == pytest.approx(10, rel=0.08)  # faceted circle
    assert hole["axis"] == pytest.approx([1, 0, 0], abs=0.01)
    assert len(hole["neighbours"]) == 2  # the two faces the hole opens onto
    shaft = describe_part(upload(tmp_path, suffix, "shaft"))
    (side,) = [f for f in shaft["faces"] if f["kind"] != "plane"]
    assert side["kind"] == "cylinder" and side["diameter_mm"] == pytest.approx(20, rel=0.08)


def test_summary_labels_holes_and_gravity(tmp_path):
    from simly.ai import part_summary

    text = part_summary(describe_part(upload(tmp_path, ".step", "bracket")), gravity="-y")
    assert "Gravity (down) in the part's coordinates: -Y" in text
    assert "hole diameter" in text and "neighbours" in text


def test_summary_ranks_resting_faces(tmp_path):
    from simly.ai import part_summary

    text = part_summary(describe_part(upload(tmp_path, ".step", "bracket")), gravity="-z")
    up = next(line for line in text.splitlines() if line.startswith("Upward-facing"))
    # the top of the horizontal arm (2960 mm2) comes before the top of the leg (240 mm2)
    assert up.index("2960") < up.index("240 mm2")


@pytest.mark.parametrize("gravity, expected", [("-z", [0, 0, -490.5]), ("+z", [0, 0, 490.5]),
                                               ("-y", [0, -490.5, 0])])
def test_weight_follows_gravity_whatever_the_orientation(gravity, expected):
    """The model gives kilograms; Simly picks the sign of "down" for the file."""
    from simly.ai import resolve_weights

    (ld,) = resolve_weights([{"entity": "face", "ids": [3], "weight_kg": 50}], gravity)
    assert ld["kind"] == "force" and "weight_kg" not in ld
    assert ld["vector"] == pytest.approx(expected)
    with pytest.raises(ValueError):
        resolve_weights([{"entity": "face", "ids": [3], "weight_kg": -1}], gravity)


def test_ai_weight_on_an_upside_down_part(tmp_path):
    from simly.ai import plan_part
    from simly.llm import ToolCall

    info = describe_part(upload(tmp_path, ".step"))
    fixed, tip = face_at(info, 0, 0.0), face_at(info, 0, 1000.0)

    class Scripted:
        def call(self, system, history, tools):
            assert "weight_kg" in str(tools[0].input_schema)
            return ToolCall("a", "propose_part_setup", {
                "supports": [{"entity": "face", "ids": [fixed]}],
                "loads": [{"entity": "face", "ids": [tip], "weight_kg": 10}],
                "material": "pla", "rationale": "ok"})

    plan = plan_part("10 kg at the tip", info, Scripted(), gravity="+z")
    assert plan.spec.loads[0].vector == pytest.approx([0, 0, 98.1])


def test_equilibrium_when_the_load_touches_a_contact_support(tmp_path):
    """Load on the top of the leg shares an edge with the wall face held in X only:
    CalculiX's RF there also carries the applied Z load, which must not read as an error."""
    info = describe_part(upload(tmp_path, ".step", "bracket"))
    hole = next(f["id"] for f in info["faces"] if f["kind"] == "hole")
    back, top = face_at(info, 0, 0.0), face_at(info, 2, 60.0)
    spec = CustomPart(part_id=info["part_id"],
                      supports=[{"entity": "face", "ids": [hole]},
                                {"entity": "face", "ids": [back], "dofs": [1]}],
                      loads=[{"entity": "face", "ids": [top], "vector": [0, 0, -491]}])
    res = run_study(spec, tmp_path / "run")
    assert res.summary["equilibrium_error_pct"] < 1e-3
    assert res.summary["reaction_N"] == pytest.approx([0, 0, 491], abs=0.01)
