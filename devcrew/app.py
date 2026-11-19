"""DevCrew's single-page workflow UI."""

from __future__ import annotations

import inspect
from typing import Any
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from openai import AuthenticationError

from devcrew.llm import LLMConfigurationError, LLMResponseError
from devcrew.state import initial_state
from devcrew.ui_trace import describe_message
from devcrew.ui_adapter import (
    EXAMPLE_REQUIREMENT,
    STAGES,
    StageProgress,
    workflow_stream,
)


COLOURS = {
    "planner": "blue",
    "coder": "green",
    "tester": "orange",
    "sandbox": "orange",
    "reviewer": "violet",
    "system": "gray",
}

ROLE_ICONS = {
    "planner": "description",
    "coder": "code",
    "tester": "science",
    "sandbox": "science",
    "reviewer": "fact_check",
    "system": "task_alt",
}

# autoscroll needs a newer Streamlit than Python 3.9 can install; skip it there.
_AUTOSCROLL = (
    {"autoscroll": True}
    if "autoscroll" in inspect.signature(st.container).parameters
    else {}
)


def _render_trace(trace) -> None:
    st.subheader("Execution timeline")
    st.caption(f"{len(trace)} steps recorded. Scroll to explore earlier steps.")
    with st.container(
        height=420, border=True, key="execution_timeline", **_AUTOSCROLL
    ):
        attempts: dict[str, int] = {}
        for index, message in enumerate(trace, start=1):
            attempts[message.type] = attempts.get(message.type, 0) + 1
            card = describe_message(message)
            colour = COLOURS.get(message.sender, "gray")
            icon = ROLE_ICONS.get(message.sender, "update")
            with st.container(border=True):
                number, content, status = st.columns([0.5, 6, 1.5], gap="small")
                with number:
                    st.markdown(f":{colour}[**{index:02d}**]")
                with content:
                    st.markdown(
                        f":{colour}[:material/{icon}: **{card.role}**] "
                        f"· **{card.title}**"
                    )
                    st.write(card.detail)
                    if attempts[message.type] > 1:
                        st.caption(f"Attempt {attempts[message.type]}")
                with status:
                    st.badge(card.status, color=card.status_colour)


