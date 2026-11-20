import pytest
from pydantic import ValidationError

from simly.spec import CantileverBeam, PlateWithHole, parse_spec


def test_parse_by_template():
    s = parse_spec({"template": "cantilever_beam", "length": 1000, "width": 40,
                    "height": 60, "load": 500})
    assert isinstance(s, CantileverBeam) and s.material == "steel"


def test_block_is_not_a_beam():
    with pytest.raises(ValidationError, match="not a beam"):
        CantileverBeam(length=100, width=80, height=80, load=10)


def test_hole_ratio_outside_kt_formula():
    with pytest.raises(ValidationError, match="0.05 to 0.65"):
        PlateWithHole(length=300, width=100, thickness=5, hole_diameter=80, load=1000)


def test_unknown_material_rejected():
    with pytest.raises(ValidationError):
        parse_spec({"template": "cantilever_beam", "length": 1000, "width": 40,
                    "height": 60, "load": 500, "material": "unobtainium"})


def test_mesh_size_guard_rails():
    with pytest.raises(ValidationError, match="slender"):
        CantileverBeam(length=10_000, width=5, height=5, load=1)
    with pytest.raises(ValidationError, match="too thin"):
        PlateWithHole(length=2000, width=1000, thickness=1, hole_diameter=200, load=1)
