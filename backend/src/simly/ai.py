"""AI features: plain-language request -> study spec, and results -> explanation.

The model proposes, the validators dispose: every proposed spec goes through
the same pydantic validation as a hand-made one, and rejections go back to the
model with the reason. Explanations are written from the computed numbers
only; the model is told not to introduce values of its own.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from pydantic import ValidationError

from .llm import LLMClient, LLMError, Tool, ToolResult, Turn, UserText, inline_refs
from .materials import MATERIALS
from .spec import TEMPLATES, CustomPart, Load, Support, parse_spec

PLAN_PROMPT = f"""\
You set up structural simulations for Simly, a teaching tool. A teacher or
student describes what they want to show; you pick the matching template and
fill in its parameters.

Templates (one propose_<template> tool each):
- cantilever_beam: rectangular beam clamped at one end, load at the free end.
  Use for bending, deflection, beams, shelves, diving boards, cantilevers.
- plate_with_hole: plate with a central hole pulled in tension. Use for stress
  concentration, holes, notches, Kt, bolted plates in tension.

Units: millimetres and newtons. Convert: 1 m = 1000 mm, 1 kN = 1000 N,
1 kgf = 9.81 N (a mass of m kg hanging means m * 9.81 N).
Materials (use the key): {"; ".join(f"{k} = {m.name}" for k, m in MATERIALS.items())}.
Default to steel when not stated. For 3D-printed parts pick the filament named;
if the user only says "3D printed", use pla.
When a dimension is not given, choose a realistic textbook value.
Use mesh "medium" unless the user asks for speed (coarse) or accuracy (fine).
If no template fits (fluids, heat, vibration, assemblies, other shapes), call
cannot_simulate with the reason and the closest template.
If a proposal is rejected, read the reason and fix it.
"""

EXPLAIN_PROMPT = """\
You are a friendly engineering teacher explaining a simulation result to a class.
Use ONLY the numbers given in the results JSON; do not invent or estimate values.
Write in the same language as the user's original request (default English).
Structure, in short plain paragraphs:
1. What was simulated and what the colours show.
2. The key numbers (peak stress, deflection, safety factor) and what they mean.
3. How the simulation compares with the hand calculation, and why they agree or differ.
4. One intuition the students should take away.
Keep it under 220 words. No markdown headings.
"""


def _propose_tool(name: str) -> Tool:
    model = TEMPLATES[name]
    schema = inline_refs(model.model_json_schema())
    schema["properties"].pop("template", None)
    return Tool(f"propose_{name}", f"Propose a {name} study. {model.__doc__.strip()}", schema)


PROPOSE_TOOLS = [_propose_tool(n) for n in TEMPLATES]
DECLINE = Tool(
    "cannot_simulate",
    "Decline a request that no template can represent.",
    {"type": "object",
     "properties": {"reason": {"type": "string"}, "closest_template": {"type": "string"}},
     "required": ["reason"]},
)
EXPLAIN = Tool(
    "write_explanation",
    "Return the classroom explanation of the results.",
    {"type": "object", "properties": {"explanation": {"type": "string"}},
     "required": ["explanation"]},
)


class Declined(Exception):
    def __init__(self, reason: str, closest: str | None = None):
        super().__init__(reason)
        self.reason, self.closest = reason, closest


class NoValidSpec(Exception):
    pass


@dataclass
class PlanResult:
    spec: object
    attempts: list[dict] = field(default_factory=list)  # {"proposal", "error"}


def _explain_error(e: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(map(str, err['loc'])) or 'spec'}: {err['msg']}" for err in e.errors()
    )


def plan_study(request: str, client: LLMClient, max_attempts: int = 3) -> PlanResult:
    history: list[Turn] = [UserText(request)]
    attempts: list[dict] = []
    for _ in range(max_attempts):
        call = client.call(PLAN_PROMPT, history, [*PROPOSE_TOOLS, DECLINE])
        if call.name == DECLINE.name:
            raise Declined(call.input.get("reason", ""), call.input.get("closest_template"))
        template = call.name.removeprefix("propose_")
        if template not in TEMPLATES:
            raise LLMError(f"unexpected tool '{call.name}'")
        try:
            spec = parse_spec({**call.input, "template": template})
        except ValidationError as e:
            reason = _explain_error(e)
            attempts.append({"proposal": call.input, "error": reason})
            history += [call, ToolResult(call.id, f"Rejected by the validator: {reason}", True)]
            continue
        attempts.append({"proposal": call.input, "error": None})
        return PlanResult(spec, attempts)
    raise NoValidSpec(
        f"no valid study after {max_attempts} attempts; last error: "
        f"{attempts[-1]['error'] if attempts else '-'}"
    )


def explain_results(request: str, result: dict, client: LLMClient) -> str:
    facts = {k: result[k] for k in ("spec", "mesh", "summary", "comparisons", "note")}
    message = (
        f"Original request: {request or '(set up by hand)'}\n\n"
        f"Results JSON:\n{json.dumps(facts, indent=1)}"
    )
    call = client.call(EXPLAIN_PROMPT, [UserText(message)], [EXPLAIN])
    text = call.input.get("explanation", "").strip()
    if not text:
        raise LLMError("empty explanation")
    return text


# ---------------------------------------------------------------- uploaded parts

PART_PROMPT = f"""\
You set up a structural simulation on a part the user uploaded to Simly.
You get the part's faces (type, size, position, outward normal, neighbours),
its edges, the direction of gravity in the part's coordinates, and the user's
description of how the part is held and loaded. Think about how the part sits
in the real world before choosing faces.

