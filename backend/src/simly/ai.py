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
You get a list of the part's faces and edges (ids, sizes, positions, outward
normals, all in mm) and the user's description of how the part is held and
loaded. Decide which faces/edges/points are supported and which are loaded.

Rules:
- Supports: "fixed" = dofs [1,2,3]. A face resting on a surface but free to slide
  holds only the direction of its normal (e.g. dofs [3] for a face with normal +/-Z).
  The part must be held well enough not to move as a rigid body.
- Screws or bolts through a hole: support the hole's cylindrical face(s).
- Loads: kind "force" (vector in N), "moment" (vector in N mm, right-hand rule,
  on a face or edge), or "pressure" (MPa, on faces, pushing into them).
- A mass of m kg resting or hanging gives a force of m * 9.81 N downwards (-Z),
  unless the user says the part is oriented differently.
- Loads spread over a face unless the user describes a point or an edge.
- Point selections use coordinates in mm on the part's surface.
- Materials (use the key): {"; ".join(f"{k} = {m.name}" for k, m in MATERIALS.items())}.
  For "3D printed" with no filament named use pla.
- Explain your choices briefly in "rationale", naming the faces you used.
- If a proposal is rejected, read the reason and fix it.
"""


def part_summary(info: dict, max_faces: int = 150, max_edges: int = 250) -> str:
    """Compact text description of a part for the model."""
    def v(x):
        return "(" + ", ".join(f"{c:.4g}" for c in x) + ")"

    lines = [f"Bounding box (mm): min {v(info['bbox_mm']['min'])}, max {v(info['bbox_mm']['max'])}"]
    lines.append("Faces: id | area mm2 | centroid | outward normal")
    for f in sorted(info["faces"], key=lambda f: -f["area_mm2"])[:max_faces]:
        lines.append(f"  {f['id']} | {f['area_mm2']:.4g} | {v(f['centroid'])} | {v(f['normal'])}")
    lines.append("Edges: id | length mm | midpoint | direction (straight edges) | faces it joins")
    for e in sorted(info["edges"], key=lambda e: -e["length_mm"])[:max_edges]:
        d = v(e["direction"]) if e["direction"] else "curved"
        mid = v(e["midpoint"])
        lines.append(f"  {e['id']} | {e['length_mm']:.4g} | {mid} | {d} | {e['faces']}")
    return "\n".join(lines)


def _part_tool() -> Tool:
    schema = {
        "type": "object",
        "properties": {
            "supports": {"type": "array", "items": inline_refs(Support.model_json_schema())},
            "loads": {"type": "array", "items": inline_refs(Load.model_json_schema())},
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
              max_attempts: int = 3) -> PartPlan:
    face_ids = {f["id"] for f in info["faces"]}
    edge_ids = {e["id"] for e in info["edges"]}
    history: list[Turn] = [UserText(f"{part_summary(info)}\n\nUser: {request}")]
    attempts: list[dict] = []
    for _ in range(max_attempts):
        call = client.call(PART_PROMPT, history, [PART_TOOL, DECLINE])
        if call.name == DECLINE.name:
            raise Declined(call.input.get("reason", ""), call.input.get("closest_template"))
        try:
            spec = CustomPart(part_id=info["part_id"], units=info["units"], mesh=mesh,
                              supports=call.input.get("supports", []),
                              loads=call.input.get("loads", []),
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
