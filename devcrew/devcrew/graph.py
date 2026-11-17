"""DevCrew 流程编排（A 负责）

build_graph 接收一个 {节点名: 函数} 字典，所以 mock 和真实 Agent 可以任意混用：
    nodes = {**MOCK_NODES, "planner": planner_node}
"""
from typing import Callable, Dict

from langgraph.graph import END, START, StateGraph

from devcrew.schemas import AgentMessage
from devcrew.state import DevState

NODE_NAMES = ["planner", "coder", "coder_fix", "tester_write", "run_tests",
              "attribute", "tester_fix", "reviewer", "finalize"]


def _stalled(s: DevState) -> bool:
    sig = s["test_report"].error_signature
    return s["error_history"].count(sig) >= s["config"].stall_threshold


def route_after_test(s: DevState) -> str:
    cfg = s["config"]
    if s["test_report"].all_passed:
        return "reviewer"
    if s["test_iters"] >= cfg.max_test_iters:
        return "finalize"
    if not cfg.use_attribution:           # 消融配置 F
        return "coder_fix"
    return "attribute"


def route_after_attribution(s: DevState) -> str:
    verdict = s["attribution"].verdict
    can_replan = s["replan_count"] < s["config"].max_replans
    if can_replan and (verdict == "SPEC_AMBIGUITY" or _stalled(s)):
        return "planner"
    if verdict == "TEST_BUG":
        return "tester_fix"
    return "coder_fix"                    # CODE_BUG，或者重新规划次数已用完


def route_after_review(s: DevState) -> str:
    if s["review"].verdict == "APPROVE" or s["review_iters"] >= s["config"].max_review_iters:
        return "finalize"
    return "coder_fix"


def finalize_node(s: DevState) -> dict:
    report, review = s.get("test_report"), s.get("review")
    if report and report.all_passed and review and review.verdict == "APPROVE":
        status = "approved"
    elif not (report and report.all_passed):
        status = "max_test_iters"
    else:
        status = "max_review_iters"
    msg = AgentMessage(node="finalize", sender="system", receivers=["user"], type="final",
                       summary=f"finished: {status}", iteration=s["test_iters"])
    return {"final_status": status, "trace": [msg]}


def build_graph(nodes: Dict[str, Callable[[DevState], dict]]):
    nodes = {"finalize": finalize_node, **nodes}
    missing = set(NODE_NAMES) - set(nodes)
    if missing:
        raise ValueError(f"missing nodes: {sorted(missing)}")

    g = StateGraph(DevState)
    for name in NODE_NAMES:
        g.add_node(name, nodes[name])

    g.add_edge(START, "planner")
    g.add_edge("planner", "coder")                      # 扇出：Coder 和 Tester 并行
    g.add_edge("planner", "tester_write")
    g.add_edge(["coder", "tester_write"], "run_tests")  # 汇合：两者都完成才跑测试
    g.add_edge("coder_fix", "run_tests")                # 修复路径不经过汇合边，否则会卡住
    g.add_edge("tester_fix", "run_tests")
    g.add_conditional_edges("run_tests", route_after_test, ["reviewer", "attribute", "coder_fix", "finalize"])
    g.add_conditional_edges("attribute", route_after_attribution, ["planner", "tester_fix", "coder_fix"])
    g.add_conditional_edges("reviewer", route_after_review, ["coder_fix", "finalize"])
    g.add_edge("finalize", END)
    return g.compile()


# 一次运行最多经过的节点步数。默认值 25 不够，最坏情况下会提前报错
RECURSION_LIMIT = 100
