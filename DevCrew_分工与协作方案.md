# DevCrew 分工与协作方案

> 配套文档：`DevCrew_方案.md`（总体方案）
> 分工：A = Planner，B = Coder，C = Tester，D = Reviewer
> 提交截止：2026-11-23 23:59

---

## 0. LangGraph 是什么

LangGraph 是一个 **Python 库**（`pip install langgraph`），由 LangChain 团队开发，用来把多个 Agent 编排成一张**流程图**：谁先执行、谁和谁并行、出现什么结果走哪条路。它不是独立软件，也不是 LLM，本身不调用模型，只负责调度你写的 Python 函数。

只需要理解三个概念：

| 概念 | 含义 | 在本项目里 |
|---|---|---|
| **State** | 所有 Agent 共享的一个字典 | `DevState`：需求、plan、代码、测试、报告、审查意见 |
| **Node** | 一个普通 Python 函数：读 State，返回要更新的字段 | 每个 Agent 就是一个 node，例如 `planner_node(state) -> dict` |
| **Edge** | 节点之间的连线；条件边根据 State 决定下一步 | "测试通过 → Reviewer，失败 → 错误归因" |

最小例子：

```python
from typing import TypedDict
from langgraph.graph import StateGraph, START, END

class S(TypedDict, total=False):
    x: int

def double(s): return {"x": s["x"] * 2}

g = StateGraph(S)
g.add_node("double", double)
g.add_edge(START, "double")
g.add_edge("double", END)
app = g.compile()
print(app.invoke({"x": 3}))   # {'x': 6}
```

**对分工的影响**：只有 A（负责 `graph.py`）需要深入理解 LangGraph，大约 1–2 小时上手。B、C、D 只需要按约定写一个函数 `xxx_node(state) -> dict`，完全不用碰 LangGraph API。

**已验证**：你电脑上的 Python 3.9.6 装 `langgraph 0.6.11` 后，`devcrew/` 目录下的 mock 骨架（4 个 Agent 用假数据代替）可以跑通，完整走完"测试失败 → 归因 → 修复 → 重测 → Review → APPROVE"。Python 3.9 不支持 `str | None` 写法，类型统一写成 `Optional[str]`。组员统一 Python 版本，建议都用 3.10 及以上。

**不想用 LangGraph 的备选**：用一个 `while` 循环加 `if/else` 手写调度，也能实现同样逻辑。但 LangGraph 能直接导出流程图（`app.get_graph().draw_mermaid()`）放进 slides，能并行执行 Coder 和 Tester，也能流式输出每一步给 UI，所以仍然推荐用。

---

## 1. 协作的三条原则

1. **契约先行**：第一天全员一起定好 `schemas.py`（消息格式）和 `state.py`（共享状态）。之后改动必须通知全组。
2. **每个 Agent 是一个函数**：输入 `DevState`，返回要更新的字段字典。Agent 之间不直接互相调用，全部通过 State 通信，由 `graph.py` 调度。
3. **Mock 先行**：A 第一天就用假 Agent 搭好能跑的图。每个人开发时，上下游都用 mock，不用等别人写完；自己的 Agent 写好后把 mock 换掉即可。

---

## 2. 共享契约：`devcrew/schemas.py`、`devcrew/state.py`

完整定义、字段归属、每个节点的接口契约和冻结流程见 **`DevCrew_Schema规范.md`**，代码在 `devcrew/devcrew/` 下，以代码为准。本节只列要点：

- 所有跨 Agent 的消息类都在 `schemas.py`，共享状态 `DevState` 在 `state.py`
- 每个 State 字段只有一个写入节点
- 模型只输出内容（`CoderOutput`、`TesterOutput`、`AttributionDraft`、`ReviewerLLMOutput`），归因结论和 Review 结论由代码计算
- `coder_mode` 字段告诉 Coder 这次是首次编写、修测试失败还是修审查意见
- `trace` 和 `error_history` 是追加型字段，节点只返回新增的条目
- 消融实验通过 `RunConfig` 切换

### 公共 LLM 接口：`devcrew/llm.py`（A 提供）

所有人只调用这两个函数，不直接调用 OpenAI SDK：

