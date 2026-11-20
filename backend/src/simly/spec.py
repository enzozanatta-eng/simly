"""Study specifications: what to simulate, validated before anything runs.

Units throughout: millimetres, newtons, megapascals (N/mm^2).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, TypeAdapter, model_validator

from .materials import MATERIALS


def _known_material(key: str) -> str:
    if key not in MATERIALS:
        raise ValueError(f"unknown material '{key}'; choose from: {', '.join(MATERIALS)}")
    return key


MaterialKey = Annotated[
    str, AfterValidator(_known_material), Field(json_schema_extra={"enum": list(MATERIALS)})
]
MeshLevel = Literal["coarse", "medium", "fine"]


class CantileverBeam(BaseModel):
    """Rectangular beam clamped at one end with a point-like load at the free end.

    The classic first example of beam bending: compare the simulation with
    Euler-Bernoulli (plus shear) deflection and the bending stress M*c/I.
    """

    template: Literal["cantilever_beam"] = "cantilever_beam"
    length: float = Field(..., ge=10, le=10_000, description="mm")
    width: float = Field(..., ge=1, le=2_000, description="mm (along y)")
    height: float = Field(..., ge=1, le=2_000, description="mm (along z, bending direction)")
    load: float = Field(..., gt=0, le=1e7, description="tip load in N, pointing down")
    material: MaterialKey = "steel"
    mesh: MeshLevel = "medium"

    @model_validator(mode="after")
    def _is_a_beam(self) -> CantileverBeam:
        if self.length < 2 * max(self.width, self.height):
            raise ValueError(
                f"length {self.length:g} mm is under twice the cross-section size; "
                "this is a block, not a beam. Use length >= 2x the larger of width and height."
            )
        if self.length > 100 * min(self.width, self.height):
            raise ValueError(
                "length over 100x the smallest cross-section dimension: a beam this "
                "slender would need a very large 3D mesh. Use a thicker section or a shorter beam."
            )
        if max(self.width, self.height) > 20 * min(self.width, self.height):
            raise ValueError("cross-section sides differ by more than 20x: model it as a plate.")
        return self


class PlateWithHole(BaseModel):
    """Flat plate with a central hole pulled in tension.

    The classic stress concentration example: compare the peak stress at the
    hole edge with Kt times the nominal net-section stress.
    """

    template: Literal["plate_with_hole"] = "plate_with_hole"
    length: float = Field(..., ge=10, le=10_000, description="mm (along x, load direction)")
    width: float = Field(..., ge=5, le=5_000, description="mm (along y)")
    thickness: float = Field(..., ge=0.5, le=500, description="mm (along z)")
    hole_diameter: float = Field(..., gt=0, description="mm")
    load: float = Field(..., gt=0, le=1e8, description="total tensile force in N")
    material: MaterialKey = "steel"
    mesh: MeshLevel = "medium"

    @model_validator(mode="after")
    def _geometry(self) -> PlateWithHole:
        ratio = self.hole_diameter / self.width
        if not 0.05 <= ratio <= 0.65:
            raise ValueError(
                f"hole diameter / width = {ratio:.2f}; the Kt formula used for the hand "
                "calculation holds for 0.05 to 0.65."
            )
        if self.length < 2 * self.width:
            raise ValueError(
                "length must be at least 2x the width so the stress is uniform away "
                "from the hole."
            )
        if self.thickness > self.width / 2:
            raise ValueError("thickness must be under half the width for a plate.")
        if self.length > 10 * self.width:
            raise ValueError("length must be at most 10x the width (the hole effect is local).")
        if self.width > 100 * self.thickness:
            raise ValueError("width over 100x the thickness: the plate is too thin to mesh in 3D.")
        return self


class FaceLoad(BaseModel):
    faces: list[int] = Field(..., min_length=1)
    force: tuple[float, float, float] = Field(..., description="total force in N (x, y, z)")

    @model_validator(mode="after")
    def _nonzero(self) -> FaceLoad:
        if not any(self.force):
            raise ValueError("a load needs a non-zero force")
        return self


class CustomPart(BaseModel):
    """A part uploaded by the user (STL/STEP), with supports and loads on chosen faces.

    There is no textbook formula for an arbitrary shape, so the checks are force
    equilibrium and the mesh convergence study.
    """

    template: Literal["custom_part"] = "custom_part"
    part_id: str = Field(..., pattern=r"^[0-9a-f]{16}$")
    units: Literal["mm", "cm", "m", "in"] = "mm"
    fixed_faces: list[int] = Field(..., min_length=1)
    loads: list[FaceLoad] = Field(..., min_length=1, max_length=10)
    material: MaterialKey = "pla"
    mesh: MeshLevel = "medium"

    @model_validator(mode="after")
    def _faces(self) -> CustomPart:
        loaded = {f for ld in self.loads for f in ld.faces}
        both = loaded & set(self.fixed_faces)
        if both:
            raise ValueError(f"face(s) {sorted(both)} are both fixed and loaded")
        return self

    @property
    def load(self) -> float:
        total = [sum(ld.force[i] for ld in self.loads) for i in range(3)]
        return sum(c * c for c in total) ** 0.5


StudySpec = Annotated[
    CantileverBeam | PlateWithHole | CustomPart, Field(discriminator="template")
]
# templates the AI can set up from text (they have hand calculations)
TEMPLATES: dict[str, type[BaseModel]] = {
    "cantilever_beam": CantileverBeam,
    "plate_with_hole": PlateWithHole,
}
_adapter: TypeAdapter = TypeAdapter(StudySpec)


def parse_spec(data: dict):
    return _adapter.validate_python(data)
