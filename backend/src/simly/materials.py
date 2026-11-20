"""Material library with mechanical, thermal and electrical properties.

Every material records where its numbers come from. Two kinds of source:

* Printed polymers: mechanical values are the manufacturer's technical data
  sheet, measured on 3D-printed specimens in two directions. X-Y is within a
  layer; Z is across layers (layer adhesion), usually the weak direction.
* Metals and generic plastics: handbook typical values for the stated
  condition (ASM / MatWeb typical data, EN 10025 for structural steel).

Thermal and electrical values of polymers are typical values for the base
resin; printed parts vary with infill, porosity and direction. Polymer
resistivity is given as an order of magnitude only, because it depends
strongly on humidity and grade.

Units: E and strengths in MPa, density kg/m^3, conductivity W/(m K),
specific heat J/(kg K), expansion 1e-6/K, temperatures degC, resistivity ohm m.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["metal", "printing_polymer", "engineering_polymer"]


class Material(BaseModel):
    key: str
    name: str
    category: Category
    condition: str = ""

    # mechanical
    youngs_modulus: float = Field(..., gt=0, description="MPa (X-Y for printed parts)")
    youngs_modulus_z: float | None = Field(None, description="MPa, across layers")
    poisson_ratio: float = Field(..., gt=0, lt=0.5)
    yield_strength: float | None = Field(None, description="MPa, 0.2% offset (metals)")
    tensile_strength: float = Field(..., gt=0, description="MPa (X-Y for printed parts)")
    tensile_strength_z: float | None = Field(None, description="MPa, across layers")
    elongation_pct: float | None = None
    density: float = Field(..., gt=0)

    # thermal
    thermal_conductivity: float | None = None
    specific_heat: float | None = None
    thermal_expansion: float | None = None
    max_service_temp: float | None = Field(
        None, description="degC; heat deflection temperature at 0.45 MPa for polymers"
    )

    # electrical
    resistivity: float | None = Field(None, description="ohm m (order of magnitude for polymers)")
    electrical: Literal["conductor", "insulator", "not_insulating"] = "insulator"

    source: str
    notes: str = ""

    @property
    def is_printed(self) -> bool:
        return self.category == "printing_polymer"

    @property
    def design_strength(self) -> float:
        """Strength used for the safety factor: yield for metals, tensile otherwise."""
        return self.yield_strength or self.tensile_strength

    @property
    def weakest_strength(self) -> float:
        """Conservative strength: across layers for printed parts."""
        return min(self.design_strength, self.tensile_strength_z or self.design_strength)


TDS = "manufacturer TDS, ISO 527 on printed specimens"
RESIN = "thermal/electrical: typical values for the base resin"
HANDBOOK = "ASM/MatWeb typical values"

_M = [
    # ------------------------------------------------------------------ printing
    Material(
        key="pla", name="PLA", category="printing_polymer", condition="Bambu Lab PLA Basic",
        youngs_modulus=2680, youngs_modulus_z=2160, poisson_ratio=0.36,
        tensile_strength=39, tensile_strength_z=35, elongation_pct=12.2, density=1260,
        thermal_conductivity=0.13, specific_heat=1800, thermal_expansion=68,
        max_service_temp=55, resistivity=1e13,
        source=f"Bambu Lab PLA Basic TDS V2 ({TDS}); {RESIN}",
        notes="Softens around 55-60 C: avoid hot cars and direct summer sun.",
    ),
    Material(
        key="pla_tough", name="PLA Tough", category="printing_polymer",
        condition="Bambu Lab PLA Tough",
        youngs_modulus=2330, youngs_modulus_z=2110, poisson_ratio=0.36,
        tensile_strength=44, tensile_strength_z=39, elongation_pct=8.2, density=1260,
        thermal_conductivity=0.13, specific_heat=1800, thermal_expansion=68,
        max_service_temp=55, resistivity=1e13,
        source=f"Bambu Lab PLA Tough TDS V1 ({TDS}); HDT 55 C at 0.45 MPa; {RESIN}",
    ),
    Material(
        key="petg", name="PETG", category="printing_polymer", condition="Bambu Lab PETG Basic",
        youngs_modulus=1460, youngs_modulus_z=1120, poisson_ratio=0.38,
        tensile_strength=48, tensile_strength_z=39, density=1270,
        thermal_conductivity=0.20, specific_heat=1200, thermal_expansion=60,
        max_service_temp=69, resistivity=1e13,
        source=f"Bambu Lab PETG Basic TDS V2 ({TDS}); HDT 69 C at 0.45 MPa; {RESIN}",
    ),
    Material(
        key="petg_hf", name="PETG HF", category="printing_polymer",
        condition="Bambu Lab PETG HF",
        youngs_modulus=1810, youngs_modulus_z=1540, poisson_ratio=0.38,
        tensile_strength=34, tensile_strength_z=23, elongation_pct=8.6, density=1280,
        thermal_conductivity=0.20, specific_heat=1200, thermal_expansion=60,
        max_service_temp=69, resistivity=1e13,
        source=f"Bambu Lab PETG HF TDS V1 ({TDS}); density 1.28 g/cm3, HDT 69 C; {RESIN}",
    ),
    Material(
        key="abs", name="ABS", category="printing_polymer", condition="Polymaker PolyLite ABS",
        youngs_modulus=2247, youngs_modulus_z=2081, poisson_ratio=0.35,
        tensile_strength=33.4, tensile_strength_z=29.7, elongation_pct=17.9, density=1050,
        thermal_conductivity=0.17, specific_heat=1400, thermal_expansion=90,
        max_service_temp=100, resistivity=1e13,
        source=f"Polymaker PolyLite ABS TDS V5.4 ({TDS}); HDT 100 C at 0.45 MPa; {RESIN}",
    ),
    Material(
        key="asa", name="ASA", category="printing_polymer", condition="Polymaker PolyLite ASA",
        youngs_modulus=2379, youngs_modulus_z=1965, poisson_ratio=0.35,
        tensile_strength=43.8, tensile_strength_z=32.0, elongation_pct=6.7, density=1070,
        thermal_conductivity=0.17, specific_heat=1300, thermal_expansion=95,
        max_service_temp=95, resistivity=1e13,
        source=f"Polymaker PolyLite ASA TDS V5.1 ({TDS}); {RESIN}",
        notes="UV and weather resistant: the usual choice for outdoor parts.",
    ),
    Material(
        key="pc", name="Polycarbonate (PC)", category="printing_polymer",
        condition="Bambu Lab PC",
        youngs_modulus=2110, youngs_modulus_z=1450, poisson_ratio=0.37,
        tensile_strength=62, tensile_strength_z=56, density=1200,
        thermal_conductivity=0.20, specific_heat=1200, thermal_expansion=68,
        max_service_temp=111, resistivity=1e14,
        source=f"Bambu Lab PC TDS V2 ({TDS}); HDT from Polymaker PolyLite PC TDS; {RESIN}",
    ),
    Material(
        key="tpu_95a", name="TPU 95A (flexible)", category="printing_polymer",
        condition="Bambu Lab TPU 95A",
        youngs_modulus=9.2, youngs_modulus_z=7.8, poisson_ratio=0.48,
        tensile_strength=29.6, tensile_strength_z=23.2, elongation_pct=700, density=1220,
        thermal_conductivity=0.25, specific_heat=1800, thermal_expansion=150,
        resistivity=1e11,
        source=f"Bambu Lab TPU 95A TDS V3 ({TDS}); conductivity 0.26 W/mK measured on "
        f"printed TPU (Polymers/PMC 10707084); {RESIN}",
        notes="Rubber-like: a linear analysis is only meaningful for small strains. "
        "Simly flags results above 5% strain.",
    ),
    Material(
        key="pla_cf", name="PLA-CF (carbon fibre)", category="printing_polymer",
        condition="Bambu Lab PLA-CF",
        youngs_modulus=2790, youngs_modulus_z=2160, poisson_ratio=0.35,
        tensile_strength=38, tensile_strength_z=26, elongation_pct=8.4, density=1220,
        thermal_conductivity=0.20, specific_heat=1700, thermal_expansion=40,
        max_service_temp=55, electrical="not_insulating",
        source=f"Bambu Lab PLA-CF TDS V2/V3 ({TDS}); {RESIN}",
        notes="Carbon fibre makes it stiffer but weaker across layers, and it should not "
        "be relied on as an electrical insulator.",
    ),
    Material(
        key="petg_cf", name="PETG-CF (carbon fibre)", category="printing_polymer",
        condition="Bambu Lab PETG-CF",
        youngs_modulus=2460, youngs_modulus_z=1340, poisson_ratio=0.37,
        tensile_strength=59, tensile_strength_z=38, elongation_pct=10.4, density=1250,
        thermal_conductivity=0.25, specific_heat=1200, thermal_expansion=40,
        max_service_temp=74, electrical="not_insulating",
        source=f"Bambu Lab PETG-CF TDS V2 ({TDS}); HDT 74 C at 0.45 MPa; {RESIN}",
    ),
    Material(
        key="pet_cf", name="PET-CF (carbon fibre)", category="printing_polymer",
        condition="Bambu Lab PET-CF, dry",
        youngs_modulus=4730, youngs_modulus_z=2160, poisson_ratio=0.37,
        tensile_strength=74, tensile_strength_z=35, elongation_pct=4.5, density=1290,
        thermal_conductivity=0.25, specific_heat=1200, thermal_expansion=35,
        electrical="not_insulating",
        source=f"Bambu Lab PET-CF TDS V3 ({TDS}); {RESIN}",
    ),
    Material(
        key="abs_gf", name="ABS-GF (glass fibre)", category="printing_polymer",
        condition="Bambu Lab ABS-GF, annealed",
        youngs_modulus=3160, youngs_modulus_z=2250, poisson_ratio=0.35,
        tensile_strength=36, tensile_strength_z=29, density=1080,
        thermal_conductivity=0.20, specific_heat=1300, thermal_expansion=60,
        max_service_temp=99, resistivity=1e13,
        source=f"Bambu Lab ABS-GF TDS V1 ({TDS}); HDT 99 C at 0.45 MPa; {RESIN}",
    ),
    Material(
        key="paht_cf", name="Nylon PAHT-CF (carbon fibre)", category="printing_polymer",
        condition="Bambu Lab PAHT-CF, dry",
        youngs_modulus=3860, youngs_modulus_z=2180, poisson_ratio=0.38,
        tensile_strength=92, tensile_strength_z=47, elongation_pct=8.4, density=1200,
        thermal_conductivity=0.30, specific_heat=1600, thermal_expansion=30,
        max_service_temp=194, electrical="not_insulating",
        source=f"Bambu Lab PAHT-CF TDS V2 ({TDS}); HDT 194 C at 0.45 MPa; {RESIN}",
        notes="Values are for dry parts; nylon absorbs moisture and loses stiffness.",
    ),
    # ------------------------------------------------------------------ metals
    Material(
        key="steel_s235", name="Structural steel S235", category="metal",
        condition="EN 10025-2, t <= 16 mm",
        youngs_modulus=210_000, poisson_ratio=0.30, yield_strength=235,
        tensile_strength=360, elongation_pct=26, density=7850,
        thermal_conductivity=50, specific_heat=460, thermal_expansion=12,
        max_service_temp=400, resistivity=1.6e-7, electrical="conductor",
        source="EN 10025-2 minimum strengths; EN 1993-1-1 elastic constants; "
        f"thermal/electrical {HANDBOOK} for carbon steel",
    ),
    Material(
        key="steel", name="Structural steel S275", category="metal",
        condition="EN 10025-2, t <= 16 mm",
        youngs_modulus=210_000, poisson_ratio=0.30, yield_strength=275,
        tensile_strength=410, elongation_pct=23, density=7850,
        thermal_conductivity=50, specific_heat=460, thermal_expansion=12,
        max_service_temp=400, resistivity=1.6e-7, electrical="conductor",
        source="EN 10025-2 minimum strengths; EN 1993-1-1 elastic constants; "
        f"thermal/electrical {HANDBOOK} for carbon steel",
    ),
    Material(
        key="steel_s355", name="Structural steel S355", category="metal",
        condition="EN 10025-2, t <= 16 mm",
        youngs_modulus=210_000, poisson_ratio=0.30, yield_strength=355,
        tensile_strength=470, elongation_pct=22, density=7850,
        thermal_conductivity=50, specific_heat=460, thermal_expansion=12,
        max_service_temp=400, resistivity=1.6e-7, electrical="conductor",
        source="EN 10025-2 minimum strengths; EN 1993-1-1 elastic constants; "
        f"thermal/electrical {HANDBOOK} for carbon steel",
    ),
    Material(
        key="steel_1045", name="Steel AISI 1045", category="metal", condition="cold drawn",
        youngs_modulus=205_000, poisson_ratio=0.29, yield_strength=530,
        tensile_strength=625, elongation_pct=12, density=7870,
        thermal_conductivity=49.8, specific_heat=486, thermal_expansion=11.2,
        resistivity=1.62e-7, electrical="conductor", source=HANDBOOK,
    ),
    Material(
        key="steel_4140", name="Steel AISI 4140", category="metal", condition="annealed",
        youngs_modulus=205_000, poisson_ratio=0.29, yield_strength=415,
        tensile_strength=655, elongation_pct=25.7, density=7850,
        thermal_conductivity=42.6, specific_heat=473, thermal_expansion=12.2,
        resistivity=2.2e-7, electrical="conductor", source=HANDBOOK,
    ),
    Material(
        key="stainless_steel", name="Stainless steel 304", category="metal",
        condition="annealed",
        youngs_modulus=193_000, poisson_ratio=0.29, yield_strength=215,
        tensile_strength=505, elongation_pct=70, density=8000,
        thermal_conductivity=16.2, specific_heat=500, thermal_expansion=17.3,
        max_service_temp=870, resistivity=7.2e-7, electrical="conductor", source=HANDBOOK,
    ),
    Material(
        key="stainless_316", name="Stainless steel 316", category="metal", condition="annealed",
        youngs_modulus=193_000, poisson_ratio=0.30, yield_strength=205,
        tensile_strength=515, elongation_pct=60, density=8000,
        thermal_conductivity=16.3, specific_heat=500, thermal_expansion=16.0,
        resistivity=7.4e-7, electrical="conductor", source=HANDBOOK,
    ),
    Material(
        key="aluminium", name="Aluminium 6061-T6", category="metal", condition="T6",
        youngs_modulus=68_900, poisson_ratio=0.33, yield_strength=276,
        tensile_strength=310, elongation_pct=12, density=2700,
        thermal_conductivity=167, specific_heat=896, thermal_expansion=23.6,
        max_service_temp=150, resistivity=3.99e-8, electrical="conductor", source=HANDBOOK,
    ),
    Material(
        key="aluminium_6063", name="Aluminium 6063-T5", category="metal", condition="T5",
        youngs_modulus=68_900, poisson_ratio=0.33, yield_strength=145,
        tensile_strength=186, elongation_pct=12, density=2700,
        thermal_conductivity=209, specific_heat=900, thermal_expansion=23.4,
        resistivity=3.5e-8, electrical="conductor", source=HANDBOOK,
        notes="The common extrusion alloy (profiles, frames).",
    ),
    Material(
        key="aluminium_7075", name="Aluminium 7075-T6", category="metal", condition="T6",
        youngs_modulus=71_700, poisson_ratio=0.33, yield_strength=503,
        tensile_strength=572, elongation_pct=11, density=2810,
        thermal_conductivity=130, specific_heat=960, thermal_expansion=23.6,
        resistivity=5.15e-8, electrical="conductor", source=HANDBOOK,
    ),
    Material(
        key="aluminium_5052", name="Aluminium 5052-H32", category="metal", condition="H32",
        youngs_modulus=70_300, poisson_ratio=0.33, yield_strength=193,
        tensile_strength=228, elongation_pct=12, density=2680,
        thermal_conductivity=138, specific_heat=880, thermal_expansion=23.8,
        resistivity=4.99e-8, electrical="conductor", source=HANDBOOK,
        notes="Sheet-metal alloy with good formability and corrosion resistance.",
    ),
    Material(
        key="titanium", name="Titanium Ti-6Al-4V", category="metal", condition="annealed",
        youngs_modulus=113_800, poisson_ratio=0.342, yield_strength=880,
        tensile_strength=950, elongation_pct=14, density=4430,
        thermal_conductivity=6.7, specific_heat=526, thermal_expansion=8.6,
        max_service_temp=400, resistivity=1.78e-6, electrical="conductor", source=HANDBOOK,
    ),
    Material(
        key="copper", name="Copper C11000", category="metal", condition="annealed",
        youngs_modulus=115_000, poisson_ratio=0.31, yield_strength=69,
        tensile_strength=220, elongation_pct=50, density=8890,
        thermal_conductivity=388, specific_heat=385, thermal_expansion=17.0,
        resistivity=1.71e-8, electrical="conductor", source=HANDBOOK,
    ),
    Material(
        key="brass", name="Brass C36000 (free-cutting)", category="metal",
        condition="half hard",
        youngs_modulus=97_000, poisson_ratio=0.31, yield_strength=310,
        tensile_strength=385, elongation_pct=25, density=8500,
        thermal_conductivity=115, specific_heat=380, thermal_expansion=20.5,
        resistivity=6.6e-8, electrical="conductor", source=HANDBOOK,
    ),
    # ------------------------------------------------------------------ plastics
    Material(
        key="pom", name="Acetal (POM, Delrin)", category="engineering_polymer",
        condition="homopolymer, moulded",
        youngs_modulus=3100, poisson_ratio=0.35, tensile_strength=70, elongation_pct=25,
        density=1420, thermal_conductivity=0.31, specific_heat=1470, thermal_expansion=110,
        max_service_temp=90, resistivity=1e13, source=HANDBOOK,
    ),
    Material(
        key="pmma", name="Acrylic (PMMA)", category="engineering_polymer", condition="cast sheet",
        youngs_modulus=3200, poisson_ratio=0.37, tensile_strength=70, elongation_pct=4,
        density=1190, thermal_conductivity=0.19, specific_heat=1470, thermal_expansion=70,
        max_service_temp=80, resistivity=1e13, source=HANDBOOK,
        notes="Brittle: it cracks rather than yields, so keep a larger safety factor.",
    ),
    Material(
        key="hdpe", name="HDPE", category="engineering_polymer", condition="moulded",
        youngs_modulus=1000, poisson_ratio=0.42, tensile_strength=26, elongation_pct=500,
        density=950, thermal_conductivity=0.48, specific_heat=1900, thermal_expansion=120,
        max_service_temp=75, resistivity=1e14, source=HANDBOOK,
    ),
]

MATERIALS: dict[str, Material] = {m.key: m for m in _M}