```python
def chat(system: str, user: str, *, agent: str) -> tuple[str, int]:
    """返回 (文本, token 数)。带磁盘缓存：相同 prompt 直接返回缓存结果。"""

def chat_json(system: str, user: str, schema: type[BaseModel], *, agent: str) -> tuple[BaseModel, int]:
    """要求模型输出 JSON，用 schema 校验；校验失败把错误信息发回模型重试，最多 2 次。"""
```

缓存键是 `sha1(model + system + user)`，缓存文件放 `.cache/llm/`。实验可复现，demo 录制时也不会出现意外。

---

## 3. Agent 之间如何通信

### 3.1 通信方式：共享 State（黑板模式）

Agent 之间不直接调用对方。每个 Agent 从 State 里读需要的字段，把结果写回 State，`graph.py` 根据 State 决定下一个执行谁。这样每个人的模块可以单独开发、单独测试。

### 3.2 字段读写权限（信息隔离在这里落实）

完整的字段归属表见 `DevCrew_Schema规范.md` 第 4 节。和信息隔离直接相关的两条：

- `tester_write` 不能读 `code_files`：Tester 只根据规格写测试
- `coder` / `coder_fix` 不能读 `test_files` 和 `test_report.raw_output`：Coder 只能看到失败信息，看不到测试源码

**落实方式**：每个 Agent 写一个 `build_context(state) -> str` 函数，只挑表里允许的字段拼 prompt。不靠模型自觉，靠代码保证。B 和 C 各写一个单元测试检查隔离：

```python
def test_coder_cannot_see_tests():
    state = make_state(test_files={"test_solution.py": "SECRET_TEST_MARKER"})
    assert "SECRET_TEST_MARKER" not in coder.build_context(state)
```

### 3.3 消息流

| 步骤 | 发送方 → 接收方 | 内容 | 触发条件 |
|---|---|---|---|
| 1 | Planner → Coder、Tester | `Plan` | 开始，或收到 `SPEC_AMBIGUITY` |
| 2a | Coder → Sandbox | `code_files` | 收到 Plan（与 2b 并行） |
| 2b | Tester → Sandbox | `test_files` | 收到 Plan（与 2a 并行） |
| 3 | Sandbox → Tester | `TestReport` | 2a、2b 都完成 |
| 4 | Tester → Coder / Tester / Planner | `Attribution` | 测试失败 |
| 5 | Coder → Sandbox | 修改后的 `code_files` | `CODE_BUG` 或 Review 要求修改 |
| 6 | Sandbox → Reviewer | 全部通过的 `TestReport` | 测试全部通过 |
| 7 | Reviewer → Coder / 结束 | `ReviewVerdict` | 收到通过的代码 |

### 3.4 Agent 函数的统一写法

```python
def coder_node(state: DevState) -> dict:
    ctx = build_context(state)                  # 按 state["coder_mode"] 拼不同的上下文
    out, tokens = chat_json(SYSTEM_PROMPT, ctx, CoderOutput, agent="coder")
    node = "coder" if state["coder_mode"] == "write" else "coder_fix"
    msg = AgentMessage(node=node, sender="coder", receivers=["sandbox"], type="code",
                       summary=f"[{state['coder_mode']}] {out.notes}", tokens=tokens,
                       iteration=state["test_iters"])
    return {"code_files": out.files, "trace": [msg]}     # 只返回要更新的字段
```

---

## 4. 怎么放在一起：`devcrew/graph.py`（A 负责）

代码在 `devcrew/devcrew/graph.py`，路由规则表见 `DevCrew_Schema规范.md` 第 6 节。结构如下：

```
START → planner → coder ∥ tester_write → run_tests
run_tests  → reviewer | attribute | coder_fix（关闭归因时）| finalize（轮数用完）
attribute  → planner（需求歧义或停滞）| tester_fix | coder_fix
coder_fix、tester_fix → run_tests
reviewer   → finalize | coder_fix
finalize   → END
```

`build_graph(nodes)` 接收一个 `{节点名: 函数}` 字典，mock 和真实 Agent 可以混用：`build_graph({**MOCK_NODES, "planner": planner_node})`。用 mock 跑 6 种场景的契约测试在 `devcrew/tests/test_contract.py`，已全部通过。

