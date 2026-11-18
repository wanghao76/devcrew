"""Simple DevCrew UI; internal agents can be replaced without changing the page."""

from __future__ import annotations

from typing import Any

import streamlit as st

from devcrew.agents.reviewer import reviewer_node
from devcrew.graph import RECURSION_LIMIT, build_graph
from devcrew.mocks import MOCK_NODES
from devcrew.state import initial_state


AGENT_COLOURS = {
    "planner": "#64748b",
    "coder": "#2563eb",
    "tester": "#0d9488",
    "sandbox": "#d97706",
    "reviewer": "#7c3aed",
}


def _merge(state: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    merged = dict(state)
    for key, value in update.items():
        merged[key] = (
            [*merged.get(key, []), *value]
            if key in {"trace", "error_history"}
            else value
        )
    return merged


def _run(requirement: str) -> dict[str, Any]:
    graph = build_graph({**MOCK_NODES, "reviewer": reviewer_node})
    state = initial_state(requirement, task_id="mock-happy")
    with st.status("Running DevCrew", expanded=True, state="running") as status:
        for update in graph.stream(
            state, stream_mode="updates", config={"recursion_limit": RECURSION_LIMIT}
        ):
            for node, payload in update.items():
                state = _merge(state, payload)
                status.write(f"{node}: completed")
        status.update(label="DevCrew run complete", state="complete", expanded=False)
    return state


def _results(state: dict[str, Any], requirement: str) -> None:
    plan, report, review = (
        state.get("plan"),
        state.get("test_report"),
        state.get("review"),
    )
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
        st.markdown("#### Original requirement")
        st.write(requirement)
        if plan:
            st.markdown("#### Acceptance criteria")
            for item in [*plan.acceptance_criteria, *plan.edge_cases]:
                st.markdown(f"- **{item.id}** - {item.text}")
    with code_tab:
        for name, content in state.get("code_files", {}).items():
            st.markdown(f"#### {name}")
            st.code(content, language="python")
    with tests_tab:
        if report:
            passed, failed = st.columns(2)
            passed.metric("Passed", report.passed)
            failed.metric("Failed", report.failed)
            st.json(report.model_dump(exclude={"raw_output"}))
    with review_tab:
        if review:
            st.markdown(f"#### Final verdict: :violet[{review.verdict}]")
            if not review.comments:
                st.success("No findings in this review.")
            for comment in review.comments:
                with st.container(border=True):
                    st.markdown(
                        f"**{comment.severity.upper()} - {comment.file}:"
                        f"{comment.line}**"
                    )
                    st.write(comment.comment)
                    st.caption(f"Suggested action: {comment.suggestion}")


def main() -> None:
    st.set_page_config(
        page_title="DevCrew", page_icon=":material/groups:", layout="wide"
    )
    st.html("""<style>
    .trace-card {padding:.8rem 1rem;border:1px solid rgba(128,128,128,.2);
    border-left:5px solid #64748b;border-radius:10px;margin-bottom:.55rem}
    .trace-heading {display:flex;justify-content:space-between;gap:12px}
    .muted {color:#8b949e;font-size:.85rem}
    </style>""")
    st.session_state.setdefault("result", None)
    st.session_state.setdefault("run_requirement", "")

    title, badge = st.columns([5, 1], vertical_alignment="center")
    with title:
        st.title("DevCrew")
        st.caption("MULTI-AGENT SOFTWARE DEVELOPMENT SYSTEM")
    with badge:
        st.badge("UI DEMO", icon=":material/dashboard:")

    with st.sidebar:
        st.header("New task")
        requirement = st.text_area(
            "Programming requirement",
            value=st.session_state.run_requirement
            or "Create a Python function that adds two integers.",
            height=150,
            placeholder="Describe what you want DevCrew to build...",
        )
        run = st.button(
            "Run DevCrew", type="primary", width="stretch", icon=":material/play_arrow:"
        )
        if st.button("Clear results", width="stretch", icon=":material/delete_sweep:"):
            st.session_state.result = None
            st.session_state.run_requirement = ""

    if run and requirement.strip():
        st.session_state.run_requirement = requirement.strip()
        st.session_state.result = _run(requirement.strip())
    elif run:
        st.warning("Please enter a programming requirement.")

    state = st.session_state.result
    if not state:
        with st.container(border=True):
            st.caption("WORKSPACE")
            st.subheader("Build, test, and review with multiple agents.")
            st.caption("Enter a programming task in the sidebar and run DevCrew.")
        for column, (name, text) in zip(
            st.columns(4),
            [
                (
                    "Planner",
                    "Breaks down the requirement and defines acceptance criteria.",
                ),
                ("Coder", "Generates an implementation from the plan and feedback."),
                ("Tester", "Executes tests and sends evidence or failure feedback."),
                (
                    "Reviewer",
                    "Checks requirement coverage, code quality, and review findings.",
                ),
            ],
            strict=False,
        ):
            with column:
                st.markdown(f"### {name}")
                st.caption(text)
        return

    trace = state.get("trace", [])
    st.subheader("Execution overview")
    metrics = st.columns(4)
    metrics[0].metric("Agent executions", len(trace))
    metrics[1].metric("Max iteration", state.get("test_iters", 0))
    metrics[2].metric("Tests passed", getattr(state.get("test_report"), "passed", 0))
    metrics[3].metric("Final verdict", getattr(state.get("review"), "verdict", "-"))
    st.subheader("Agent execution trace")
    for message in trace:
        colour = AGENT_COLOURS.get(message.sender, "#64748b")
        card = (
            f'<div class="trace-card" style="border-left-color:{colour}">'
            f'<div class="trace-heading"><strong>{message.node}</strong>'
            f'<span class="muted">Iteration {message.iteration}</span></div>'
            f"<div>{message.summary}</div></div>"
        )
        st.markdown(
            card,
            unsafe_allow_html=True,
        )
    _results(state, st.session_state.run_requirement)


if __name__ == "__main__":
    main()
