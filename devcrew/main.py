"""命令行入口

    python main.py "add two numbers"                       # 全 mock，happy 场景，不需要 API key
    python main.py "add two numbers" --scenario stall      # 全 mock，指定场景
    python main.py "add two numbers" --coder real          # 只用真实 Coder，其余 mock
    python main.py "Implement add(a: int, b: int) -> int" --real   # 4 个真实 Agent（需要 .env 里的 API key）
"""
import argparse
from pathlib import Path

from devcrew.agents import ROLES, select_nodes
from devcrew.graph import RECURSION_LIMIT, build_graph
from devcrew.state import initial_state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("requirement")
    parser.add_argument("--scenario", default="happy",
                        help="mock scenario: happy, code_bug, test_bug, spec, review, stall")
    for role in ROLES:
        parser.add_argument(f"--{role}", choices=["mock", "real"], default="mock",
                            help=f"use the real {role.title()} agent")
    parser.add_argument("--real", action="store_true", help="use all four real agents")
    parser.add_argument("--task-id", default=None, help="name of the output folder under --out")
    parser.add_argument("--out", default="results/runs")
    args = parser.parse_args()

    real = set(ROLES) if args.real else {r for r in ROLES if getattr(args, r) == "real"}
    app = build_graph(select_nodes(real))
    task_id = args.task_id or ("real" if real == set(ROLES) else f"mock-{args.scenario}")
    final = app.invoke(initial_state(args.requirement, task_id=task_id),
                       config={"recursion_limit": RECURSION_LIMIT})

    out_dir = Path(args.out, task_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "trace.jsonl", "w") as f:
        for m in final["trace"]:
            f.write(m.model_dump_json() + "\n")
    for name, content in {**final["code_files"], **final["test_files"]}.items():
        (out_dir / Path(name).name).write_text(content)     # basename only: never write outside out_dir

    for m in final["trace"]:
        print(f"[{m.iteration}] {m.node:<12} {m.sender:>8} -> {','.join(m.receivers):<22} {m.summary}")
    print("final_status:", final["final_status"])
    print("output:", out_dir)


if __name__ == "__main__":
    main()