**踩过的坑**：修复路径如果直接回到 `coder` 节点，图会卡住不再执行。原因是汇合边 `["coder", "tester_write"] → run_tests` 要等两个节点都执行，修复时只有 Coder 执行。解决办法是把同一个函数注册成两个节点：`coder`（首次，走汇合边）和 `coder_fix`（修复，直接连 `run_tests`）。`coder_node` 内部根据 `state["coder_mode"]` 判断当前是首次编写还是修复。

**其他用法**：
- 给 UI 逐步输出：`for update in app.stream(inputs, stream_mode="updates"): ...`
- 导出流程图放 slides：`print(app.get_graph().draw_mermaid())`，粘贴到 mermaid.live 导出图片

---

## 5. A：Planner Agent

Planner 本身工作量最小，所以 A 同时负责公共基础设施（`schemas.py`、`llm.py`、`graph.py`、mock、停滞检测），是整个组的集成负责人。

### 5.1 职责

- 把自然语言需求变成结构化 `Plan`：文件、函数签名、验收标准（AC）、边界情况（EC）、假设。
- 收到 `SPEC_AMBIGUITY` 或停滞升级时**重新规划**：只改有问题的部分，`version + 1`，把澄清写进 `assumptions`。

### 5.2 输入 / 输出 / 工具

- 输入：`requirement`；重新规划时额外读 `plan`（旧版）和 `attribution.reasoning`
- 输出：`plan`、`trace`
- 工具：无 LLM 工具。输出后做一次**规则校验**：
  - 函数名是合法标识符：`name.isidentifier()`
  - 签名能解析：`ast.parse(signature + ": pass")`
  - 至少 3 条 AC、3 条 EC，id 不重复
  - 校验失败就把错误发回模型重试一次

### 5.3 Prompt 要点

```
You are a senior software architect. Turn the requirement into a precise spec. Do NOT write code.
- Give exact Python signatures with type hints.
- Number acceptance criteria AC-1, AC-2, ... Each must be testable with concrete input -> output.
- Number edge cases EC-1, EC-2, ... (empty input, boundaries, invalid types, large input).
- If the requirement is ambiguous, pick one interpretation and record it in "assumptions".
Output JSON matching the schema.
```

重新规划时追加：`The previous plan (v{n}) caused this ambiguity: {reasoning}. Revise only what is needed.`

### 5.4 公共基础设施（A 额外负责）

| 文件 | 内容 | 截止 |
|---|---|---|
| `schemas.py` / `state.py` | 已写好，见 `DevCrew_Schema规范.md`，会议确认后冻结 | 11/17 晚 |
| `mocks.py` | 已写好，6 种场景 | 11/17 晚 |
| `graph.py` | 已写好，契约测试通过 | 11/17 晚 |
| `llm.py` | `chat` / `chat_json` + 缓存 + token 统计 | 11/18 上午 |
| `main.py` | 已写好 mock 版本；11/18 加上切换真实 Agent 的参数 | 11/18 |

### 5.5 自测

- 3 个自定义任务各跑一次，人工检查 AC/EC 是否具体可测
- 构造一个歧义需求（例如"把列表排序"，没说升序还是降序），确认 `assumptions` 里写明了选择
- 构造一个 `attribution`，确认重新规划后 `version` 变成 2 且只改了相关条目

---

## 6. B：Coder Agent

B 额外负责评测框架和基线，因为 Coder 的单 Agent 版本就是基线 A、B 的核心。

### 6.1 职责

同一个 `coder_node` 有三种模式，由 `state["coder_mode"]` 决定（上游节点负责设置）：

| 模式 | 判断条件 | 额外上下文 |
|---|---|---|
| 首次编写 | `coder_mode == "write"`（planner 设置） | 只有 `plan` |
| 修测试失败 | `coder_mode == "fix_tests"`（run_tests 设置） | 当前代码 + `failures` + `attribution.suggestion`（关闭归因时没有） |
| 修审查意见 | `coder_mode == "fix_review"`（reviewer 设置） | 当前代码 + blocker/major 级别的 `comments` |

### 6.2 输入 / 输出 / 工具

- 输入：`plan`、`code_files`、`test_report.failures`、`attribution`、`review`
- **禁止读取**：`test_files`、`test_report.raw_output`
- 输出：`code_files`（每次输出完整文件内容，不做 diff，实现简单且不易出错）、`trace`
- 工具（Agent 内部的自检循环，不经过图）：
  1. `ast.parse` 检查语法
  2. 检查 plan 里每个函数都已定义且签名一致
  3. 不通过就把错误发回模型重试，最多 2 次，然后再交给 Sandbox

