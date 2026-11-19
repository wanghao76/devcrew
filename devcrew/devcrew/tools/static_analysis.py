"""Static-analysis gate for the DevCrew Reviewer.

The reviewed code is written into an isolated temporary directory.  The tools
inspect source only; this module never imports or executes reviewed code.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

from devcrew.schemas import StaticReport


def analyze_files(code_files: dict[str, str]) -> StaticReport:
    if not code_files:
        return StaticReport(
            findings=["static analysis skipped: no code files supplied"]
        )
    with tempfile.TemporaryDirectory(prefix="devcrew-review-") as directory:
        root = Path(directory)
        paths = [
            _write_safe(root, name, content) for name, content in code_files.items()
        ]
        python_paths = [
            path.relative_to(root).as_posix() for path in paths if path.suffix == ".py"
        ]
        if not python_paths:
            return StaticReport(
                findings=["static analysis skipped: no Python files supplied"]
            )
        ruff_count, ruff_notes = _ruff(root, python_paths)
        maximum, radon_notes = _radon(root, python_paths)
        high, medium, bandit_notes = _bandit(root, python_paths)
        return StaticReport(
            ruff_issues=ruff_count,
            max_complexity=maximum,
            bandit_high=high,
            bandit_medium=medium,
            findings=ruff_notes + radon_notes + bandit_notes,
        )


def _write_safe(root: Path, filename: str, content: str) -> Path:
    relative = PurePosixPath(filename.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe code file path: {filename}")
    path = root.joinpath(*relative.parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _run_json(command: list[str], root: Path) -> tuple[object | None, str | None]:
    # Run each tool from the current interpreter so it works without an activated venv.
    tool = command[0]
    try:
        result = subprocess.run(
            [sys.executable, "-m", *command], cwd=root, capture_output=True, text=True,
            timeout=30, check=False,
        )
    except subprocess.TimeoutExpired:
        return None, f"{tool} timed out after 30 seconds"
    if "No module named" in result.stderr:
        return None, f"{tool} unavailable"
    try:
        return json.loads(result.stdout or "{}"), None
    except json.JSONDecodeError:
        return None, f"{tool} returned non-JSON output"


def _ruff(root: Path, paths: list[str]) -> tuple[int, list[str]]:
    output, note = _run_json(
        ["ruff", "check", "--select", "E,F,B", "--output-format", "json", *paths], root
    )
    if note:
        return 0, [note]
    issues = output if isinstance(output, list) else []
    notes = [
        f"ruff:{item.get('filename', '')}:{item.get('location', {}).get('row', 0)} "
        f"{item.get('code', '')} {item.get('message', '')}"
        for item in issues
        if isinstance(item, dict)
    ]
    return len(issues), notes


def _radon(root: Path, paths: list[str]) -> tuple[int, list[str]]:
    output, note = _run_json(["radon", "cc", "-j", *paths], root)
    if note:
        return 0, [note]
    notes: list[str] = []
    values: list[int] = []
    if isinstance(output, dict):
        for filename, entries in output.items():
            if not isinstance(entries, list):
                continue
            for item in entries:
                if not isinstance(item, dict):
                    continue
                complexity = int(item.get("complexity", 0))
                values.append(complexity)
                if complexity > 10:
                    notes.append(
                        f"radon:{filename}:{item.get('lineno', 0)} "
                        f"{item.get('name', '<function>')} complexity={complexity}"
                    )
    return max(values, default=0), notes


def _bandit(root: Path, paths: list[str]) -> tuple[int, int, list[str]]:
    output, note = _run_json(["bandit", "-f", "json", "-q", *paths], root)
    if note:
        return 0, 0, [note]
    results = output.get("results", []) if isinstance(output, dict) else []
    high = [
        item
        for item in results
        if isinstance(item, dict) and item.get("issue_severity") == "HIGH"
    ]
    medium = [
        item
        for item in results
        if isinstance(item, dict) and item.get("issue_severity") == "MEDIUM"
    ]
    notes = [
        f"bandit_{item.get('issue_severity', '').lower()}:"
        f"{_normalise_filename(str(item.get('filename', '')))}:"
        f"{item.get('line_number', 0)} {item.get('test_id', '')} "
        f"{item.get('issue_text', '')}"
        for item in high + medium
    ]
    return len(high), len(medium), notes


def _normalise_filename(filename: str) -> str:
    return filename.replace("\\", "/").removeprefix("./")
