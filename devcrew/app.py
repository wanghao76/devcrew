"""DevCrew's single-page workflow UI."""

from __future__ import annotations

from typing import Any

import streamlit as st
from openai import AuthenticationError

from devcrew.agents.reviewer import reviewer_node
from devcrew.graph import RECURSION_LIMIT, build_graph
from devcrew.llm import LLMConfigurationError, LLMResponseError
from devcrew.mocks import MOCK_NODES
from devcrew.state import initial_state


COLOURS = {
    "planner": "blue",
    "coder": "green",
    "tester": "orange",
    "sandbox": "orange",
    "reviewer": "violet",
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
    """Run today's demo nodes; later replace only this internal node mapping."""
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


def _render_results(state: dict[str, Any], requirement: str) -> None:
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


def _render_empty() -> None:
    with st.container(border=True):
        st.caption("WORKSPACE")
        st.subheader("Build, test, and review with multiple agents.")
        st.caption("Describe what you want built, then run DevCrew.")
    roles = [
        ("Planner", "Breaks down the requirement and defines acceptance criteria."),
        ("Coder", "Generates an implementation from the plan and feedback."),
        ("Tester", "Executes tests and sends evidence or failure feedback."),
        ("Reviewer", "Checks requirement coverage, code quality, and review findings."),
    ]
    for column, (name, description) in zip(st.columns(4), roles, strict=False):
        with column:
            st.markdown(f"### {name}")
            st.caption(description)


def main() -> None:
    st.set_page_config(
        page_title="DevCrew", page_icon=":material/groups:", layout="wide"
    )
    st.title("DevCrew")
    st.caption("MULTI-AGENT SOFTWARE DEVELOPMENT SYSTEM")
    st.session_state.setdefault("result", None)
    st.session_state.setdefault("run_requirement", "")

    with st.form("task_form", border=True):
        requirement = st.text_area(
            "What would you like DevCrew to build?",
            value=st.session_state.run_requirement,
            placeholder="Describe a Python programming task...",
            height=120,
        )
        run = st.form_submit_button(
            "Run DevCrew", type="primary", width="content", icon=":material/play_arrow:"
        )
    if st.button("Clear results", width="content", icon=":material/delete_sweep:"):
        st.session_state.result = None
        st.session_state.run_requirement = ""

    if run:
        if not requirement.strip():
            st.warning("Please enter a programming requirement.")
        else:
            try:
                st.session_state.run_requirement = requirement.strip()
                st.session_state.result = _run(requirement.strip())
            except AuthenticationError:
                st.error(
                    "The model API key was rejected. Update OPENAI_API_KEY. "
                    "For a compatible provider, also set OPENAI_BASE_URL and "
                    "OPENAI_MODEL in the environment or .env.",
                    title="Model authentication failed",
                )
            except (LLMConfigurationError, LLMResponseError) as error:
                st.error(str(error), title="Model configuration failed")
            except Exception:
                st.error(
                    "The workflow could not complete. Check the terminal log for "
                    "details.",
                    title="Workflow failed",
                )

    state = st.session_state.result
    if not state:
        _render_empty()
        return
    trace = state.get("trace", [])
    metrics = st.columns(4)
    metrics[0].metric("Agent executions", len(trace), border=True)
    metrics[1].metric("Max iteration", state.get("test_iters", 0), border=True)
    metrics[2].metric(
        "Tests passed", getattr(state.get("test_report"), "passed", 0), border=True
    )
    metrics[3].metric(
        "Final verdict", getattr(state.get("review"), "verdict", "-"), border=True
    )
    st.subheader("Agent execution trace")
    for message in trace:
        st.markdown(
            f":{COLOURS.get(message.sender, 'gray')}[**{message.node}**] - "
            f"{message.summary}"
        )
    _render_results(state, st.session_state.run_requirement)


if __name__ == "__main__":
    main()
