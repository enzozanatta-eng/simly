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
from .spec import TEMPLATES, parse_spec

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
