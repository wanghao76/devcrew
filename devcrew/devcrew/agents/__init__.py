"""DevCrew real agent implementations."""
from typing import Callable, Dict, Iterable

ROLES = ("planner", "coder", "tester", "reviewer")


def select_nodes(real: Iterable[str] = ROLES) -> Dict[str, Callable]:
    """Return MOCK_NODES with the given roles replaced by the real agents."""
    from devcrew.mocks import MOCK_NODES

    real = set(real)
    unknown = real - set(ROLES)
    if unknown:
        raise ValueError(f"unknown roles: {sorted(unknown)}")
    nodes = dict(MOCK_NODES)
    if "planner" in real:
        from devcrew.agents.planner import planner_node
        nodes["planner"] = planner_node
    if "coder" in real:
        from devcrew.agents.coder import CODER_NODES
        nodes.update(CODER_NODES)
    if "tester" in real:
        from devcrew.agents.tester import TESTER_NODES
        nodes.update(TESTER_NODES)
    if "reviewer" in real:
        from devcrew.agents.reviewer import reviewer_node
        nodes["reviewer"] = reviewer_node
    return nodes