### 6.3 Prompt 要点

```
You are a senior Python engineer. Implement exactly the functions in the spec, with the exact signatures.
- Handle every edge case listed (EC-*).
- Do NOT special-case specific test inputs. Fix the general logic.
- Use only the Python standard library.
Return JSON: {"files": {"<filename>": "<full file content>"}, "notes": "<what you changed and why>"}
```

修复模式追加：`These tests failed (you cannot see the test code): {failures}. QA analysis: {suggestion}.`

`notes` 字段写进 `AgentMessage.summary`，UI 和视频里能看到 Coder 的修改理由。

### 6.4 评测框架（B 额外负责）

| 文件 | 内容 |
|---|---|
| `eval/baselines.py` | 配置 A（single-shot）、B（self-refine，同一个 LLM 自己生成测试再自己改，最多 3 轮） |
| `eval/run_benchmark.py` | `--config A..F --n 50 --seed 42`，加载 HumanEval+，逐题跑，结果写 `results/{config}.jsonl` |
| `eval/analyze.py` | 读结果，输出 pass@1、平均迭代、token、成本的表格和柱状图 |
| `RunConfig`（在 `schemas.py`） | 消融开关：`coder_sees_tests`（配置 E，B 实现）、`use_attribution`（配置 F，A 已实现）。评测脚本按配置构造 `RunConfig` 传给 `initial_state` |

HumanEval+ 用 `pip install evalplus`，`from evalplus.data import get_human_eval_plus` 加载题目。Agent 只拿题目的 `prompt` 字段。评分时把每题最终代码导出成 `samples.jsonl`（每行 `{"task_id": ..., "solution": ...}`），运行 `evalplus.evaluate --dataset humaneval --samples samples.jsonl`，用 EvalPlus 的隐藏测试打分。具体参数以 EvalPlus README 为准，11/18 先跑通一题确认。

### 6.5 自测

- 用 mock Plan 跑首次编写；用 mock 失败报告跑修复模式，确认代码变化合理
- 隔离单元测试（3.2 节）
- 11/19 晚用 5 道题跑一次 smoke test，确认评测流程通畅，再跑全量

---

## 7. C：Tester Agent

Tester 有 4 个节点，是工作量最大的角色，也是本项目创新点（信息隔离 + 错误归因）的主要承载者。

### 7.1 职责与节点

| 节点 | 做什么 | 能看到的信息 |
|---|---|---|
| `tester_write` | 只根据规格写 pytest 测试 | `plan`（**看不到代码**） |
| `run_tests` | 调用沙箱执行测试，生成 `TestReport`，更新 `test_iters` 和 `error_history` | 代码 + 测试（纯程序，不调 LLM） |
| `attribute` | 判断失败原因：`CODE_BUG` / `TEST_BUG` / `SPEC_AMBIGUITY` | `plan` + 代码 + 测试 + 失败信息 |
| `tester_fix` | 修正自己写错的测试 | `plan` + 测试 + `attribution` |

`run_tests` 已在 `devcrew/devcrew/mocks.py` 里写好真实实现，C 直接搬到 `agents/tester.py`。`error_history` 是追加型字段，只返回 `[签名]`。

### 7.2 测试命名约定（让程序能解析出对应的规格条目）

测试函数名必须是 `test_ac{n}_描述` 或 `test_ec{n}_描述`，例如 `test_ec2_empty_list`。沙箱据此填 `spec_ref = "EC-2"`，归因时直接找到对应规格原文。额外补充的边界测试用 `test_ex{n}_描述`。

### 7.3 Prompt 要点

写测试：

```
You are a QA engineer. You will NOT see the implementation.
Based ONLY on the specification, write pytest tests in test_solution.py:
1. One test per acceptance criterion, named test_ac<N>_<desc>
2. One test per edge case, named test_ec<N>_<desc>
3. At least 2 extra edge cases not in the spec, named test_ex<N>_<desc>
Import functions with: from solution import <name>
Compute expected values carefully by hand. Do not guess.
```

错误归因：

