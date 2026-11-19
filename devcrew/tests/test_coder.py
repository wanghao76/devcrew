"""Coder unit and mock-integration tests. The LLM is replaced by a fake chat_json."""
import pytest

from devcrew.agents import coder
from devcrew.graph import RECURSION_LIMIT, build_graph
from devcrew.mocks import BUGGY, CORRECT, MOCK_NODES, TESTS_OK
from devcrew.schemas import (Attribution, CoderOutput, FailureVerdict, FunctionSpec, Plan,
                             ReviewComment, ReviewVerdict, RunConfig, SpecItem, StaticReport,
                             TestFailure, TestReport)
from devcrew.state import initial_state

SECRET_TEST = "SECRET_TEST_MARKER"
SECRET_RAW = "SECRET_RAW_OUTPUT_MARKER"


def make_plan(files=("solution.py",)):
    return Plan(
        summary="Add two integers.",
        files=list(files),
        functions=[FunctionSpec(name="add", signature="def add(a: int, b: int) -> int",
                                description="Return a + b.")],
        acceptance_criteria=[SpecItem(id="AC-1", text="add(1, 2) returns 3")],
        edge_cases=[SpecItem(id="EC-1", text="add(0, 0) returns 0")],
    )


def make_state(mode="write", config=None, **fields):
    state = initial_state("add two numbers", config=config)
    state["plan"] = make_plan()
    state["coder_mode"] = mode
    state.update(fields)
    return state


def failing_report():
    return TestReport(
        all_passed=False, passed=1, failed=1, error_signature="abc",
        failures=[TestFailure(test_name="test_ac1_basic", spec_ref="AC-1", error_type="AssertionError",
                              message="assert -1 == 3\n +  where -1 = add(1, 2)")],
        raw_output=SECRET_RAW,
    )


def fix_tests_state(config=None):
    return make_state(
        "fix_tests", config=config,
        code_files={"solution.py": BUGGY},
        test_files={"test_solution.py": SECRET_TEST},
        test_report=failing_report(),
        attribution=Attribution(
            verdict="CODE_BUG",
            details=[
                FailureVerdict(test_name="test_ac1_basic", verdict="CODE_BUG", spec_ref="AC-1",
                               reasoning="subtracts instead of adding"),
                FailureVerdict(test_name="test_ec9_other", verdict="TEST_BUG", spec_ref="EC-9",
                               reasoning="TEST_BUG_ONLY_REASONING"),
            ],
            suggestion="Use a + b."),
    )


# ---------- information isolation ----------

def test_coder_cannot_see_tests_or_raw_output():
    ctx = coder.build_context(fix_tests_state())
    assert SECRET_TEST not in ctx
    assert SECRET_RAW not in ctx


def test_coder_sees_tests_only_in_ablation_e():
    ctx = coder.build_context(fix_tests_state(config=RunConfig(coder_sees_tests=True)))
    assert SECRET_TEST in ctx
    assert SECRET_RAW not in ctx


# ---------- context per mode ----------

def test_write_context_contains_only_plan():
    ctx = coder.build_context(make_state("write"))
    assert "def add(a: int, b: int) -> int" in ctx
    assert "Failed tests" not in ctx and "Reviewer" not in ctx and "Current implementation" not in ctx


def test_write_after_replan_shows_previous_code():
    ctx = coder.build_context(make_state("write", code_files={"solution.py": BUGGY}))
    assert "plan was revised" in ctx and BUGGY in ctx


def test_fix_tests_context_has_failures_and_code_related_attribution():
    ctx = coder.build_context(fix_tests_state())
    assert "Current implementation" in ctx and BUGGY in ctx
    assert "where -1 = add(1, 2)" in ctx
    assert "Use a + b." in ctx and "subtracts instead of adding" in ctx
    assert "TEST_BUG_ONLY_REASONING" not in ctx


def test_fix_tests_without_attribution_ablation_f():
    state = fix_tests_state(config=RunConfig(use_attribution=False))
    state["attribution"] = None
    ctx = coder.build_context(state)
    assert "Failed tests" in ctx and "QA analysis" not in ctx


def test_fix_review_context_has_only_blocking_comments():
    def comment(severity, text):
        return ReviewComment(severity=severity, category="style", file="solution.py", comment=text,
                             suggestion="s")
    review = ReviewVerdict.from_comments([comment("major", "MAJOR_TEXT"), comment("minor", "MINOR_TEXT")],
                                         StaticReport())
    ctx = coder.build_context(make_state("fix_review", code_files={"solution.py": CORRECT}, review=review))
    assert "MAJOR_TEXT" in ctx and "MINOR_TEXT" not in ctx
    assert "Failed tests" not in ctx


# ---------- self-check ----------

@pytest.mark.parametrize("source, expected", [
    (CORRECT, None),
    ("def add(a, b):\n    return a + b\n", None),          # annotations are not compared
    ("def add(a, b)\n    return a + b\n", "SyntaxError"),
    ("def plus(a, b):\n    return a + b\n", "does not define top-level function add"),
    ("def add(x, y):\n    return x + y\n", "parameters do not match"),
    ("class C:\n    def add(self, a, b):\n        return a + b\n", "does not define top-level function add"),
])
def test_check_files(source, expected):
    errors = coder.check_files({"solution.py": source}, make_plan())
    if expected is None:
        assert errors == []
    else:
        assert len(errors) == 1 and expected in errors[0]


