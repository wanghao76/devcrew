"""Small offline tests for Tester; no API key or LangGraph needed."""
import json

from devcrew.agents import tester
from devcrew.schemas import (
    Attribution, AttributionDraft, FailureVerdict, FunctionSpec, Plan, SpecItem,
    TesterOutput,
)
from devcrew.state import initial_state

GOOD_CODE = "def add(a, b):\n    return a + b\n"
BAD_CODE = "def add(a, b):\n    return a - b\n"
GOOD_TEST = "from solution import add\n\ndef test_ac1_add():\n    assert add(1, 2) == 3\n"
WRONG_TEST = GOOD_TEST.replace("== 3", "== 4")


def state(code=GOOD_CODE, tests=GOOD_TEST):
    s = initial_state("add two numbers")
    s["plan"] = Plan(
        summary="addition", files=["solution.py"],
        functions=[FunctionSpec(name="add", signature="def add(a,b)", description="sum")],
        acceptance_criteria=[SpecItem(id="AC-1", text="add(1,2) returns 3")],
        edge_cases=[],
    )
    s["code_files"] = {"solution.py": code}
    s["test_files"] = {"test_solution.py": tests}
    return s


def test_tester_write_is_independent(monkeypatch):
    seen = {}

    def fake_ask(system, data, schema):
        seen.update(data)
        return TesterOutput(files={"test_solution.py": GOOD_TEST}, notes="written"), 5

    monkeypatch.setattr(tester, "_ask", fake_ask)
    output = tester.tester_write_node(state(code="PRIVATE_CODER_SOURCE"))
    assert "code_files" not in seen
    assert "PRIVATE_CODER_SOURCE" not in json.dumps(seen)
    assert output["test_files"]["test_solution.py"] == GOOD_TEST


def test_run_tests_pass_and_failure():
    passed = tester.run_tests_node(state())
    assert passed["test_report"].all_passed
    assert passed["test_report"].passed == 1
    failed = tester.run_tests_node(state(code=BAD_CODE))
    assert not failed["test_report"].all_passed
    assert failed["test_report"].failed == 1
    assert failed["test_report"].failures[0].spec_ref == "AC-1"
    assert "raw_output" not in failed["trace"][0].payload


def test_attribute_code_bug(monkeypatch):
    s = state(code=BAD_CODE)
    s.update(tester.run_tests_node(s))

    def fake_ask(system, data, schema):
        return AttributionDraft(details=[FailureVerdict(
            test_name="test_ac1_add", verdict="CODE_BUG", spec_ref="AC-1",
            reasoning="the code subtracts")], suggestion="return a+b"), 8

    monkeypatch.setattr(tester, "_ask", fake_ask)
    assert tester.attribute_node(s)["attribution"].verdict == "CODE_BUG"


def test_fix_wrong_test_then_pass(monkeypatch):
    s = state(tests=WRONG_TEST)
    s.update(tester.run_tests_node(s))
    assert not s["test_report"].all_passed
    s["attribution"] = Attribution(
        verdict="TEST_BUG", suggestion="3, not 4", details=[FailureVerdict(
            test_name="test_ac1_add", verdict="TEST_BUG", spec_ref="AC-1",
            reasoning="the expectation is incorrect")],
    )
    monkeypatch.setattr(tester, "_ask", lambda *_args: (
        TesterOutput(files={"test_solution.py": GOOD_TEST}, notes="fixed"), 3))
    fixed = tester.tester_fix_node(s)
    assert "code_files" not in fixed
    s.update(fixed)
    assert tester.run_tests_node(s)["test_report"].all_passed


def test_test_file_syntax_error_goes_to_tester():
    s = state(tests="def test_ac1_add(:\n    pass\n")
    s.update(tester.run_tests_node(s))
    result = tester.attribute_node(s)["attribution"]
    assert result.verdict == "TEST_BUG" and result.by_rule
