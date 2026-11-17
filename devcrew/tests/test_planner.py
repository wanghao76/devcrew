"""Planner unit and mock-integration tests."""
import pytest

from devcrew.agents import planner
from devcrew.graph import RECURSION_LIMIT, build_graph
from devcrew.mocks import MOCK_NODES
from devcrew.schemas import (Attribution, FailureVerdict, FunctionSpec, Plan,
                             RunConfig, SpecItem)
from devcrew.state import initial_state


def valid_plan(version=99, changed_ec2=False):
    return Plan(
        version=version,
        summary="Add two integers.",
        files=["solution.py"],
        functions=[FunctionSpec(
            name="add",
            signature="def add(a: int, b: int) -> int",
            description="Return the arithmetic sum.",
        )],
        acceptance_criteria=[
            SpecItem(id="AC-1", text="add(1, 2) returns 3"),
            SpecItem(id="AC-2", text="add(-2, 5) returns 3"),
            SpecItem(id="AC-3", text="add(10, 20) returns 30"),
        ],
        edge_cases=[
            SpecItem(id="EC-1", text="add(0, 0) returns 0"),
            SpecItem(id="EC-2", text="add(-1, 1) returns 1" if changed_ec2 else "add(-1, 1) returns 0"),
            SpecItem(id="EC-3", text="add(1000000, 1) returns 1000001"),
        ],
        assumptions=["Inputs are integers."],
    )


def test_validate_plan_accepts_complete_contract():
    assert planner.validate_plan(valid_plan()) == []


def test_validate_plan_reports_cross_field_and_id_errors():
    bad = valid_plan().model_copy(deep=True)
    bad.functions[0] = bad.functions[0].model_copy(update={
        "name": "other",
        "file": "missing.py",
    })
    bad.acceptance_criteria[1] = bad.acceptance_criteria[1].model_copy(update={"id": "AC-3"})
    errors = planner.validate_plan(bad)
    assert any("undeclared file" in error for error in errors)
    assert any("does not match" in error for error in errors)
    assert any("unique" in error for error in errors)


def test_initial_plan_overwrites_model_version_and_emits_small_trace(monkeypatch):
    calls = []

    def fake_chat(system, user, schema, *, agent):
        calls.append(user)
        return valid_plan(version=88), 123

    monkeypatch.setattr(planner, "chat_json", fake_chat)
    state = initial_state("add two numbers")
    state["code_files"] = {"solution.py": "SECRET_CODE"}
    state["test_files"] = {"test_solution.py": "SECRET_TEST"}
    update = planner.planner_node(state)

    assert update["plan"].version == 1
    assert update["coder_mode"] == "write"
    assert update["replan_count"] == 0
    assert update["trace"][0].tokens == 123
    assert update["trace"][0].payload == {
        "plan_version": 1,
        "ac_count": 3,
        "ec_count": 3,
        "changed_spec_ids": [],
    }
    assert "SECRET_CODE" not in calls[0] and "SECRET_TEST" not in calls[0]


def test_invalid_candidate_gets_one_semantic_repair(monkeypatch):
    invalid = valid_plan().model_copy(update={"edge_cases": []})
    responses = iter([(invalid, 10), (valid_plan(), 20)])
    monkeypatch.setattr(planner, "chat_json", lambda *args, **kwargs: next(responses))

    update = planner.planner_node(initial_state("add two numbers"))

    assert update["trace"][0].tokens == 30
    assert len(update["plan"].edge_cases) == 3


def test_second_invalid_candidate_fails_closed(monkeypatch):
    invalid = valid_plan().model_copy(update={"edge_cases": []})
    monkeypatch.setattr(planner, "chat_json", lambda *args, **kwargs: (invalid, 10))
    with pytest.raises(planner.PlannerValidationError, match="EC requires at least 3 items"):
        planner.planner_node(initial_state("add two numbers"))


def test_replan_reads_schema_details_and_versions_in_code(monkeypatch):
    captured = []

    def fake_chat(system, user, schema, *, agent):
        captured.append(user)
        return valid_plan(version=90, changed_ec2=True), 42

    monkeypatch.setattr(planner, "chat_json", fake_chat)
    state = initial_state("add two numbers")
    state["plan"] = valid_plan(version=1)
    state["attribution"] = Attribution(
        verdict="SPEC_AMBIGUITY",
        details=[FailureVerdict(
            test_name="test_ec2_negative",
            verdict="SPEC_AMBIGUITY",
            spec_ref="EC-2",
            reasoning="The sign rule is ambiguous.",
        )],
        suggestion="Clarify EC-2.",
    )

    update = planner.planner_node(state)

    assert update["plan"].version == 2
    assert update["replan_count"] == 1
    assert update["trace"][0].payload["changed_spec_ids"] == ["EC-2"]
    assert "The sign rule is ambiguous." in captured[0]
    assert "Clarify EC-2." in captured[0]


def test_no_planner_ablation_is_deterministic_and_does_not_call_llm(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("LLM should not be called")

    monkeypatch.setattr(planner, "chat_json", fail_if_called)
    state = initial_state(
        "Implement def add(a: int, b: int) -> int: return the sum.",
        config=RunConfig(use_planner=False),
    )
    update = planner.planner_node(state)

    assert update["plan"].functions[0].name == "add"
    assert update["plan"].version == 1
    assert update["trace"][0].tokens == 0


def test_real_planner_can_replace_only_planner_mock(monkeypatch):
    monkeypatch.setattr(
        planner,
        "chat_json",
        lambda *args, **kwargs: (valid_plan(), 7),
    )
    app = build_graph({**MOCK_NODES, "planner": planner.planner_node})
    final = app.invoke(
        initial_state("add two numbers", task_id="mock-happy"),
        config={"recursion_limit": RECURSION_LIMIT},
    )

    assert final["final_status"] == "approved"
    assert final["plan"].version == 1
    assert final["trace"][0].node == "planner"
