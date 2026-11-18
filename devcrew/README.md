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

The current UI uses upstream mock nodes until the group replaces them with the
real Planner, Coder, and Tester nodes. Its Reviewer node is real. The UI reads
graph updates and Shared State; when real nodes are supplied, only the node map
needs to change.

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
