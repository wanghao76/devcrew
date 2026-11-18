from types import SimpleNamespace

from devcrew.ui_adapter import StageProgress


def test_writing_tests_does_not_mark_tester_complete():
    progress = StageProgress()
    progress.start("tester_write")
    progress.complete("tester_write", {})
    assert progress.statuses["Tester"] == "running"
    assert progress.percent == 0
    progress.complete("run_tests", {"test_report": SimpleNamespace(all_passed=False)})
    assert progress.statuses["Tester"] == "failed"
    assert progress.percent == 0


def test_fix_invalidates_tests_and_review_until_rerun():
    progress = StageProgress()
    for node in ("planner", "coder"):
        progress.complete(node, {})
    progress.complete("run_tests", {"test_report": SimpleNamespace(all_passed=True)})
    progress.complete(
        "reviewer", {"review": SimpleNamespace(verdict="REQUEST_CHANGES")}
    )
    assert progress.percent == 75
    progress.start("coder_fix")
    assert progress.statuses["Tester"] == "waiting"
    assert progress.statuses["Reviewer"] == "waiting"
    assert progress.percent == 25
    progress.complete("coder_fix", {})
    assert progress.percent == 50
    progress.complete("run_tests", {"test_report": SimpleNamespace(all_passed=True)})
    progress.complete("reviewer", {"review": SimpleNamespace(verdict="APPROVE")})
    assert progress.percent == 100


def test_model_failure_does_not_light_reviewer_green():
    progress = StageProgress()
    progress.start("reviewer")
    progress.fail()
    assert progress.statuses["Reviewer"] == "failed"
    assert progress.percent == 0