```
A test failed. Decide who is wrong, using the SPEC as the source of truth.
- CODE_BUG: the test matches the spec, the code does not.
- TEST_BUG: the code matches the spec, the test's expectation is wrong.
- SPEC_AMBIGUITY: the spec allows both readings.
Quote the spec item (AC-*/EC-*) you relied on. Return JSON per the Attribution schema.
```

**多个测试失败时**：逐个归因，再按优先级 `SPEC_AMBIGUITY > TEST_BUG > CODE_BUG` 决定整体结论。先修规格和测试，代价小，也避免 Coder 被错误的测试误导。

**规则兜底**：如果 `collection_error` 为真且报错指向测试文件自身（语法错误、导入了 plan 里没有的名字），直接判 `TEST_BUG`，不调 LLM。如果导入的名字在 plan 里但代码没实现，判 `CODE_BUG`。

### 7.4 沙箱：`devcrew/tools/sandbox.py`

以下代码已验证四种情况：断言失败、运行时异常、测试文件导入失败、死循环超时。

```python
import hashlib, re, subprocess, sys, tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from devcrew.schemas import TestFailure, TestReport

def _error_type(msg):
    # "TypeError: unsupported ..." -> TypeError；"assert -1 == 3" -> AssertionError
    if msg.startswith("assert"):
        return "AssertionError"
    head = msg.split(":", 1)[0]
    return head if head.isidentifier() else "Error"

def run_pytest(code_files, test_files, timeout=30):
    with tempfile.TemporaryDirectory() as d:          # 每次在独立临时目录执行
        for name, content in {**code_files, **test_files}.items():
            Path(d, name).write_text(content)
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "--tb=short", "-p", "no:cacheprovider",
                 "--junitxml=report.xml"],
                cwd=d, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return TestReport(all_passed=False, passed=0, failed=1, failures=[TestFailure(
                test_name="<timeout>", spec_ref="", error_type="Timeout",
                message=f"tests exceeded {timeout}s, possible infinite loop")], error_signature="timeout")
        xml_path = Path(d, "report.xml")
        if not xml_path.exists():
            return TestReport(all_passed=False, passed=0, failed=0, collection_error=True,
                              raw_output=proc.stdout + proc.stderr)
        root = ET.parse(xml_path).getroot()
        failures, passed, collection_error = [], 0, False
        for case in root.iter("testcase"):
            bad = case.find("failure")
            if bad is None:
                bad = case.find("error")
            if bad is None:
                if case.find("skipped") is None:
                    passed += 1
                continue
            name = case.get("name")
            m = re.match(r"test_(ac|ec)(\d+)", name)
            msg = bad.get("message", "")
            body = (bad.text or "").strip().splitlines()
            if msg == "collection failure":           # 测试文件导入失败
                collection_error = True
                msg = next((l[1:].strip() for l in reversed(body) if l.startswith("E ")), msg)
            # 只取 message 属性；bad.text 里含测试源码，不能给 Coder
            failures.append(TestFailure(
                test_name=name,
                spec_ref=f"{m.group(1).upper()}-{m.group(2)}" if m else "",
                error_type=_error_type(msg),
                message=msg[:500]))
        sig = hashlib.sha1("|".join(sorted(f"{f.test_name}:{f.error_type}" for f in failures)).encode()).hexdigest()[:12]
        return TestReport(all_passed=not failures and passed > 0, passed=passed, failed=len(failures),
                          collection_error=collection_error, failures=failures,
                          error_signature=sig if failures else "", raw_output=proc.stdout[-3000:])
```

Coder 收到的失败信息长这样，能看到输入和实际输出，看不到测试源码：

```
{'test_name': 'test_ac1_basic', 'spec_ref': 'AC-1', 'error_type': 'AssertionError',
 'message': 'assert -1 == 3\n +  where -1 = add(1, 2)'}
```

**安全说明**：临时目录 + 超时只能防止误操作和死循环，不能防恶意代码。演示和实验只跑自己的任务和 HumanEval+，风险可控。如果组里有人装了 Docker，可以改成 `docker run --rm --network none` 执行。

### 7.5 自测

- 用正确代码 + 错误测试，确认归因为 `TEST_BUG`；错误代码 + 正确测试，确认为 `CODE_BUG`
- 准备 10 个人工标注的失败样例，统计归因准确率，结果放进 slides 的 Analysis 部分
- 隔离单元测试：`tester_write` 的 prompt 里不包含代码