def test_check_files_reports_missing_file():
    assert "solution.py is missing" in coder.check_files({}, make_plan())[0]


@pytest.mark.parametrize("name", ["test_solution.py", "conftest.py", "../solution.py", "/tmp/x.py", "other.py"])
def test_disallowed_files(name):
    assert coder.disallowed_files({name: "x = 1"}, make_plan()) == [name]


def test_planned_file_is_allowed():
    assert coder.disallowed_files({"solution.py": CORRECT}, make_plan()) == []


# ---------- node ----------

def scripted(*answers):
    """Fake chat_json that returns the given CoderOutputs in order and records prompts."""
    calls = []
    it = iter(answers)

    def fake(system, user, schema, *, agent):
        assert schema is CoderOutput and agent == "coder"
        calls.append(user)
        return next(it), 10
    return fake, calls


def test_write_mode_returns_code_and_trace(monkeypatch):
    fake, calls = scripted(CoderOutput(files={"solution.py": CORRECT}, notes="implemented add"))
    monkeypatch.setattr(coder, "chat_json", fake)
    update = coder.coder_node(make_state("write"))
    assert update["code_files"] == {"solution.py": CORRECT}
    msg = update["trace"][0]
    assert msg.node == "coder" and msg.sender == "coder" and msg.tokens == 10
    assert msg.summary == "[write] implemented add"
    assert msg.payload["attempts"] == 1 and msg.payload["self_check_errors"] == []


def test_fix_mode_uses_coder_fix_node_name(monkeypatch):
    fake, _ = scripted(CoderOutput(files={"solution.py": CORRECT}, notes="fixed"))
    monkeypatch.setattr(coder, "chat_json", fake)
    assert coder.coder_node(fix_tests_state())["trace"][0].node == "coder_fix"


def test_self_check_failure_triggers_repair(monkeypatch):
    fake, calls = scripted(
        CoderOutput(files={"solution.py": "def plus(a, b):\n    return a + b\n"}, notes="v1"),
        CoderOutput(files={"solution.py": CORRECT}, notes="v2"),
    )
    monkeypatch.setattr(coder, "chat_json", fake)
    update = coder.coder_node(make_state("write"))
    assert update["code_files"]["solution.py"] == CORRECT
    assert update["trace"][0].payload["attempts"] == 2 and update["trace"][0].tokens == 20
    assert "failed the self-check" in calls[1] and "does not define top-level function add" in calls[1]


def test_exhausted_repairs_hand_over_without_raising(monkeypatch):
    bad = CoderOutput(files={"solution.py": "def add(a, b)\n", "conftest.py": "import os"}, notes="bad")
    fake, calls = scripted(bad, bad, bad)
    monkeypatch.setattr(coder, "chat_json", fake)
    update = coder.coder_node(make_state("write"))
    assert len(calls) == coder.MAX_ATTEMPTS
    assert "conftest.py" not in update["code_files"]
    assert update["trace"][0].summary.startswith("[write] self-check failed after 3 attempts")


def test_omitted_files_keep_current_content(monkeypatch):
    plan = make_plan(files=("solution.py", "utils.py"))
    fake, _ = scripted(CoderOutput(files={"solution.py": CORRECT}, notes="only solution"))
    monkeypatch.setattr(coder, "chat_json", fake)
    state = make_state("fix_tests", code_files={"solution.py": BUGGY, "utils.py": "X = 1\n"},
                       test_report=failing_report())
    state["plan"] = plan
    update = coder.coder_node(state)
    assert update["code_files"] == {"solution.py": CORRECT, "utils.py": "X = 1\n"}


# ---------- graph integration (mock Planner / Tester / Reviewer, real pytest sandbox) ----------

def run_graph(monkeypatch, scenario):
    prompts = []

    def fake(system, user, schema, *, agent):
        prompts.append(user)
        fixing = "Mode: fix_tests" in user
        return CoderOutput(files={"solution.py": CORRECT if fixing or scenario != "happy" else BUGGY},
                           notes="fix" if fixing else "write"), 5

    monkeypatch.setattr(coder, "chat_json", fake)
    app = build_graph({**MOCK_NODES, **coder.CODER_NODES})
    final = app.invoke(initial_state("add two numbers", task_id=f"mock-{scenario}"),
                       config={"recursion_limit": RECURSION_LIMIT})
    return final, [m.node for m in final["trace"]], prompts


def test_graph_buggy_first_draft_is_fixed_from_test_feedback(monkeypatch):
    final, nodes, prompts = run_graph(monkeypatch, "happy")
    assert nodes == ["planner", "coder", "tester_write", "run_tests", "attribute",
                     "coder_fix", "run_tests", "reviewer", "finalize"]
    assert final["final_status"] == "approved"
    assert all(TESTS_OK not in p and "def test_" not in p for p in prompts)


def test_graph_review_feedback_reaches_coder(monkeypatch):
    final, nodes, prompts = run_graph(monkeypatch, "review")
    assert nodes.count("coder_fix") == 1 and nodes.count("reviewer") == 2
    assert "Mode: fix_review" in prompts[-1] and "missing docstring" in prompts[-1]
    assert final["final_status"] == "approved"
