"""Tester Agent: generate tests -> run pytest -> classify failures -> fix tests.

Uses the shared devcrew.llm.chat_json interface supplied by the team leader.
No extra API keys or LangGraph setup are needed inside this module.
"""
import json

from devcrew.schemas import (
    AgentMessage, Attribution, AttributionDraft, FailureVerdict, TesterOutput,
)
from devcrew.tools.sandbox import run_pytest


def _ask(system, data, schema):
    # Group A provides llm.py; import here so we can unit-test without a real LLM.
    from devcrew.llm import chat_json
    return chat_json(system, json.dumps(data, ensure_ascii=False), schema, agent="tester")


def _message(node, kind, summary, state, payload=None, tokens=0):
    return AgentMessage(
        node=node, sender="sandbox" if node == "run_tests" else "tester",
        receivers={"tester_write": ["sandbox"], "run_tests": ["tester"],
                   "attribute": ["coder", "tester", "planner"],
                   "tester_fix": ["sandbox"]}[node],
        type=kind, summary=summary, payload=payload or {},
        tokens=tokens, iteration=state["test_iters"],
    )


def tester_write_node(state):
    """Only the Planner's plan is visible to test generation; NEVER pass code."""
    prompt = (
        "You are an independent Tester. Create a complete pytest test_solution.py "
        "using ONLY this plan. Cover every AC-N and EC-N, plus two extra edge cases. "
        "Name tests test_acN_*, test_ecN_*, or test_exN_*. "
        "Calculate expected results from the specification, not from code. "
        "Return complete files as TesterOutput."
    )
    result, tokens = _ask(prompt, {"plan": state["plan"].model_dump()}, TesterOutput)
    return {
        "test_files": result.files,
        "trace": [_message("tester_write", "tests", result.notes, state, tokens=tokens)],
    }


def run_tests_node(state):
    """Run REAL pytest using the existing project sandbox, not an LLM."""
    report = run_pytest(state["code_files"], state["test_files"])
    iteration = state["test_iters"] + 1
    update = {"test_report": report, "test_iters": iteration}
    if not report.all_passed:
        update["coder_mode"] = "fix_tests"
        update["error_history"] = [report.error_signature]
    msg = _message("run_tests", "test_report", f"{report.passed} passed, {report.failed} failed",
                   state, report.model_dump(exclude={"raw_output"}))
    msg.iteration = iteration
    update["trace"] = [msg]
    return update


def attribute_node(state):
    """Decide whether the code, tests, or ambiguous spec caused the failure."""
    report = state["test_report"]
    # A syntax error in a generated test should be fixed by the Tester, not Coder.
    def test_has_syntax_error():
        for filename, source in state["test_files"].items():
            try:
                compile(source, filename, "exec")
            except SyntaxError:
                return True
        return False

    if report.collection_error and test_has_syntax_error():
        draft = AttributionDraft(
            details=[FailureVerdict(test_name=f.test_name, verdict="TEST_BUG",
                                    spec_ref=f.spec_ref, reasoning="test file syntax error")
                     for f in report.failures],
            suggestion="Fix the syntax of the generated pytest test file.",
        )
        attribution = Attribution.from_draft(draft)
        attribution.by_rule = True
        tokens = 0
    else:
        prompt = (
            "Determine the cause of EACH failed test based on the specification: "
            "CODE_BUG (implementation wrong), TEST_BUG (test expectation wrong), "
            "or SPEC_AMBIGUITY (spec unclear). Return AttributionDraft with "
            "one FailureVerdict per failure and an actionable suggestion."
        )
        draft, tokens = _ask(prompt, {
            "plan": state["plan"].model_dump(),
            "code_files": state["code_files"],
            "test_files": state["test_files"],
            "test_report": report.model_dump(exclude={"raw_output"}),
        }, AttributionDraft)
        attribution = Attribution.from_draft(draft)
    return {
        "attribution": attribution,
        "trace": [_message("attribute", "attribution", attribution.verdict, state,
                           attribution.model_dump(), tokens)],
    }


def tester_fix_node(state):
    """Repair tests only; never overwrite production code."""
    prompt = (
        "Fix the incorrect pytest expectations identified by attribution. "
        "Only edit the test files; keep all valid tests. "
        "Follow the Plan, and return complete files as TesterOutput."
    )
    result, tokens = _ask(prompt, {
        "plan": state["plan"].model_dump(),
        "test_files": state["test_files"],
        "attribution": state["attribution"].model_dump(),
    }, TesterOutput)
    return {
        "test_files": result.files,
        "trace": [_message("tester_fix", "tests", result.notes, state, tokens=tokens)],
    }


# Merge with MOCK_NODES to replace only the four Tester nodes.
TESTER_NODES = {
    "tester_write": tester_write_node,
    "run_tests": run_tests_node,
    "attribute": attribute_node,
    "tester_fix": tester_fix_node,
}