How to read the part:
- "hole" faces are cylindrical holes (diameter and axis given). A through hole
  opens onto two neighbouring plane faces: one is where the screw head or nut
  sits, the other is pressed against whatever the part is screwed to.
- The face pressed against a wall or floor faces AWAY from the rest of the part
  (its outward normal points to the wall). E.g. for an L-shaped shelf bracket the
  wall side of the vertical leg faces away from the horizontal shelf arm.

Supports (dofs: 1 = x, 2 = y, 3 = z):
- Bolted or screwed through a hole: support the hole face(s) as fixed [1,2,3],
  and support the plane face pressed against the wall in the direction of its
  normal only (contact: it cannot go into the wall). Never fix the face where
  the screw head sits, or faces far from the fastening.
- Clamped or glued: fix the clamped/glued faces.
- Resting on a floor or table: hold the resting face in the vertical direction
  only, plus enough small supports to stop sliding and spinning.
- The part must not be able to move as a rigid body.

Loads:
- kind "force" (vector in N), "moment" (vector in N mm, right-hand rule, on a
  face or edge) or "pressure" (MPa, faces only, pushing into them).
- A weight (a mass of m kg resting on or hanging from the part): give
  "weight_kg": m and NO vector. Simly turns it into m * 9.81 N along gravity
  itself, whatever way the part is oriented in the file. Put it on the face it
  rests on, spread over that face unless a point or edge is described.
- Never load a face you also support.
- A shelf, board, box or anything placed on the part rests on a large
  upward-facing face: use the "Upward-facing faces" list, normally the largest
  one on the arm that sticks out from the support, never the thin top edge of a
  vertical leg. Items hanging from the part load the downward-facing face or
  the hole they hang from.

Materials (use the key): {"; ".join(f"{k} = {m.name}" for k, m in MATERIALS.items())}.
For "3D printed" with no filament named use pla; if nothing is said, pla.

