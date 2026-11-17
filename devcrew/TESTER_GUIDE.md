# Tester Agent（小组 C 成员）

本提交只有以下功能：自动编写 pytest 测试、执行测试、分析失败原因、修复写错的测试。保留小组已定好的 LangGraph State 与 Schema，不另外使用 MCP。

## 文件

- `devcrew/agents/tester.py`：四个真实节点，提供 `TESTER_NODES`
- `devcrew/agents/__init__.py`：包初始化
- `tests/test_tester.py`：5 个本地测试

## 自测（在仓库 `devcrew/` 子目录中运行）

```bash
pip install -r requirements.txt
python -m pytest -q tests/test_tester.py
```

## 和组里的 LangGraph 集成

在负责组装流程的代码里，用下面两行把 Tester 的 Mock 替换掉，**无需编辑公共 State 和 Schema**：

```python
from devcrew.agents.tester import TESTER_NODES
nodes = {**MOCK_NODES, **TESTER_NODES}
app = build_graph(nodes)
```

`tester_write`、`attribute`、`tester_fix` 会调用组长约定的 `devcrew.llm.chat_json(system, user, schema, agent="tester")`。目前上传的仓库快照里还**没有** `devcrew/llm.py`，等组长提交后，才能用真实模型跑完整工作流。本地单元测试已用模拟模型响应验证接口，不需要 API key。

`run_tests` 使用仓库原有的 `devcrew/tools/sandbox.py` 实际执行 pytest，不调用大模型。

注意：当前沙箱仅是临时目录 + 超时，并非安全隔离环境。只运行课堂自己编写的可信演示代码，不要执行恶意或不可信的程序。
