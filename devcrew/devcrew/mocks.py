"""Mock Agent（A 负责）

每个 mock 返回固定内容，只用来跑通流程和测试路由。run_tests_node 是真实实现，C 可以直接搬到 agents/tester.py。
场景由 task_id 决定，格式为 "mock-<scenario>"：
    happy     一次通过
    code_bug  代码有 bug -> CODE_BUG -> coder_fix
    test_bug  测试写错 -> TEST_BUG -> tester_fix
    spec      需求歧义 -> SPEC_AMBIGUITY -> planner 重新规划
    review    Reviewer 第一轮要求修改
    stall     代码一直错 -> 停滞 -> 重新规划 -> 达到最大测试轮数
"""
from devcrew.schemas import (AgentMessage, Attribution, AttributionDraft, FailureVerdict, FunctionSpec,
                             Plan, ReviewComment, ReviewVerdict, SpecItem, StaticReport)
from devcrew.state import DevState
from devcrew.tools.sandbox import run_pytest

CORRECT = "def add(a: int, b: int) -> int:\n    return a + b\n"
BUGGY = "def add(a: int, b: int) -> int:\n    return a - b\n"
TESTS_OK = ("from solution import add\n\n"
            "def test_ac1_basic():\n    assert add(1, 2) == 3\n\n"
            "def test_ec1_zeros():\n    assert add(0, 0) == 0\n\n"
            "def test_ec2_negative():\n    assert add(-1, 1) == 0\n")
TESTS_WRONG = TESTS_OK.replace("== 3", "== 4")


def _scenario(s: DevState) -> str:
    return s["task_id"].split("-", 1)[1] if s["task_id"].startswith("mock-") else "happy"


def mock_planner(s: DevState) -> dict:
    old = s.get("plan")
    plan = Plan(version=old.version + 1 if old else 1,
                summary="Add two integers.", files=["solution.py"],
                functions=[FunctionSpec(name="add", signature="def add(a: int, b: int) -> int",
                                        description="Return a + b.")],
                acceptance_criteria=[SpecItem(id="AC-1", text="add(1, 2) returns 3")],
                edge_cases=[SpecItem(id="EC-1", text="add(0, 0) returns 0"),
                            SpecItem(id="EC-2", text="add(-1, 1) returns 0")])
    msg = AgentMessage(node="planner", sender="planner", receivers=["coder", "tester"], type="plan",
                       summary=f"plan v{plan.version}", payload=plan.model_dump(), iteration=s["test_iters"])
    return {"plan": plan, "coder_mode": "write", "replan_count": s["replan_count"] + (1 if old else 0),
            "trace": [msg]}


def mock_coder(s: DevState) -> dict:
    sc, mode = _scenario(s), s["coder_mode"]
    buggy = sc == "stall" or (sc == "code_bug" and mode == "write") or (sc == "spec" and s["plan"].version == 1)
    code = BUGGY if buggy else CORRECT
    node = "coder" if mode == "write" else "coder_fix"
    msg = AgentMessage(node=node, sender="coder", receivers=["sandbox"], type="code",
                       summary=f"[{mode}] wrote solution.py", iteration=s["test_iters"])
    return {"code_files": {"solution.py": code}, "trace": [msg]}


def mock_tester_write(s: DevState) -> dict:
    tests = TESTS_WRONG if _scenario(s) == "test_bug" else TESTS_OK
    msg = AgentMessage(node="tester_write", sender="tester", receivers=["sandbox"], type="tests",
                       summary="wrote 3 tests", iteration=s["test_iters"])
    return {"test_files": {"test_solution.py": tests}, "trace": [msg]}


def mock_tester_fix(s: DevState) -> dict:
    msg = AgentMessage(node="tester_fix", sender="tester", receivers=["sandbox"], type="tests",
                       summary="fixed wrong expectation in test_ac1_basic", iteration=s["test_iters"])
    return {"test_files": {"test_solution.py": TESTS_OK}, "trace": [msg]}


def run_tests_node(s: DevState) -> dict:
    """真实实现，不是 mock。"""
    report = run_pytest(s["code_files"], s["test_files"])
    update = {"test_report": report, "test_iters": s["test_iters"] + 1}
    if not report.all_passed:
        update["coder_mode"] = "fix_tests"
        update["error_history"] = [report.error_signature]      # reducer 会追加到已有列表
    msg = AgentMessage(node="run_tests", sender="sandbox", receivers=["tester"], type="test_report",
                       summary=f"{report.passed} passed, {report.failed} failed",
                       payload=report.model_dump(exclude={"raw_output"}), iteration=update["test_iters"])
    update["trace"] = [msg]
    return update


def mock_attribute(s: DevState) -> dict:
    verdict = {"test_bug": "TEST_BUG", "spec": "SPEC_AMBIGUITY"}.get(_scenario(s), "CODE_BUG")
    draft = AttributionDraft(
        details=[FailureVerdict(test_name=f.test_name, verdict=verdict, spec_ref=f.spec_ref,
                                reasoning="mock reasoning") for f in s["test_report"].failures],
        suggestion="mock suggestion")
    attribution = Attribution.from_draft(draft)
    msg = AgentMessage(node="attribute", sender="tester", receivers=["coder", "tester", "planner"],
                       type="attribution", summary=attribution.verdict, payload=attribution.model_dump(),
                       iteration=s["test_iters"])
    return {"attribution": attribution, "trace": [msg]}


def mock_reviewer(s: DevState) -> dict:
    comments = []
    if s["config"].use_reviewer and _scenario(s) == "review" and s["review_iters"] == 0:
        comments = [ReviewComment(severity="major", category="style", file="solution.py", line=1,
                                  comment="missing docstring", suggestion="add a docstring")]
    review = ReviewVerdict.from_comments(comments, StaticReport())
    update = {"review": review, "review_iters": s["review_iters"] + 1}
    if review.verdict == "REQUEST_CHANGES":
        update["coder_mode"] = "fix_review"
    update["trace"] = [AgentMessage(node="reviewer", sender="reviewer", receivers=["coder"], type="review",
                                    summary=review.verdict, payload=review.model_dump(),
                                    iteration=s["test_iters"])]
    return update


MOCK_NODES = {
    "planner": mock_planner,
    "coder": mock_coder,
    "coder_fix": mock_coder,
    "tester_write": mock_tester_write,
    "run_tests": run_tests_node,
    "attribute": mock_attribute,
    "tester_fix": mock_tester_fix,
    "reviewer": mock_reviewer,
}
