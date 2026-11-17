"""Planner Agent: requirement -> validated, versioned Plan."""
import ast
import json
import re
from typing import Dict, List, Optional, Tuple

from devcrew.llm import chat_json
from devcrew.schemas import AgentMessage, FunctionSpec, Plan, SpecItem
from devcrew.state import DevState


SYSTEM_PROMPT = """You are DevCrew's senior software architect.
Turn the user's requirement into a precise implementation specification. Do not write code.

Rules:
- Give exact Python function signatures with type hints.
- Produce at least three acceptance criteria, numbered AC-1, AC-2, ...
- Produce at least three edge cases, numbered EC-1, EC-2, ...
- Every criterion must describe concrete, testable input/output or observable behavior.
- Cover applicable empty input, boundary values, invalid types, and large inputs.
- If the requirement is ambiguous, choose one interpretation and record it in assumptions.
- Keep the requested scope; do not invent unrelated features.
"""

SIGNATURE_RE = re.compile(r"\bdef\s+([A-Za-z_]\w*)\s*(\([^\n]*\)(?:\s*->\s*[^:\n]+)?)\s*:?")


class PlannerValidationError(ValueError):
    """Raised when a candidate Plan fails deterministic business rules."""


def build_initial_context(state: DevState) -> str:
    return "Create the initial implementation plan for this requirement:\n\n" + state["requirement"]


def _attribution_feedback(state: DevState) -> List[Dict[str, str]]:
    attribution = state["attribution"]
    if attribution is None:
        return []
    return [
        {
            "test_name": detail.test_name,
            "spec_ref": detail.spec_ref,
            "verdict": detail.verdict,
            "reasoning": detail.reasoning,
        }
        for detail in attribution.details
    ]


def build_replan_context(state: DevState) -> str:
    old = state["plan"]
    attribution = state["attribution"]
    feedback = {
        "details": _attribution_feedback(state),
        "suggestion": attribution.suggestion if attribution else "",
    }
    return (
        "Revise the previous plan because testing found ambiguity or the workflow stalled.\n"
        "Change only the affected specification items; preserve everything else.\n"
        "Do not trust the previous plan's version field; versioning is handled by code.\n\n"
        "Original requirement:\n"
        + state["requirement"]
        + "\n\nPrevious plan:\n"
        + old.model_dump_json(indent=2)
        + "\n\nTester attribution:\n"
        + json.dumps(feedback, indent=2, ensure_ascii=False)
    )


