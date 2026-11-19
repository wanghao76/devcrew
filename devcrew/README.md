# DevCrew

DevCrew is a LangGraph-based multi-agent Python development workflow:

```text
Planner -> Coder + Tester -> Sandbox -> Reviewer
                    ^                    |
                    |---- Coder fix -----|
```

The graph only approves a task when tests pass and the Reviewer returns
`APPROVE`. A reviewer rejection routes through `coder_fix -> run_tests ->
reviewer`, so repaired code is always retested before re-review.

## Run locally

```powershell
cd devcrew
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `OPENAI_API_KEY` (or `DEEPSEEK_API_KEY`) in `.env`. The Reviewer uses the
shared LLM wrapper and runs Ruff, Radon, and Bandit before semantic review.

Run the mock graph:

```powershell
python main.py "Implement a function that adds two integers"
pytest tests -q
```

Run the Streamlit UI:

```powershell
streamlit run app.py
```

The current UI reviews a prepared addition example: the plan, implementation,
and test-writing are supplied by mock nodes. Pytest, static analysis, and the
LLM Reviewer run for real. The downloaded `solution.py` is the example code;
custom requirements will be supported after the other agents are integrated.

`devcrew/ui_adapter.py` owns the temporary example input and node bindings,
keeping them separate from the UI and the shared graph. Replace those bindings
and the example input when the real agents are ready.

The single-page UI provides four-stage progress indicators, a 420px scrolling
execution timeline, result tabs, and a direct solution download. After a code
fix, the progress indicators invalidate the previous test and review results
until testing and review run again.

The UI loads its project-local `.env` in preference to inherited environment
values. For an OpenAI-compatible provider, set `OPENAI_API_KEY`,
`OPENAI_BASE_URL`, and `OPENAI_MODEL` (or `DEVCREW_MODEL`, which takes priority).
Credentials and model response caches are local and must not be committed.

## Reviewer contract

`devcrew.agents.reviewer.reviewer_node` reads `plan`, `code_files`,
`test_report`, the prior `review`, and iteration counters. It returns only the
Reviewer-owned fields: `review`, `review_iters`, `trace`, and (when needed)
`coder_mode="fix_review"`.

Static gates are deterministic:

- Bandit HIGH -> blocker -> `REQUEST_CHANGES`;
- Radon complexity above 10 -> major -> `REQUEST_CHANGES`;
- a follow-up review suppresses new minor comments but keeps every blocker or
  major regression actionable.

Never commit `.env` or cached LLM responses.
