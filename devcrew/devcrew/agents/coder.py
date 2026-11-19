"""Coder Agent: Plan + feedback -> complete source files.

Information isolation: the Coder never sees test source code or raw pytest output.
It only receives the Plan, its own previous code, structured failure messages,
the Tester's attribution and the Reviewer's blocking comments. The one exception
is ablation E (config.coder_sees_tests), which deliberately exposes test files.
"""
import ast
import json
from typing import Dict, List, Optional, Tuple

from devcrew.llm import chat_json
from devcrew.schemas import AgentMessage, CoderOutput, Plan
from devcrew.state import DevState

SYSTEM_PROMPT = """You are DevCrew's senior Python engineer.
Implement exactly the functions in the specification, with the exact names and parameters.

Rules:
- Handle every acceptance criterion (AC-*) and edge case (EC-*).
- Do NOT special-case specific test inputs or hard-code expected outputs. Fix the general logic.
- Use only the Python standard library.
- Only write the files declared in the plan. Never write test files or conftest.py.
- Return complete file contents, not diffs. Files you omit keep their current content.
- In "notes", state briefly what you implemented or changed and why.
"""

MAX_ATTEMPTS = 3          # first answer + up to 2 self-check repairs
MAX_SUMMARY_CHARS = 200
BLOCKING_SEVERITIES = {"blocker", "major"}


# ---------- context ----------

def _dump_files(files: Dict[str, str]) -> str:
    return "\n\n".join(f"### {name}\n```python\n{content}\n```" for name, content in sorted(files.items()))


def build_context(state: DevState) -> str:
    """Build the Coder prompt from the fields the Coder is allowed to read."""
    mode = state["coder_mode"]
    cfg = state["config"]
    parts = [f"Mode: {mode}", "Specification (Plan):\n" + state["plan"].model_dump_json(indent=2)]

    if state["code_files"]:
        if mode == "write":
            parts.append("Previous implementation. The plan was revised; update it to match the new plan:\n"
                         + _dump_files(state["code_files"]))
        else:
            parts.append("Current implementation:\n" + _dump_files(state["code_files"]))

    if mode == "fix_tests":
        report = state["test_report"]
        failures = [f.model_dump() for f in report.failures]
        header = "Failed tests (you cannot see the test code):"
        if report.collection_error:
            header += "\nThe test file could not be loaded. Check that every planned function exists and imports work."
        parts.append(header + "\n" + json.dumps(failures, indent=2, ensure_ascii=False))
        attribution = state["attribution"]
        if cfg.use_attribution and attribution is not None:
            qa = {
                "verdict": attribution.verdict,
                "details": [d.model_dump() for d in attribution.details if d.verdict != "TEST_BUG"],
                "suggestion": attribution.suggestion,
            }
            parts.append("QA analysis:\n" + json.dumps(qa, indent=2, ensure_ascii=False))

    if mode == "fix_review":
        comments = [c.model_dump() for c in state["review"].comments if c.severity in BLOCKING_SEVERITIES]
        parts.append("Reviewer requested changes. Resolve every comment:\n"
                     + json.dumps(comments, indent=2, ensure_ascii=False))

    if cfg.coder_sees_tests and state["test_files"]:
        parts.append("Test files (visible only in ablation E):\n" + _dump_files(state["test_files"]))

    return "\n\n".join(parts)


# ---------- self-check ----------

def _params(fn: ast.FunctionDef) -> Tuple:
    a = fn.args
    return (
        [p.arg for p in a.posonlyargs + a.args],
        a.vararg.arg if a.vararg else None,
        [p.arg for p in a.kwonlyargs],
        a.kwarg.arg if a.kwarg else None,
    )


def _planned_function(signature: str) -> Optional[ast.FunctionDef]:
    try:
        node = ast.parse(signature.strip() + ": pass").body[0]
    except (SyntaxError, IndexError):
        return None
    return node if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else None


def disallowed_files(files: Dict[str, str], plan: Plan) -> List[str]:
    """Files the Coder must not write: undeclared, test files, conftest.py, or unsafe paths."""
    bad = []
    for name in files:
        base = name.replace("\\", "/").rsplit("/", 1)[-1]
        unsafe = name.startswith(("/", "\\")) or ".." in name.replace("\\", "/").split("/")
        if unsafe or name not in plan.files or base.startswith("test_") or base == "conftest.py":
            bad.append(name)
    return bad


def check_files(files: Dict[str, str], plan: Plan) -> List[str]:
    """Return deterministic problems in the merged code files; empty means OK."""
    errors = []
    trees = {}
    for name, source in files.items():
        if not name.endswith(".py"):
            continue
        try:
            trees[name] = ast.parse(source, filename=name)
        except SyntaxError as exc:
            errors.append(f"{name}: SyntaxError at line {exc.lineno}: {exc.msg}")

    for spec in plan.functions:
        if spec.file not in files:
            errors.append(f"{spec.file} is missing; it must define {spec.name}")
            continue
        tree = trees.get(spec.file)
        if tree is None:
            continue                       # syntax error already reported
        defined = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        if spec.name not in defined:
            errors.append(f"{spec.file} does not define top-level function {spec.name}")
            continue
        expected = _planned_function(spec.signature)
        if expected is not None and _params(defined[spec.name]) != _params(expected):
            errors.append(f"{spec.name} parameters do not match the plan signature: {spec.signature}")
    return errors


# ---------- node ----------

def _generate(state: DevState) -> Tuple[Dict[str, str], str, List[str], int, int]:
    """Ask the model, self-check, and retry. Returns (files, notes, errors, attempts, tokens)."""
    plan = state["plan"]
    context = build_context(state)
    prompt = context
    tokens = 0
    files, notes, errors = dict(state["code_files"]), "", []

    for attempt in range(1, MAX_ATTEMPTS + 1):
        out, used = chat_json(SYSTEM_PROMPT, prompt, CoderOutput, agent="coder")
        tokens += used
        rejected = disallowed_files(out.files, plan)
        accepted = {k: v for k, v in out.files.items() if k not in rejected}
        files = {**state["code_files"], **accepted}
        notes = out.notes
        errors = [f"not allowed to write {name}; only write {plan.files}" for name in rejected]
        errors += check_files(files, plan)
        if not errors:
            return files, notes, [], attempt, tokens
        prompt = (context
                  + "\n\nYour previous answer failed the self-check. Return corrected complete files."
                  + "\nProblems:\n- " + "\n- ".join(errors)
                  + "\nPrevious answer:\n" + _dump_files(out.files))

    # Still failing: hand the best effort to the sandbox so tests and attribution handle it
    return files, notes, errors, MAX_ATTEMPTS, tokens


def coder_node(state: DevState) -> dict:
    """Write or fix code. Registered as both the "coder" and "coder_fix" graph nodes."""
    mode = state["coder_mode"]
    files, notes, errors, attempts, tokens = _generate(state)
    summary = f"[{mode}] {notes}".strip()
    if errors:
        summary = f"[{mode}] self-check failed after {attempts} attempts: {errors[0]}"
    message = AgentMessage(
        node="coder" if mode == "write" else "coder_fix",
        sender="coder",
        receivers=["sandbox"],
        type="code",
        summary=summary[:MAX_SUMMARY_CHARS],
        payload={"mode": mode, "files": sorted(files), "notes": notes,
                 "attempts": attempts, "self_check_errors": errors},
        tokens=tokens,
        iteration=state["test_iters"],
    )
    return {"code_files": files, "trace": [message]}


CODER_NODES = {"coder": coder_node, "coder_fix": coder_node}
