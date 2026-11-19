from devcrew.agents import reviewer
from devcrew.schemas import Plan, RunConfig, SpecItem, TestReport
from devcrew.state import initial_state


def _state():
    state = initial_state("add", config=RunConfig())
    state["plan"] = Plan(
        summary="add",
        files=["solution.py"],
        functions=[],
        acceptance_criteria=[SpecItem(id="AC-1", text="add returns the sum")],
        edge_cases=[],
    )
    state["code_files"] = {"solution.py": "def add(a, b):\n    return a + b\n"}
    state["test_report"] = TestReport(all_passed=True, passed=1, failed=0)
    return state


def test_request_changes_sets_coder_review_mode(monkeypatch):
    monkeypatch.setattr(
        reviewer,
        "analyze_files",
        lambda files: __import__(
            "devcrew.schemas", fromlist=["StaticReport"]
        ).StaticReport(),
    )
    monkeypatch.setattr(
        reviewer,
        "_llm_comments",
        lambda state, static, round_: (
            [
                __import__("devcrew.schemas", fromlist=["ReviewComment"]).ReviewComment(
                    severity="major",
                    category="correctness",
                    file="solution.py",
                    line=1,
                    comment="incorrect",
                    suggestion="fix",
                )
            ],
            9,
        ),
    )
    update = reviewer.reviewer_node(_state())
    assert update["review"].verdict == "REQUEST_CHANGES"
    assert update["coder_mode"] == "fix_review"
    assert update["trace"][0].tokens == 9


def test_follow_up_suppresses_new_minor_comments(monkeypatch):
    monkeypatch.setattr(
        reviewer,
        "analyze_files",
        lambda files: __import__(
            "devcrew.schemas", fromlist=["StaticReport"]
        ).StaticReport(),
    )
    monkeypatch.setattr(
        reviewer,
        "_llm_comments",
        lambda state, static, round_: (
            [
                __import__("devcrew.schemas", fromlist=["ReviewComment"]).ReviewComment(
                    severity="minor",
                    category="style",
                    file="solution.py",
                    line=1,
                    comment="nit",
                    suggestion="rename",
                )
            ],
            3,
        ),
    )
    state = _state()
    state["review_iters"] = 1
    update = reviewer.reviewer_node(state)
    assert update["review"].verdict == "APPROVE"
    assert update["review"].comments == []