---

## 8. D：Reviewer Agent

D 额外负责 Streamlit UI 和 slides 主笔，因为 Reviewer 是流程终点，D 最清楚最终输出长什么样。

### 8.1 职责

测试全部通过后，检查测试覆盖不到的问题：是否完整实现规格、安全隐患、复杂度、可读性。输出结构化 `ReviewVerdict`。

### 8.2 两步审查：先工具，后 LLM

**第一步：静态分析**（`devcrew/tools/static_analysis.py`，纯程序）。以下命令已验证可输出 JSON：

| 工具 | 命令 | 取什么 |
|---|---|---|
| ruff | `ruff check --select E,F,B --output-format json <file>` | 问题数和位置（只选错误类规则，避免格式问题刷屏） |
| radon | `radon cc -j <file>` | 每个函数的圈复杂度 |
| bandit | `bandit -f json -q <file>` | 安全问题及严重度，例如 `shell=True` 是 HIGH |

**第二步：LLM 审查**。把 plan、代码、测试报告摘要、静态分析结果一起给模型。

**规则优先于 LLM**（保证结果稳定，也防止 Reviewer 无休止地挑刺）：

- bandit HIGH → 自动生成一条 `blocker`
- 圈复杂度 > 10 → 自动生成一条 `major`
- 最终 `verdict` 由代码计算：存在 `blocker` 或 `major` 才 `REQUEST_CHANGES`，只有 `minor` 时 `APPROVE`
- 第二轮审查只检查上一轮的 blocker/major 是否解决，不提新的 minor 意见，确保收敛

### 8.3 Prompt 要点

```
You are a strict but pragmatic code reviewer. All tests already pass.
Check, in order:
1. spec_mismatch: is every AC-*/EC-* actually handled? Cite the item id.
2. correctness: bugs the tests may have missed.
3. security / complexity: explain the static analysis findings that matter.
4. style: minor only.
Every comment must include file, line, and a concrete suggestion. Do not nitpick.
```

### 8.4 Streamlit UI：`app.py`（D 额外负责）

- 左栏：需求输入框、"Run" 按钮、配置选择（Full / 消融配置）、"缓存回放"开关
- 中栏：按时间顺序显示 `trace` 消息，每个 Agent 一种颜色，例如 Planner 蓝、Coder 绿、Tester 橙、Reviewer 紫
- 右栏：标签页显示当前 `plan`、代码、测试、测试报告、审查意见
- 顶部：当前所在节点、迭代次数、累计 token
- 实现：`for update in app.stream(inputs, stream_mode="updates")` 每拿到一个节点的输出就刷新页面

### 8.5 自测

- 构造一段含 `subprocess.call(x, shell=True)` 的代码，确认生成 blocker 且 verdict 为 `REQUEST_CHANGES`
- 构造一段干净代码，确认 `APPROVE`
- 确认第二轮审查不会提出新的 minor 意见导致死循环

---

## 9. 集成流程

### 9.1 Mock 替换顺序

1. **11/17 晚**：开会按 `DevCrew_Schema规范.md` 第 11 节确认并冻结 schema。mock 骨架已在 `devcrew/` 目录写好，A 提交到仓库，所有人拉代码，确认 `python main.py "add two numbers"` 和 `pytest tests` 在本地能跑。
2. **11/18**：每人在自己分支实现 Agent，用 `scripts/try_<agent>.py` 单独测试，上下游仍用 mock。
3. **11/19 上午，集成 1**：按 Planner → Coder → Tester → Reviewer 的顺序逐个替换 mock，每换一个跑一次。出问题立刻知道是谁的模块。
4. **11/19 下午，集成 2**：全真实 Agent 跑 3 个自定义任务，接上 UI。

### 9.2 集成验收清单

每条路由都要至少被触发一次。可以用 mock 强制制造对应情况：

