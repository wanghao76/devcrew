"""命令行入口

    python main.py "add two numbers"                 # 全 mock，happy 场景
    python main.py "add two numbers" --scenario stall
"""
import argparse
from pathlib import Path

from devcrew.graph import RECURSION_LIMIT, build_graph
from devcrew.mocks import MOCK_NODES
from devcrew.state import initial_state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("requirement")
    parser.add_argument("--scenario", default="happy")
    parser.add_argument("--planner", choices=["mock", "real"], default="mock",
                        help="use the real Planner with mock downstream Agents")
    parser.add_argument("--out", default="results/runs")
    args = parser.parse_args()

    nodes = dict(MOCK_NODES)
    if args.planner == "real":
        from devcrew.agents.planner import planner_node
        nodes["planner"] = planner_node
    app = build_graph(nodes)
    task_id = f"mock-{args.scenario}"
    final = app.invoke(initial_state(args.requirement, task_id=task_id),
                       config={"recursion_limit": RECURSION_LIMIT})

    out_dir = Path(args.out, task_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "trace.jsonl", "w") as f:
        for m in final["trace"]:
            f.write(m.model_dump_json() + "\n")
    for name, content in final["code_files"].items():
        (out_dir / name).write_text(content)

    for m in final["trace"]:
        print(f"[{m.iteration}] {m.node:<12} {m.sender:>8} -> {','.join(m.receivers):<22} {m.summary}")
    print("final_status:", final["final_status"])


if __name__ == "__main__":
    main()
