# DevCrew

This directory contains the runnable DevCrew graph and the real Planner implementation.
Coder, Tester attribution/fix, and Reviewer are still represented by mocks on this branch.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set either `OPENAI_API_KEY` or `DEEPSEEK_API_KEY` in `.env`.

## Run

Run the original all-mock workflow:

```bash
python main.py "add two numbers"
```

Run the real Planner with mock downstream Agents:

```bash
python main.py "Implement add(a, b) for integers" --planner real
```

The real Planner produces a schema-validated `Plan`, applies deterministic business-rule
validation, retries one invalid semantic result, writes a compact trace message, and then
fans out to the mock Coder and Tester through the existing LangGraph.

## Tests

```bash
pytest -q
```

Planner tests cover initial planning, semantic repair, fail-closed validation, replanning,
information isolation, the no-Planner ablation, and real-Planner/mock-downstream integration.
