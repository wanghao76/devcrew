"""契约测试：schema 和路由。改了 schemas.py / state.py / graph.py 之后必须全部通过。"""
import pytest
from pydantic import ValidationError

from devcrew.graph import RECURSION_LIMIT, build_graph
from devcrew.mocks import MOCK_NODES
from devcrew.schemas import (Attribution, AttributionDraft, CoderOutput, FailureVerdict, FunctionSpec, Plan,
                             ReviewComment, ReviewerLLMOutput, ReviewVerdict, RunConfig, SpecItem,
                             StaticReport, TesterOutput)
from devcrew.state import initial_state


# ---------- schema ----------

def test_spec_item_id_format():
    SpecItem(id="AC-1", text="x")
    with pytest.raises(ValidationError):
        SpecItem(id="ac1", text="x")


def test_signature_trailing_colon_is_stripped():
    # DeepSeek 实际返回过 "def is_palindrome(s: str) -> bool:"
    spec = FunctionSpec(name="f", signature=" def f(s: str) -> bool: ", description="d")
    assert spec.signature == "def f(s: str) -> bool"


def test_attribution_priority():
    draft = AttributionDraft(details=[
        FailureVerdict(test_name="t1", verdict="CODE_BUG", spec_ref="AC-1", reasoning=""),
        FailureVerdict(test_name="t2", verdict="TEST_BUG", spec_ref="AC-2", reasoning=""),
    ], suggestion="")
    assert Attribution.from_draft(draft).verdict == "TEST_BUG"
    assert Attribution.from_draft(AttributionDraft(details=[], suggestion="")).verdict == "CODE_BUG"


def test_review_verdict_computed_from_severity():
    minor = ReviewComment(severity="minor", category="style", file="a.py", comment="", suggestion="")
    major = minor.model_copy(update={"severity": "major"})
    assert ReviewVerdict.from_comments([minor], StaticReport()).verdict == "APPROVE"
    assert ReviewVerdict.from_comments([minor, major], StaticReport()).verdict == "REQUEST_CHANGES"


@pytest.mark.parametrize("cls", [Plan, CoderOutput, TesterOutput, AttributionDraft, ReviewerLLMOutput])
def test_llm_schemas_export_json_schema(cls):
    assert cls.model_json_schema()["type"] == "object"


def test_plan_roundtrip_from_llm_json():
    raw = ('{"summary": "s", "files": ["solution.py"], '
           '"functions": [{"name": "f", "signature": "def f() -> int", "description": "d"}], '
           '"acceptance_criteria": [{"id": "AC-1", "text": "f() returns 1"}], "edge_cases": []}')
    plan = Plan.model_validate_json(raw)
    assert plan.version == 1 and plan.assumptions == []


# ---------- 路由（全 mock，跑真实沙箱） ----------

def run(scenario, **cfg):
    app = build_graph(MOCK_NODES)
    s = initial_state("add two numbers", task_id=f"mock-{scenario}", config=RunConfig(**cfg))
    final = app.invoke(s, config={"recursion_limit": RECURSION_LIMIT})
    return final, [m.node for m in final["trace"]]


def test_happy():
    final, nodes = run("happy")
    assert nodes == ["planner", "coder", "tester_write", "run_tests", "reviewer", "finalize"]
    assert final["final_status"] == "approved"


def test_code_bug():
    final, nodes = run("code_bug")
    assert nodes[3:7] == ["run_tests", "attribute", "coder_fix", "run_tests"]
    assert final["final_status"] == "approved"


def test_test_bug():
    final, nodes = run("test_bug")
    assert "tester_fix" in nodes and "coder_fix" not in nodes
    assert final["final_status"] == "approved"


def test_spec_ambiguity_replans_and_refans_out():
    final, nodes = run("spec")
    assert nodes.count("planner") == 2 and nodes.count("tester_write") == 2
    assert final["plan"].version == 2 and final["final_status"] == "approved"


def test_review_reject_then_approve():
    final, nodes = run("review")
    assert nodes.count("reviewer") == 2
    assert final["review_iters"] == 2 and final["final_status"] == "approved"


def test_stall_replans_once_then_hits_max_iters():
    final, nodes = run("stall")
    assert nodes.count("planner") == 2
    assert final["test_iters"] == 4 and final["final_status"] == "max_test_iters"


def test_no_attribution_ablation():
    _, nodes = run("code_bug", use_attribution=False)
    assert "attribute" not in nodes and "coder_fix" in nodes


def test_parallel_trace_merged():
    final, _ = run("happy")
    assert {"coder", "tester_write"} <= {m.node for m in final["trace"]}
