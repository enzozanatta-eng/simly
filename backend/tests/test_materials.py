import pytest

from simly.materials import MATERIALS
from simly.study import strength_check


@pytest.mark.parametrize("key", list(MATERIALS))
def test_material_is_physically_consistent(key):
    m = MATERIALS[key]
    assert m.source, "every material must cite where its numbers come from"
    assert m.design_strength <= m.tensile_strength + 1e-9 or m.yield_strength is None
    if m.yield_strength:
        assert m.yield_strength <= m.tensile_strength
    if m.is_printed:
        # across layers is never stronger or stiffer than within a layer
        assert m.tensile_strength_z is not None and m.tensile_strength_z <= m.tensile_strength
        assert m.youngs_modulus_z is not None and m.youngs_modulus_z <= m.youngs_modulus
    if m.electrical == "conductor":
        assert m.resistivity is not None and m.resistivity < 1e-5
    if m.electrical == "insulator" and m.resistivity is not None:
        assert m.resistivity > 1e6
    # E / density sanity: specific stiffness of engineering solids, MPa/(kg/m3)
    assert 1e-3 < m.youngs_modulus / m.density < 50


def test_printed_part_reports_layer_safety_factor():
    out = strength_check(MATERIALS["petg_hf"], peak_vm=10.0)
    assert out["safety_factor"] == pytest.approx(3.4)
    assert out["safety_factor_z"] == pytest.approx(2.3)
    assert any("3D-printed" in w for w in out["warnings"])


def test_metal_uses_yield_strength():
    out = strength_check(MATERIALS["aluminium"], peak_vm=138.0)
    assert out["strength_basis"] == "yield strength"
    assert out["safety_factor"] == pytest.approx(2.0)
    assert out["warnings"] == []


def test_overload_and_large_strain_are_flagged():
    over = strength_check(MATERIALS["pla"], peak_vm=50.0)
    assert any("exceeds the material strength" in w for w in over["warnings"])
    rubber = strength_check(MATERIALS["tpu_95a"], peak_vm=2.0)
    assert any("small-strain" in w for w in rubber["warnings"])
