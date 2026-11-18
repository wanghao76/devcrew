"""Temporary example graph adapter; replace node bindings after integration."""

from functools import wraps

from langgraph.config import get_stream_writer

from devcrew.agents.reviewer import reviewer_node
from devcrew.graph import RECURSION_LIMIT, build_graph
from devcrew.mocks import MOCK_NODES
from devcrew.state import initial_state

EXAMPLE_REQUIREMENT = (
    "Implement add(a: int, b: int) -> int, returning the sum of two integers. "
    "Verify add(1, 2) == 3, add(0, 0) == 0, and add(-1, 1) == 0."
)
STAGES = ("Planner", "Coder", "Tester", "Reviewer")
NODE_STAGE = {
    "planner": "Planner",
    "coder": "Coder",
    "coder_fix": "Coder",
    "tester_write": "Tester",
    "tester_fix": "Tester",
    "run_tests": "Tester",
    "attribute": "Tester",
    "reviewer": "Reviewer",
}


def _with_start_event(name, node):
    @wraps(node)
    def wrapped(state):
        get_stream_writer()({"node": name, "event": "start"})
        return node(state)

    return wrapped


def example_stream():
    """Real pytest and Reviewer; the other agents supply fixed example data."""
    nodes = {**MOCK_NODES, "reviewer": reviewer_node}
    graph = build_graph(
        {name: _with_start_event(name, node) for name, node in nodes.items()}
    )
    yield from graph.stream(
        initial_state(EXAMPLE_REQUIREMENT, task_id="mock-happy"),
        stream_mode=["custom", "updates"],
        config={"recursion_limit": RECURSION_LIMIT},
    )


class StageProgress:
    """Track actual completion, invalidating test/review evidence after edits."""

    def __init__(self):
        self.statuses = dict.fromkeys(STAGES, "waiting")

    def start(self, node):
        stage = NODE_STAGE.get(node)
        if not stage:
            return
        if node == "planner":
            self.statuses = dict.fromkeys(STAGES, "waiting")
        elif node in {"coder", "coder_fix"}:
            self.statuses["Tester"] = "waiting"
            self.statuses["Reviewer"] = "waiting"
        elif node in {"tester_fix", "run_tests"}:
            self.statuses["Reviewer"] = "waiting"
        self.statuses[stage] = "running"

    def complete(self, node, state):
        if node in {"planner", "coder", "coder_fix"}:
            self.statuses[NODE_STAGE[node]] = "complete"
        elif node == "run_tests":
            self.statuses["Tester"] = (
                "complete" if state["test_report"].all_passed else "failed"
            )
        elif node == "reviewer":
            self.statuses["Reviewer"] = (
                "complete" if state["review"].verdict == "APPROVE" else "changes"
            )

    def fail(self):
        for stage, status in self.statuses.items():
            if status == "running":
                self.statuses[stage] = "failed"

    @property
    def percent(self):
        return 25 * list(self.statuses.values()).count("complete")