def _parse_signature(signature: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        tree = ast.parse(signature.strip() + ": pass")
    except SyntaxError as exc:
        return None, str(exc)
    if len(tree.body) != 1 or not isinstance(tree.body[0], (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None, "signature must contain exactly one function definition"
    return tree.body[0].name, None


def _validate_spec_items(items: List[SpecItem], prefix: str, require_full: bool) -> List[str]:
    errors = []
    if require_full and len(items) < 3:
        errors.append(f"{prefix} requires at least 3 items")
    expected = [f"{prefix}-{i}" for i in range(1, len(items) + 1)]
    actual = [item.id for item in items]
    if len(actual) != len(set(actual)):
        errors.append(f"{prefix} ids must be unique")
    if actual != expected:
        errors.append(f"{prefix} ids must be consecutive: {expected}")
    for item in items:
        if require_full and len(item.text.strip()) < 8:
            errors.append(f"{item.id} must describe concrete, testable behavior")
    return errors


def validate_plan(plan: Plan, *, require_full: bool = True) -> List[str]:
    """Return deterministic contract violations; an empty list means valid."""
    errors = []
    if not plan.files:
        errors.append("files must not be empty")
    if len(plan.files) != len(set(plan.files)):
        errors.append("files must not contain duplicates")

    names = [function.name for function in plan.functions]
    if not names:
        errors.append("functions must not be empty")
    if len(names) != len(set(names)):
        errors.append("function names must be unique")
    for function in plan.functions:
        if not function.name.isidentifier():
            errors.append(f"invalid function name: {function.name!r}")
        if function.file not in plan.files:
            errors.append(f"{function.name} references undeclared file {function.file!r}")
        parsed_name, signature_error = _parse_signature(function.signature)
        if signature_error:
            errors.append(f"invalid signature for {function.name}: {signature_error}")
        elif parsed_name != function.name:
            errors.append(
                f"signature name {parsed_name!r} does not match function name {function.name!r}"
            )

    errors.extend(_validate_spec_items(plan.acceptance_criteria, "AC", require_full))
    errors.extend(_validate_spec_items(plan.edge_cases, "EC", require_full))
    return errors


def diff_plan(old: Optional[Plan], new: Plan) -> List[str]:
    """Return AC/EC identifiers that were added, removed, or changed."""
    if old is None:
        return []
    old_items = {
        item.id: item.text
        for item in old.acceptance_criteria + old.edge_cases
    }
    new_items = {
        item.id: item.text
        for item in new.acceptance_criteria + new.edge_cases
    }
    return sorted(
        key for key in set(old_items) | set(new_items)
        if old_items.get(key) != new_items.get(key)
    )


def build_minimal_plan(requirement: str, *, version: int = 1) -> Plan:
    """Deterministically wrap a requirement for the no-Planner ablation."""
    match = SIGNATURE_RE.search(requirement)
    if match:
        name = match.group(1)
        signature = f"def {name}{match.group(2).strip()}"
    else:
        name = "solve"
        signature = "def solve(*args, **kwargs)"
    return Plan(
        version=version,
        summary=requirement.strip(),
        files=["solution.py"],
        functions=[FunctionSpec(
            name=name,
            signature=signature,
            description="Implement the behavior stated in the original requirement.",
        )],
        acceptance_criteria=[SpecItem(id="AC-1", text=requirement.strip())],
        edge_cases=[],
        assumptions=[],
    )


def _request_plan(state: DevState, old: Optional[Plan]) -> Tuple[Plan, int]:
    context = build_replan_context(state) if old else build_initial_context(state)
    candidate, tokens = chat_json(SYSTEM_PROMPT, context, Plan, agent="planner")
    version = old.version + 1 if old else 1
    candidate = candidate.model_copy(update={"version": version})
    errors = validate_plan(candidate)
    if not errors:
        return candidate, tokens

    repair_context = (
        context
        + "\n\nYour candidate plan failed deterministic validation. Return a corrected full Plan."
        + "\nValidation errors:\n- "
        + "\n- ".join(errors)
        + "\nCandidate plan:\n"
        + candidate.model_dump_json(indent=2)
    )
    repaired, retry_tokens = chat_json(SYSTEM_PROMPT, repair_context, Plan, agent="planner")
    repaired = repaired.model_copy(update={"version": version})
    retry_errors = validate_plan(repaired)
    if retry_errors:
        raise PlannerValidationError("; ".join(retry_errors))
    return repaired, tokens + retry_tokens


def planner_node(state: DevState) -> dict:
    """Create or revise the shared Plan without directly invoking another Agent."""
    old = state["plan"]
    version = old.version + 1 if old else 1
    if state["config"].use_planner:
        plan, tokens = _request_plan(state, old)
        validation_errors = validate_plan(plan)
    else:
        plan = build_minimal_plan(state["requirement"], version=version)
        tokens = 0
        validation_errors = validate_plan(plan, require_full=False)

    if validation_errors:
        raise PlannerValidationError("; ".join(validation_errors))

    changed = diff_plan(old, plan)
    action = "replanned" if old else "planned"
    summary = f"{action} v{plan.version}: {len(plan.acceptance_criteria)} AC, {len(plan.edge_cases)} EC"
    if changed:
        summary += f"; changed {', '.join(changed)}"
    message = AgentMessage(
        node="planner",
        sender="planner",
        receivers=["coder", "tester"],
        type="plan",
        summary=summary,
        payload={
            "plan_version": plan.version,
            "ac_count": len(plan.acceptance_criteria),
            "ec_count": len(plan.edge_cases),
            "changed_spec_ids": changed,
        },
        tokens=tokens,
        iteration=state["test_iters"],
    )
    return {
        "plan": plan,
        "coder_mode": "write",
        "replan_count": state["replan_count"] + (1 if old else 0),
        "trace": [message],
    }
