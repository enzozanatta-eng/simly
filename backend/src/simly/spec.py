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


Vec3 = tuple[float, float, float]


class Selection(BaseModel):
    """Where a support or load acts: faces, edges (by id) or one point (coordinates in mm)."""

    entity: Literal["face", "edge", "point"] = "face"
    ids: list[int] = Field(default_factory=list, description="face or edge ids")
    point: Vec3 | None = Field(None, description="mm, for entity 'point'")

    @model_validator(mode="after")
    def _target(self):
        if self.entity == "point":
            if self.point is None:
                raise ValueError("a point selection needs coordinates")
        elif not self.ids:
            raise ValueError(f"select at least one {self.entity}")
        return self

    def key(self) -> tuple:
        return (self.entity, tuple(sorted(self.ids)), self.point)


class Support(Selection):
    """Held in the directions listed in ``dofs`` (1 = x, 2 = y, 3 = z); all three = fixed."""

    dofs: list[Literal[1, 2, 3]] = Field(default_factory=lambda: [1, 2, 3], min_length=1)


class Load(Selection):
    """A force (N), a moment (N mm, right-hand rule) or a pressure (MPa, into the face)."""

    kind: Literal["force", "moment", "pressure"] = "force"
    vector: Vec3 | None = Field(None, description="force in N or moment in N mm")
    pressure: float | None = Field(None, description="MPa, pushes into the selected faces")

    @model_validator(mode="after")
    def _value(self):
        if self.kind == "pressure":
            if self.entity != "face" or not self.pressure:
                raise ValueError("a pressure acts on faces and needs a non-zero value in MPa")
        else:
            if self.vector is None or not any(self.vector):
                raise ValueError(f"a {self.kind} needs a non-zero vector")
            if self.kind == "moment" and self.entity == "point":
                raise ValueError("a moment needs a face or an edge to act on; solid "
                                 "elements have no rotation at a single point")
        return self


class CustomPart(BaseModel):
    """A part uploaded by the user (STL/STEP), with supports and loads on chosen
    faces, edges or points.

    There is no textbook formula for an arbitrary shape, so the checks are force
    equilibrium and the mesh convergence study.
    """

    template: Literal["custom_part"] = "custom_part"
    part_id: str = Field(..., pattern=r"^[0-9a-f]{16}$")
    units: Literal["mm", "cm", "m", "in"] = "mm"
    supports: list[Support] = Field(..., min_length=1, max_length=20)
    loads: list[Load] = Field(..., min_length=1, max_length=20)
    material: MaterialKey = "pla"
    mesh: MeshLevel = "medium"

    @model_validator(mode="after")
    def _distinct(self):
        held = {(s.entity, i) for s in self.supports for i in s.ids}
        loaded = {(ld.entity, i) for ld in self.loads for i in ld.ids}
        both = sorted(held & loaded)
        if both:
            names = ", ".join(f"{e} {i}" for e, i in both)
            raise ValueError(f"{names} is both supported and loaded")
        return self

    @property
    def load(self) -> float:
        total = [sum(ld.vector[i] for ld in self.loads if ld.kind == "force") for i in range(3)]
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