def _merge(state: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    merged = dict(state)
    for key, value in update.items():
        merged[key] = (
            [*merged.get(key, []), *value]
            if key in {"trace", "error_history"}
            else value
        )
    return merged


def _render_progress(progress: StageProgress) -> None:
    labels = {
        "waiting": ("gray", "radio_button_unchecked", "Waiting"),
        "running": ("orange", "pending", "Running"),
        "complete": ("green", "check_circle", "Complete"),
        "changes": ("orange", "build", "Changes requested"),
        "failed": ("red", "error", "Failed"),
    }
    st.subheader("Execution progress")
    for column, stage in zip(st.columns(4), STAGES):
        colour, icon, label = labels[progress.statuses[stage]]
        with column:
            with st.container(border=True):
                st.markdown(f":{colour}[:material/{icon}: **{stage}**]")
                st.caption(label)
    st.progress(progress.percent, text=f"{progress.percent // 25} / 4 stages complete")


def _run(requirement: str) -> dict[str, Any]:
    state = initial_state(requirement, task_id="ui")
    progress = StageProgress()
    slot = st.empty()
    try:
        for mode, update in workflow_stream(requirement):
            if mode == "custom":
                progress.start(update["node"])
            else:
                for node, payload in update.items():
                    state = _merge(state, payload)
                    progress.complete(node, state)
            with slot.container():
                _render_progress(progress)
    except Exception:
        progress.fail()
        with slot.container():
            _render_progress(progress)
        raise
    st.session_state.progress = progress
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
        with st.container(border=True):
            file_info, download = st.columns([3, 1], vertical_alignment="center")
            with file_info:
                st.markdown("### :material/code: solution.py")
                st.caption(
                    f"Python solution · {len(solution.splitlines())} lines · "
                    f"final status: {state.get('final_status')}"
                )
            with download:
                st.download_button(
                    "Download solution.py",
                    solution,
                    file_name="solution.py",
                    mime="text/x-python",
                    icon=":material/download:",
                    type="primary",
                    width="stretch",
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
    st.subheader("Workspace")
    st.caption("Four roles working toward one tested, reviewed solution.")
    roles = [
        (
            "Planner",
            "Understand the task",
            "Plan and acceptance criteria.",
            "Live agent",
        ),
        (
            "Coder",
            "Build the solution",
            "Implementation in solution.py.",
            "Live agent",
        ),
        (
            "Tester",
            "Check the behavior",
            "Tests written from the plan, run with pytest.",
            "Live agent",
        ),
        (
            "Reviewer",
            "Review the result",
            "LLM review and static analysis.",
            "Live agent",
        ),
    ]
    for column, (name, action, description, source) in zip(
        st.columns(4), roles
    ):
        with column:
            with st.container(border=True, height="stretch"):
                role = name.lower()
                colour = COLOURS[role]
                st.markdown(f"### :{colour}[:material/{ROLE_ICONS[role]}: {name}]")
                st.markdown(f"**{action}**")
                st.caption(description)
                st.badge(source, color=colour)


def main() -> None:
    st.set_page_config(
        page_title="DevCrew", page_icon=":material/groups:", layout="wide"
    )
    with st.container(horizontal=True, vertical_alignment="center", gap="medium"):
        st.image(
            str(Path(__file__).parent / "assets" / "devcrew-mark.svg"),
            width=56,
        )
        with st.container(width="stretch", gap="small"):
            st.title("DevCrew")
            st.caption("Plan. Build. Test. Review.")
        st.badge("Live agents", icon=":material/groups:", color="violet")
    # This UI's explicit local config takes precedence over stale host variables.
    # The .env file is ignored by Git and is never included in downloads.
    load_dotenv(Path(__file__).parent / ".env", override=True)
    st.caption(
        "Describe a Python function. Planner, Coder, Tester and Reviewer all call "
        "the configured model; tests run locally with pytest."
    )
    st.session_state.setdefault("result", None)
    st.session_state.setdefault("run_requirement", EXAMPLE_REQUIREMENT)
    st.session_state.setdefault("progress", None)

    with st.form("task_form", border=True):
        st.markdown("### :material/edit_note: Start a new task")
        requirement = st.text_area(
            "What would you like DevCrew to build?",
            value=st.session_state.run_requirement,
            placeholder="Describe a Python programming task...",
            height=120,
            key="requirement_input",
        )
        run = st.form_submit_button(
            "Run DevCrew",
            type="primary",
            width="content",
            icon=":material/play_arrow:",
            key="run_example",
        )
    if st.button("Clear results", width="content", icon=":material/delete_sweep:"):
        st.session_state.result = None
        st.session_state.run_requirement = EXAMPLE_REQUIREMENT
        st.session_state.progress = None

    if run:
        if not requirement.strip():
            st.warning("Please enter a programming requirement.")
        else:
            try:
                st.session_state.result = None
                st.session_state.progress = None
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
    if not run and st.session_state.progress:
        _render_progress(st.session_state.progress)
    trace = state.get("trace", [])
    st.subheader("Execution overview")
    metrics = st.columns(4)
    metrics[0].metric("Steps completed", len(trace), border=True)
    metrics[1].metric("Test rounds", state.get("test_iters", 0), border=True)
    metrics[2].metric(
        "Tests passed", getattr(state.get("test_report"), "passed", 0), border=True
    )
    metrics[3].metric(
        "Review decision",
        {"APPROVE": "Approved", "REQUEST_CHANGES": "Changes needed"}.get(
            getattr(state.get("review"), "verdict", ""), "Pending"
        ),
        border=True,
    )
    _render_trace(trace)
    _render_results(state, st.session_state.run_requirement)


if __name__ == "__main__":
    main()