In "rationale" (in the user's language), say in plain words which faces you used
and why, describing them physically (e.g. "the hole", "the back of the vertical
leg against the wall", "the top of the shelf arm"), with their ids.
If a proposal is rejected, read the reason and fix it.
"""

G = 9.81
GRAVITY = {"-z": "-Z", "+z": "+Z", "-y": "-Y", "+y": "+Y", "-x": "-X", "+x": "+X"}


def part_summary(info: dict, gravity: str = "-z", max_faces: int = 150,
                 max_edges: int = 200) -> str:
    """Compact, physically labelled description of a part for the model."""
    def v(x):
        return "(" + ", ".join(f"{c:.4g}" for c in x) + ")"

    lo, hi = info["bbox_mm"]["min"], info["bbox_mm"]["max"]
    down = gravity_vector(gravity)

    def facing(sign: float) -> list[str]:
        planes = [f for f in info["faces"] if f.get("kind", "plane") == "plane"
                  and sum(f["normal"][i] * down[i] for i in range(3)) * sign < -0.9]
        planes.sort(key=lambda f: -f["area_mm2"])
        return [f"face {f['id']} ({f['area_mm2']:.4g} mm2, centre {v(f['centroid'])})"
                for f in planes]

    holes = [f for f in info["faces"] if f.get("kind") == "hole"]
    lines = [
        f"Gravity (down) in the part's coordinates: {GRAVITY.get(gravity, '-Z')}",
        f"Bounding box (mm): min {v(lo)}, max {v(hi)}",
        "Upward-facing faces (where objects can rest), largest first: "
        + ("; ".join(facing(1.0)) or "none"),
        "Downward-facing faces, largest first: " + ("; ".join(facing(-1.0)) or "none"),
        "Holes: " + ("; ".join(
            f"face {h['id']} (diameter {h['diameter_mm']:.3g} mm, axis {v(h['axis'])}, "
            f"opens onto faces {h.get('neighbours', [])})" for h in holes) or "none"),
        "Faces:",
    ]
    for f in sorted(info["faces"], key=lambda f: -f["area_mm2"])[:max_faces]:
        kind = f.get("kind", "plane")
        if kind in ("hole", "cylinder"):
            shape = (f"{kind} diameter {f['diameter_mm']:.3g} mm, length {f['length_mm']:.3g} mm, "
                     f"axis {v(f['axis'])} through {v(f['axis_point'])}")
        elif kind == "plane":
            shape = f"plane, outward normal {v(f['normal'])}"
        else:
            shape = "curved surface"
        lines.append(f"  face {f['id']}: {shape}; area {f['area_mm2']:.4g} mm2; centre "
                     f"{v(f['centroid'])}; neighbours {f.get('neighbours', [])}")
    lines.append("Edges (id, length mm, midpoint, direction if straight, faces it joins):")
    for e in sorted(info["edges"], key=lambda e: -e["length_mm"])[:max_edges]:
        d = v(e["direction"]) if e["direction"] else "curved"
        mid = v(e["midpoint"])
        lines.append(f"  edge {e['id']}: {e['length_mm']:.4g}, {mid}, {d}, {e['faces']}")
    return "\n".join(lines)


def _load_schema() -> dict:
    schema = inline_refs(Load.model_json_schema())
    schema = {**schema, "properties": {**schema["properties"], "weight_kg": {
        "type": "number", "exclusiveMinimum": 0,
        "description": "mass in kg whose weight acts along gravity; use instead of vector"}}}
    return schema


def gravity_vector(gravity: str) -> list[float]:
    """Unit vector pointing down, e.g. "-z" -> [0, 0, -1]."""
    if len(gravity) != 2 or gravity[0] not in "+-" or gravity[1] not in "xyz":
        raise ValueError(f"bad gravity direction {gravity!r}")
    down = [0.0, 0.0, 0.0]
    down["xyz".index(gravity[1])] = -1.0 if gravity[0] == "-" else 1.0
    return down


def resolve_weights(loads: list[dict], gravity: str) -> list[dict]:
    """Turn {"weight_kg": m} loads into forces along gravity, so the model never
    has to work out the sign of "down" in the file's coordinates."""
    down = gravity_vector(gravity)
    out = []
    for ld in loads:
        ld = dict(ld)
        kg = ld.pop("weight_kg", None)
        if kg is not None:
            if not isinstance(kg, (int, float)) or kg <= 0:
                raise ValueError("weight_kg must be a positive number")
            ld["kind"] = "force"
            ld.pop("pressure", None)
            ld["vector"] = [c * kg * G for c in down]
        out.append(ld)
    return out


def _part_tool() -> Tool:
    schema = {
        "type": "object",
        "properties": {
            "supports": {"type": "array", "items": inline_refs(Support.model_json_schema())},
            "loads": {"type": "array", "items": _load_schema()},
            "material": {"type": "string", "enum": list(MATERIALS)},
            "rationale": {"type": "string"},
        },
        "required": ["supports", "loads", "material", "rationale"],
    }
    return Tool("propose_part_setup", "Supports, loads and material for the uploaded part.", schema)


PART_TOOL = _part_tool()


@dataclass
class PartPlan:
    spec: CustomPart
    rationale: str
    attempts: list[dict] = field(default_factory=list)


def plan_part(request: str, info: dict, client: LLMClient, mesh: str = "medium",
              gravity: str = "-z", max_attempts: int = 3) -> PartPlan:
    face_ids = {f["id"] for f in info["faces"]}
    edge_ids = {e["id"] for e in info["edges"]}
    history: list[Turn] = [UserText(f"{part_summary(info, gravity)}\n\nUser: {request}")]
    attempts: list[dict] = []
    for _ in range(max_attempts):
        call = client.call(PART_PROMPT, history, [PART_TOOL, DECLINE])
        if call.name == DECLINE.name:
            raise Declined(call.input.get("reason", ""), call.input.get("closest_template"))
        try:
            spec = CustomPart(part_id=info["part_id"], units=info["units"], mesh=mesh,
                              supports=call.input.get("supports", []),
                              loads=resolve_weights(call.input.get("loads", []), gravity),
                              material=call.input.get("material", "pla"))
            unknown = [
                f"{sel.entity} {i}" for sel in [*spec.supports, *spec.loads] for i in sel.ids
                if (sel.entity == "face" and i not in face_ids)
                or (sel.entity == "edge" and i not in edge_ids)
            ]
            if unknown:
                raise ValueError(f"these ids do not exist on the part: {', '.join(unknown)}")
        except (ValidationError, ValueError) as e:
            reason = _explain_error(e) if isinstance(e, ValidationError) else str(e)
            attempts.append({"proposal": call.input, "error": reason})
            history += [call, ToolResult(call.id, f"Rejected: {reason}", True)]
            continue
        attempts.append({"proposal": call.input, "error": None})
        return PartPlan(spec, call.input.get("rationale", ""), attempts)
    raise NoValidSpec(f"no valid setup after {max_attempts} attempts; last error: "
                      f"{attempts[-1]['error'] if attempts else '-'}")
