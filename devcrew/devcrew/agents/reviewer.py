"""Reviewer Agent: static gates first, then an LLM semantic review."""

from __future__ import annotations

import json

from devcrew.llm import chat_json
from devcrew.schemas import (
    AgentMessage,
    ReviewComment,
    ReviewerLLMOutput,
    ReviewVerdict,
)
from devcrew.state import DevState
from devcrew.tools.static_analysis import analyze_files


SYSTEM_PROMPT = """You are DevCrew's strict but pragmatic code reviewer.
All supplied tests have passed. Review the plan, complete changed code, declared
test evidence, and static-analysis results. Check every AC/EC for a real
implementation mismatch, then correctness risks not covered by tests, then
security/complexity, and finally minor style issues. Do not nitpick.
Each comment must name a supplied file and line when available and give a
concrete fix. Never claim a test ran unless the TestReport says so. Never expose
secret-like values. Return only the required JSON object; do not decide verdict.
On review rounds after the first, verify old blocker/major issues and report any
new blocker/major regression, but do not add new minor comments."""


def reviewer_node(state: DevState) -> dict:
    """Return Reviewer-owned State fields; graph.py owns all routing."""
    review_round = state["review_iters"] + 1
    if state["config"].use_reviewer:
        static = analyze_files(state["code_files"])
        llm_comments, tokens = _llm_comments(state, static, review_round)
        comments = _static_comments(static) + llm_comments
    else:
        static = analyze_files({})
        comments, tokens = [], 0
    if review_round > 1:
        comments = [
            comment for comment in comments if comment.severity in {"blocker", "major"}
        ]
    review = ReviewVerdict.from_comments(comments, static)
    update = {
        "review": review,
        "review_iters": review_round,
        "trace": [
            AgentMessage(
                node="reviewer",
                sender="reviewer",
                receivers=["coder", "system"],
                type="review",
                summary=f"{review.verdict}; {len(comments)} comment(s)",
                payload={"verdict": review.verdict, "comments": len(comments)},
                tokens=tokens,
                iteration=state["test_iters"],
            )
        ],
    }
    if review.verdict == "REQUEST_CHANGES":
        update["coder_mode"] = "fix_review"
    return update


def _llm_comments(
    state: DevState, static, review_round: int
) -> tuple[list[ReviewComment], int]:
    previous = state.get("review")
    prior = []
    if previous:
        prior = [
            comment.model_dump()
            for comment in previous.comments
            if comment.severity in {"blocker", "major"}
        ]
    report = state.get("test_report")
    test_data = report.model_dump(exclude={"raw_output"}) if report else None
    context = {
        "review_round": review_round,
        "previous_required_findings": prior,
        "plan": state["plan"].model_dump() if state.get("plan") else None,
        "code_files": state["code_files"],
        "test_report": test_data,
        "static_analysis": static.model_dump(),
    }
    output, tokens = chat_json(
        SYSTEM_PROMPT,
        "Review this supplied project data:\n"
        + json.dumps(context, ensure_ascii=False),
        ReviewerLLMOutput,
        agent="reviewer",
    )
    return output.comments, tokens


def _static_comments(static) -> list[ReviewComment]:
    comments: list[ReviewComment] = []
    for finding in static.findings:
        kind, _, remainder = finding.partition(":")
        if kind == "bandit_high":
            file_name, line, _, message = remainder.partition(":")[0], "0", "", finding
            pieces = remainder.split(":", 2)
            if len(pieces) >= 2:
                file_name, line = pieces[0], pieces[1].split(" ", 1)[0]
            comments.append(
                ReviewComment(
                    severity="blocker",
                    category="security",
                    file=file_name,
                    line=int(line or 0),
                    comment=message,
                    suggestion="Resolve the Bandit HIGH finding before delivery.",
                    source="rule",
                )
            )
        elif kind == "radon":
            pieces = remainder.split(":", 2)
            if len(pieces) >= 2:
                comments.append(
                    ReviewComment(
                        severity="major",
                        category="complexity",
                        file=pieces[0],
                        line=int(pieces[1].split(" ", 1)[0] or 0),
                        comment=finding,
                        suggestion=(
                            "Refactor this function until cyclomatic complexity "
                            "is at most 10."
                        ),
                        source="rule",
                    )
                )
    return comments