- [ ] 一次通过：planner → coder ∥ tester → run_tests → reviewer → APPROVE
- [ ] `CODE_BUG` → coder_fix → 重测通过
- [ ] `TEST_BUG` → tester_fix → 重测通过
- [ ] `SPEC_AMBIGUITY` → planner 重新规划（`plan.version == 2`）→ Coder 和 Tester 重新并行
- [ ] 停滞检测：同一 `error_signature` 出现 2 次 → planner
- [ ] 达到 `MAX_TEST_ITERS` 后正常结束，不卡死
- [ ] Reviewer `REQUEST_CHANGES` → coder_fix → 重测 → 第二轮审查
- [ ] 两个隔离单元测试通过
- [ ] 打开缓存后，同一任务重跑结果完全一致

### 9.3 代码协作

- 一个 GitHub 私有仓库，每人一个分支：`feat/planner`、`feat/coder`、`feat/tester`、`feat/reviewer`
- 文件归属明确，几乎不会冲突：

| 成员 | 拥有的文件 |
|---|---|
| A | `schemas.py`、`state.py`、`llm.py`、`graph.py`、`mocks.py`、`main.py`、`agents/planner.py`、`tests/test_contract.py` |
| B | `agents/coder.py`、`eval/*` |
| C | `agents/tester.py`、`tools/sandbox.py` |
| D | `agents/reviewer.py`、`tools/static_analysis.py`、`app.py` |

- 修改 `schemas.py` 必须在群里说一声，由 A 合并
- 每天晚上 15 分钟同步：今天做完什么、明天做什么、卡在哪里

---

## 10. 每人每天的计划

| 日期 | A（Planner + 集成） | B（Coder + 评测） | C（Tester + 沙箱） | D（Reviewer + UI） |
|---|---|---|---|---|
| **11/17** | 起草 schemas；全员会议冻结；提交 mock 图 | 学 EvalPlus，跑通加载题目 | 写沙箱，跑通第 7.4 节代码 | 写静态分析封装 |
| **11/18** | `llm.py`；Planner + 规则校验；`main.py` | Coder 三种模式 + 自检循环；隔离单测 | `tester_write`、`run_tests` | Reviewer 两步审查 + 规则 |
| **11/19** | 主持集成 1、2；停滞检测；`USE_ATTRIBUTION` 开关 | 基线 A、B；`run_benchmark.py`；晚上 5 题 smoke test | `attribute`、`tester_fix`；隔离单测 | Streamlit UI |
| **11/20** | 修集成 bug；盯实验进度 | **跑 6 种配置全量实验** | 人工标注 10 个归因样例 | UI 打磨；slides 框架 |
| **11/21** | 导出流程图；写架构相关 slides | `analyze.py` 出图表；写结果 slides | 挑 3 个案例；写案例分析 slides | 整合 slides |
| **11/22** | 录自己部分的视频；写 README | 录视频；写贡献声明 | 录视频；写贡献声明 | 剪辑视频；写贡献声明 |
| **11/23** | 检查 zip 内容，**上午提交** | 复核 | 复核 | 复核 |

实验跑在 11/20，如果 11/19 晚集成没完成，这一天就是缓冲。实验最晚 11/21 上午必须开始。

---

## 11. 个人贡献声明模板

每人一段，说清楚两件事：自己做了什么、和谁的模块如何对接。

> **[姓名] — Tester Agent & Sandbox**
> 实现了 Tester Agent 的四个节点（测试编写、测试执行、错误归因、测试修复）和沙箱执行模块。测试编写只依赖 Planner 输出的 `Plan`，不读取 Coder 的代码，以保证测试独立。错误归因的结果通过 `Attribution` 路由给 Coder（CODE_BUG）、Planner（SPEC_AMBIGUITY）或 Tester 自身（TEST_BUG）。沙箱生成的 `TestReport` 过滤了测试源码，供 Coder 修复和 Reviewer 审查使用。此外标注了 10 个归因样例，用于评估归因准确率。

---

## 12. 环境准备（11/17 每人都做）

```bash
python3 --version          # 全组统一版本，建议 3.10+；3.9 也能跑，类型写 Optional[...]
python3 -m venv .venv && source .venv/bin/activate
pip install langgraph pydantic openai python-dotenv pytest ruff radon bandit evalplus streamlit
cp .env.example .env       # 填入 OPENAI_API_KEY 或 DEEPSEEK_API_KEY，.env 不要提交到 git
```

`.gitignore` 至少包含：`.env`、`.venv/`、`.cache/`、`__pycache__/`。
