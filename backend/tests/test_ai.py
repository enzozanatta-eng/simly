import pytest

from simly.ai import PROPOSE_TOOLS, Declined, NoValidSpec, explain_results, plan_study
from simly.llm import ToolCall, ToolResult


class ScriptedLLM:
    def __init__(self, *calls):
        self.calls, self.seen = list(calls), []

    def call(self, system, history, tools):
        self.seen.append((system, list(history), [t.name for t in tools]))
        return self.calls.pop(0)


def test_one_tool_per_template_without_template_field():
    assert {t.name for t in PROPOSE_TOOLS} == {"propose_cantilever_beam", "propose_plate_with_hole"}
    for t in PROPOSE_TOOLS:
        assert "template" not in t.input_schema["properties"]


def test_plan_fixes_rejected_proposal():
    llm = ScriptedLLM(
        ToolCall("a", "propose_cantilever_beam",
                 {"length": 100, "width": 80, "height": 80, "load": 50}),  # a block
        ToolCall("b", "propose_cantilever_beam",
                 {"length": 1000, "width": 80, "height": 80, "load": 50}),
    )
    r = plan_study("steel diving board", llm)
    assert r.spec.length == 1000
    assert r.attempts[0]["error"] and "not a beam" in r.attempts[0]["error"]
    feedback = llm.seen[1][1][-1]
    assert isinstance(feedback, ToolResult) and feedback.is_error


def test_plan_declines_fluids():
    llm = ScriptedLLM(ToolCall("a", "cannot_simulate", {"reason": "airflow is not structural"}))
    with pytest.raises(Declined, match="airflow"):
        plan_study("air over a wing", llm)


def test_plan_gives_up():
    bad = {"length": 50, "width": 80, "height": 80, "load": 50}
    llm = ScriptedLLM(*[ToolCall(str(i), "propose_cantilever_beam", bad) for i in range(3)])
    with pytest.raises(NoValidSpec):
        plan_study("x", llm)


def test_explain_passes_only_computed_facts():
    llm = ScriptedLLM(ToolCall("e", "write_explanation", {"explanation": "The beam bends."}))
    result = {"spec": {}, "mesh": {}, "summary": {"max_von_mises_MPa": 19.07},
              "comparisons": [], "note": "", "display": {"positions": [1, 2, 3]}}
    assert explain_results("viga", result, llm) == "The beam bends."
    message = llm.seen[0][1][0].text
    assert "19.07" in message and "positions" not in message  # no mesh dump to the model
