"""Human-readable presentation of shared trace messages, without changing State."""

import re
from dataclasses import dataclass

from devcrew.schemas import AgentMessage


@dataclass(frozen=True)
class TraceCard:
    role: str
    title: str
    detail: str
    status: str = "Complete"
    status_colour: str = "green"


def describe_message(message: AgentMessage, *, example: bool = False) -> TraceCard:
    payload, node = message.payload, message.node
    if node == "planner":
        version = payload.get("plan_version", payload.get("version"))
        detail = (
            "Loaded the example plan and its acceptance criteria."
            if example
            else "Prepared the implementation plan and acceptance criteria."
        )
        if version is not None:
            detail += f" Plan version: {version}."
        return TraceCard("Planner", "Plan ready", detail)
    if node in {"coder", "coder_fix"}:
        if node == "coder_fix":
            return TraceCard(
                "Coder",
                "Code updated",
                "Updated the implementation using feedback; tests will run again.",
            )
        return TraceCard(
            "Coder",
            "Implementation ready",
            "Loaded the example solution.py for testing."
            if example
            else "Saved the implementation files for testing.",
        )
    if node in {"tester_write", "tester_fix"}:
        count = re.fullmatch(r"wrote (\d+) tests", message.summary)
        prepared = (
            f"Prepared {count[1]} example tests."
            if example and count
            else "Prepared the example test suite."
            if example
            else "Prepared tests for the plan's acceptance criteria and edge cases."
        )
        return TraceCard(
            "Tester",
            "Test suite updated" if node == "tester_fix" else "Test suite ready",
            "Updated the tests using failure feedback."
            if node == "tester_fix"
            else prepared,
            "Ready",
            "blue",
        )
    if node == "run_tests":
        passed, failed = payload.get("passed"), payload.get("failed")
        if passed is None or failed is None:
            counts = re.fullmatch(r"(\d+) passed, (\d+) failed", message.summary)
            if counts:
                passed, failed = map(int, counts.groups())
        if passed is None or failed is None:
            return TraceCard(
                "Tester", "Test run finished", message.summary, "Finished", "gray"
            )
        successful = payload.get("all_passed", failed == 0 and passed > 0)
        detail = f"Executed the test suite: {passed} passed, {failed} failed."
        if payload.get("collection_error"):
            detail += " Some tests could not be loaded."
        return TraceCard(
            "Tester",
            "Tests passed" if successful else "Tests need attention",
            detail,
            "Passed" if successful else "Failed",
            "green" if successful else "red",
        )
    if node == "attribute":
        verdict = payload.get("verdict", message.summary)
        reason = {
            "CODE_BUG": "The failure was attributed to the implementation.",
            "TEST_BUG": "The failure was attributed to the tests.",
            "SPEC_AMBIGUITY": "The requirement needs clarification to continue.",
        }.get(verdict, message.summary)
        return TraceCard(
            "Tester", "Failure investigated", reason, "Action needed", "orange"
        )
    if node == "reviewer":
        verdict = payload.get("verdict")
        if verdict is None:
            verdict = message.summary.split(";", 1)[0]
        count = payload.get("comments")
        if isinstance(count, list):
            count = len(count)
        approved = verdict == "APPROVE"
        detail = (
            "Reviewed the implementation against the plan, "
            "test evidence and static checks."
        )
        if count == 0:
            detail += " No issues were reported."
        elif isinstance(count, int):
            detail += (
                f" {count} review {'comment' if count == 1 else 'comments'} recorded."
            )
        return TraceCard(
            "Reviewer",
            "Review approved" if approved else "Code changes requested",
            detail,
            "Approved" if approved else "Changes needed",
            "green" if approved else "orange",
        )
    if node == "finalize":
        status = payload.get("final_status", message.summary.removeprefix("finished: "))
        if status == "approved":
            return TraceCard(
                "DevCrew",
                "Solution ready",
                "Tests passed and the review was approved. Download solution.py below.",
                "Ready to download",
            )
        return TraceCard(
            "DevCrew",
            "Run stopped before approval",
            "The workflow ended without approval. "
            "Check the test and review results before using the code.",
            "Not approved",
            "orange",
        )
    return TraceCard(
        message.sender.title(), "Progress updated", message.summary, "Updated", "gray"
    )
