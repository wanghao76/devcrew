"""DevCrew Streamlit UI backed by the compiled LangGraph update stream."""

from __future__ import annotations

from typing import Any

import streamlit as st

from devcrew.agents.reviewer import reviewer_node
from devcrew.graph import RECURSION_LIMIT, build_graph
from devcrew.mocks import MOCK_NODES
from devcrew.state import initial_state


COLOURS = {
    "planner": "blue",
    "coder": "green",
    "tester": "orange",
    "sandbox": "orange",
    "reviewer": "violet",
}


def _merge_update(state: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    merged = dict(state)
    for key, value in update.items():
        if key in {"trace", "error_history"}:
            merged[key] = [*merged.get(key, []), *value]
        else:
            merged[key] = value
    return merged


def _run(requirement: str, scenario: str) -> dict[str, Any]:
    graph = build_graph({**MOCK_NODES, "reviewer": reviewer_node})
    state = initial_state(requirement, task_id=f"mock-{scenario}")
    with st.status("Running DevCrew", expanded=True, state="running") as status:
        for update in graph.stream(
            state, stream_mode="updates", config={"recursion_limit": RECURSION_LIMIT}
        ):
            for node, payload in update.items():
                state = _merge_update(state, payload)
                status.write(f"{node}: completed")
        status.update(label="DevCrew run complete", state="complete", expanded=False)
    return state


def _render_results(state: dict[str, Any]) -> None:
    plan = state.get("plan")
    report = state.get("test_report")
    review = state.get("review")
    st.subheader("Execution results")
    solution = state.get("code_files", {}).get("solution.py")
    if solution:
        st.download_button(
            "Download solution.py",
            solution,
            file_name="solution.py",
            mime="text/x-python",
            icon=":material/download:",
        )
    plan_tab, code_tab, tests_tab, review_tab = st.tabs(
        ["Plan", "Code", "Tests", "Review"]
    )
    with plan_tab:
        st.json(plan.model_dump() if plan else {})
    with code_tab:
        for name, content in state.get("code_files", {}).items():
            st.markdown(f"**{name}**")
            st.code(content, language="python")
    with tests_tab:
        if report:
            passed, failed = st.columns(2)
            passed.metric("Passed", report.passed)
            failed.metric("Failed", report.failed)
            st.json(report.model_dump(exclude={"raw_output"}))
    with review_tab:
        if review:
            st.metric("Final verdict", review.verdict)
            for comment in review.comments:
                st.warning(
                    f"{comment.severity.upper()} - {comment.file}:{comment.line}\n\n"
                    f"{comment.comment}\n\nSuggestion: {comment.suggestion}"
                )
            st.json(review.model_dump())


def main() -> None:
    st.set_page_config(
        page_title="DevCrew", page_icon=":material/groups:", layout="wide"
    )
    st.title("DevCrew")
    st.caption("MULTI-AGENT SOFTWARE DEVELOPMENT SYSTEM")
    st.session_state.setdefault("final_state", None)

    with st.sidebar:
        st.header("New task")
        requirement = st.text_area(
            "Programming requirement",
            "Create a Python function that adds two integers.",
            height=150,
        )
        scenario = st.selectbox(
            "Mock upstream scenario",
            ["happy", "code_bug", "test_bug", "spec", "review", "stall"],
        )
        run = st.button(
            "Run DevCrew",
            type="primary",
            width="stretch",
            icon=":material/play_arrow:",
        )
        if st.button("Clear results", width="stretch", icon=":material/delete_sweep:"):
            st.session_state.final_state = None
        st.caption(
            "The Reviewer is LLM-enabled. Planner, Coder, and Tester use group mocks "
            "until their real nodes are integrated."
        )

    if run:
        st.session_state.final_state = _run(requirement, scenario)
    state = st.session_state.final_state
    if not state:
        st.info(
            "Enter a requirement and run DevCrew to view the workflow trace and "
            "final artifacts."
        )
        return

    trace = state.get("trace", [])
    metrics = st.columns(4)
    metrics[0].metric("Current node", trace[-1].node if trace else "idle", border=True)
    metrics[1].metric("Test iterations", state.get("test_iters", 0), border=True)
    metrics[2].metric("Review iterations", state.get("review_iters", 0), border=True)
    metrics[3].metric(
        "Final verdict", getattr(state.get("review"), "verdict", "-"), border=True
    )
    st.subheader("Agent execution trace")
    for message in trace:
        st.markdown(
            f":{COLOURS.get(message.sender, 'gray')}[**{message.node}**] - "
            f"{message.summary}"
        )
    _render_results(state)


if __name__ == "__main__":
    main()
