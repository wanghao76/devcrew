# DevCrew Schema 规范 v1.0

> 状态：**草案，待 11/17 晚全组会议确认后冻结**
> 负责人：A（Planner + 集成）
> 代码：`devcrew/devcrew/schemas.py`、`devcrew/devcrew/state.py`（以代码为准，本文档解释设计）
> 配套文档：`DevCrew_方案.md`、`DevCrew_分工与协作方案.md`

---

## 0. 现在的状态

之前分工文档第 2 节里的 schema 只是草稿，没有定稿，也缺了几块：LLM 输出格式、Coder 的模式信号、消融实验的配置、运行结束状态。本文档补齐了这些，并且附了一套**已经能跑的 mock 骨架**（`devcrew/` 目录），就是分工文档里"11/17 晚 A 提交全 mock 的图"那一步的产出。

已验证（Python 3.9.6，全新虚拟环境 `pip install -r requirements.txt` 后）：

- `python main.py "add two numbers"` 跑完，`final_status: approved`
- `pytest tests` 17 个契约测试全部通过，覆盖 6 种路由场景和消融开关

```bash
cd devcrew
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py "add two numbers"                    # 一次通过
python main.py "add two numbers" --scenario stall   # 停滞 -> 重新规划 -> 达到最大轮数
pytest tests                                        # 契约测试
```

可选场景：`happy`、`code_bug`、`test_bug`、`spec`、`review`、`stall`。每次运行在 `results/runs/mock-<场景>/` 下生成 `trace.jsonl` 和最终代码。

---

## 1. 设计原则

1. **State 是唯一通信通道**。Agent 之间不互相调用，只读写 State。
2. **每个字段只有一个写入节点**。出了问题能立刻定位是谁的模块。
3. **LLM 只出内容，决策由代码计算**。归因的整体结论、Review 是否通过，都由代码根据模型给出的明细计算，不让模型直接决定路由。结果更稳定，也方便做实验分析。
4. **消融实验只改配置，不改代码**。6 种实验配置都通过 `RunConfig` 切换。
5. **兼容 Python 3.9**。类型写 `Optional[X]`、`List[X]`，不写 `X | None`。

---

## 2. 目录结构

```
devcrew/
├── requirements.txt
├── .gitignore
├── main.py                    # 命令行入口（A）
├── devcrew/
│   ├── schemas.py             # 所有消息格式（A，全组评审）
│   ├── state.py               # 共享状态 DevState（A，全组评审）
│   ├── graph.py               # 流程编排和路由（A）
│   ├── mocks.py               # mock Agent + run_tests_node 真实实现（A）
│   ├── tools/sandbox.py       # pytest 沙箱（C，已写好）
│   └── agents/                # 各人开发：planner.py / coder.py / tester.py / reviewer.py
└── tests/test_contract.py     # 契约测试：改 schema、state、graph 后必须全过
```

`agents/` 目录还不存在，各人开发时自己创建。

---

## 3. 消息总览

| 类 | 谁产生 | 谁消费 | 是否给 LLM 当输出格式 |
|---|---|---|---|
| `Plan`（含 `SpecItem`、`FunctionSpec`） | Planner | Coder、Tester、Reviewer | 是 |
| `CoderOutput` | Coder 的 LLM | Coder 节点内部，转成 `code_files` | 是 |
| `TesterOutput` | Tester 的 LLM | Tester 节点内部，转成 `test_files` | 是 |
| `TestReport`（含 `TestFailure`） | 沙箱 | Tester、Coder、Reviewer、路由 | 否，程序生成 |
| `AttributionDraft`（含 `FailureVerdict`） | Tester 的 LLM | Tester 节点内部 | 是 |
| `Attribution` | Tester，由 `Attribution.from_draft()` 计算 | Coder、Planner、Tester、路由 | 否 |
| `ReviewerLLMOutput`（含 `ReviewComment`） | Reviewer 的 LLM | Reviewer 节点内部 | 是 |
| `StaticReport` | 静态分析工具 | Reviewer | 否，程序生成 |
| `ReviewVerdict` | Reviewer，由 `ReviewVerdict.from_comments()` 计算 | Coder、路由 | 否 |
| `AgentMessage` | 所有节点 | UI、`trace.jsonl`、实验分析 | 否 |
| `RunConfig` | `main.py` / 评测脚本 | 所有节点、路由 | 否 |

给 LLM 当输出格式的类，用 `Cls.model_json_schema()` 生成 JSON schema 放进 prompt，再用 `Cls.model_validate_json(text)` 校验模型输出。

---

## 4. State 字段归属（最重要的一张表）

| 字段 | 唯一写入节点 | 可读节点 | 禁止读取 |
|---|---|---|---|
| `task_id`、`requirement`、`config` | 初始化（`initial_state`） | 所有 | — |
| `plan` | planner | coder、tester_write、attribute、tester_fix、reviewer | — |
| `replan_count` | planner | 路由 | — |
| `code_files` | coder / coder_fix | run_tests、attribute、reviewer | **tester_write** |
| `test_files` | tester_write / tester_fix | run_tests、attribute、reviewer | **coder / coder_fix**（除非 `config.coder_sees_tests`） |
| `test_report` | run_tests | attribute、coder_fix、reviewer、路由 | `raw_output` 子字段禁止给 coder |
| `test_iters`、`error_history` | run_tests | 路由 | — |
| `attribution` | attribute | coder_fix、planner、tester_fix、路由 | — |
| `review`、`review_iters` | reviewer | coder_fix、路由 | — |
| `coder_mode` | planner（`write`）、run_tests（`fix_tests`）、reviewer（`fix_review`） | coder / coder_fix | — |
| `trace` | 所有节点追加 | UI、评测脚本 | — |
| `final_status` | finalize | `main.py`、评测脚本 | — |

`coder_mode` 是唯一由多个节点写入的字段。它们在流程上不会同时执行，所以不会冲突。

---

## 5. 每个节点的接口契约

每个节点都是 `def xxx_node(state: DevState) -> dict`，**只返回要更新的字段**，并且必须返回一条 `trace`。

| 节点 | 负责人 | 必须返回的字段 | 备注 |
|---|---|---|---|
| `planner` | A | `plan`、`coder_mode="write"`、`replan_count`、`trace` | 重新规划时 `version = 旧版 + 1`，`replan_count + 1`。`config.use_planner=False` 时把原始需求包成一个只有 summary 和函数签名的 Plan |
| `coder`、`coder_fix` | B | `code_files`、`trace` | 同一个函数注册成两个节点。按 `coder_mode` 决定是首次编写还是修复 |
| `tester_write` | C | `test_files`、`trace` | 只读 `plan` |
| `run_tests` | C | `test_report`、`test_iters + 1`、`trace`；失败时加 `coder_mode="fix_tests"` 和 `error_history=[签名]` | `mocks.py` 里已经是真实实现，C 直接搬走 |
| `attribute` | C | `attribution`、`trace` | 用 `Attribution.from_draft()` 算整体结论。规则直接判定时设 `by_rule=True` |
| `tester_fix` | C | `test_files`、`trace` | 读 `attribution.details` 里 `TEST_BUG` 的条目 |
| `reviewer` | D | `review`、`review_iters + 1`、`trace`；不通过时加 `coder_mode="fix_review"` | 用 `ReviewVerdict.from_comments()` 算结论。`config.use_reviewer=False` 时直接返回 APPROVE |
| `finalize` | A（已写好） | `final_status`、`trace` | 在 `graph.py` 里 |

### `trace` 消息怎么写

```python
AgentMessage(
    node="coder_fix",                 # 图节点名
    sender="coder",
    receivers=["sandbox"],
    type="code",
    summary="[fix_tests] handle empty list in EC-2",   # 一句话，UI 和视频里显示
    payload={"notes": out.notes},     # 可选，放 UI 需要展示的内容
    tokens=tokens,                    # chat_json 返回的 token 数
    iteration=state["test_iters"],
)
```

`payload` 只放 UI 需要展示的内容，避免 `trace.jsonl` 过大。Agent 构造 prompt 时不读 `trace`，所以 `trace` 不影响信息隔离。

---

## 6. 路由规则（`graph.py`，A 负责）

| 节点结束后 | 条件 | 去向 |
|---|---|---|
| `run_tests` | 全部通过 | `reviewer` |
| | `test_iters >= max_test_iters` | `finalize` |
| | `use_attribution=False`（配置 F） | `coder_fix` |
| | 其他 | `attribute` |
| `attribute` | 还能重新规划，且（`SPEC_AMBIGUITY` 或停滞） | `planner` |
| | `TEST_BUG` | `tester_fix` |
| | 其他（`CODE_BUG`，或重新规划次数已用完） | `coder_fix` |
| `reviewer` | `APPROVE` 或 `review_iters >= max_review_iters` | `finalize` |
| | 其他 | `coder_fix` |

停滞的定义：当前 `error_signature` 在 `error_history` 里出现次数 `>= stall_threshold`（默认 2）。

`final_status` 的三种取值：`approved`（测试通过且 Review 通过）、`max_test_iters`（测试轮数用完仍失败）、`max_review_iters`（测试通过但 Review 轮数用完仍不通过）。

---

## 7. 相比分工文档第 2 节草稿的改动

| 改动 | 原因 |
|---|---|
| 新增 `CoderOutput`、`TesterOutput`、`AttributionDraft`、`ReviewerLLMOutput` | 把"模型输出的格式"和"State 里传递的消息"分开。模型只负责填内容 |
| `Attribution.target_tests` 改成 `details: List[FailureVerdict]`，整体 `verdict` 由 `from_draft()` 按优先级计算 | 多个测试失败时每个单独归因，再统一定结论，规则写在代码里 |
| `Attribution` 新增 `by_rule` | 区分规则判定和 LLM 判定，实验时可以分别统计 |
| `ReviewVerdict.metrics: dict` 改成 `static: StaticReport`，`verdict` 由 `from_comments()` 计算 | 字段有类型，UI 和分析脚本不用猜 key；有 blocker/major 才不通过 |
| `ReviewComment` 新增 `source`，`line` 改成 `int`（0 表示整个文件） | 区分规则产生和 LLM 产生的意见；少一个 Optional |
| `AgentMessage` 新增 `node`、`iteration`，`receiver` 改成 `receivers` 列表 | Planner 同时发给 Coder 和 Tester；UI 要显示是第几轮 |
| State 新增 `coder_mode` | 原来让 Coder 自己猜模式，Review 修复后又测试失败时会猜错 |
| State 新增 `task_id`、`config`、`replan_count`、`final_status` | 评测要按题目记录结果；消融开关；限制重新规划次数；记录结束原因 |
| `error_history` 改成追加型字段 | `run_tests` 只返回 `[签名]`，不用自己拼列表，少一个出错点 |
| 新增 `RunConfig` | 6 种实验配置都通过它切换，评测时可以并行跑不同配置 |
| 新增 `finalize` 节点 | 统一写 `final_status`，三种结束路径都经过它 |
| `RECURSION_LIMIT = 100` | LangGraph 默认最多 25 步，`stall` 场景已经经过 16 个节点，真实运行加上 Review 循环可能超过 25 |
| `TestFailure`、`TestReport`、`TesterOutput` 加 `__test__ = False` | 类名以 `Test` 开头，pytest 会误以为是测试类并报警告 |

---

## 8. 代码：`devcrew/devcrew/state.py`

```python
import operator
from typing import Annotated, Dict, List, Literal, Optional, TypedDict

from devcrew.schemas import Attribution, AgentMessage, Plan, ReviewVerdict, RunConfig, TestReport

CoderMode = Literal["write", "fix_tests", "fix_review"]
FinalStatus = Literal["approved", "max_test_iters", "max_review_iters"]


class DevState(TypedDict, total=False):
    # 输入
    task_id: str
    requirement: str
    config: RunConfig
    # 产物
    plan: Optional[Plan]
    code_files: Dict[str, str]        # {"solution.py": "..."}
    test_files: Dict[str, str]        # {"test_solution.py": "..."}
    # 反馈
    test_report: Optional[TestReport]
    attribution: Optional[Attribution]
    review: Optional[ReviewVerdict]
    coder_mode: CoderMode             # 告诉 Coder 这次是首次编写、修测试失败还是修审查意见
    # 计数器
    test_iters: int
    review_iters: int
    replan_count: int
    # 追加型字段：节点返回的列表会拼接到已有列表后面，不会覆盖
    error_history: Annotated[List[str], operator.add]
    trace: Annotated[List[AgentMessage], operator.add]
    # 输出
    final_status: Optional[FinalStatus]


def initial_state(requirement: str, task_id: str = "adhoc", config: Optional[RunConfig] = None) -> DevState:
    """所有字段都有初始值，节点里可以直接用 state["xxx"]，不用 .get()。"""
```

---

## 9. 代码：`devcrew/devcrew/schemas.py`

```python
from typing import Dict, List, Literal
from pydantic import BaseModel, Field

AgentName = Literal["user", "planner", "coder", "tester", "sandbox", "reviewer", "system"]
Verdict = Literal["CODE_BUG", "TEST_BUG", "SPEC_AMBIGUITY"]

# 多个失败的归因结论不同时，按此优先级取整体结论：先修规格，再修测试，最后修代码
VERDICT_PRIORITY: Dict[str, int] = {"SPEC_AMBIGUITY": 0, "TEST_BUG": 1, "CODE_BUG": 2}


# ---------- Planner ----------

class SpecItem(BaseModel):
    id: str = Field(pattern=r"^(AC|EC)-\d+$")   # "AC-1" 验收标准 / "EC-1" 边界情况
    text: str                                    # 必须可测，例如 "add(1, 2) returns 3"


class FunctionSpec(BaseModel):
    name: str                     # "add"
    signature: str                # "def add(a: int, b: int) -> int"
    description: str
    file: str = "solution.py"


class Plan(BaseModel):
    """[LLM] Planner 的输出。version 由代码设置，模型输出的值会被覆盖。"""
    version: int = 1
    summary: str
    files: List[str]
    functions: List[FunctionSpec]
    acceptance_criteria: List[SpecItem]
    edge_cases: List[SpecItem]
    assumptions: List[str] = Field(default_factory=list)   # 对需求歧义做出的明确假设


# ---------- Coder ----------

class CoderOutput(BaseModel):
    """[LLM] Coder 的输出。每次给出完整文件内容，不给 diff。"""
    files: Dict[str, str]         # {"solution.py": "<full content>"}
    notes: str                    # 改了什么、为什么，显示在 UI 里


# ---------- Tester ----------

class TesterOutput(BaseModel):
    """[LLM] Tester 写测试或修测试的输出。测试函数名必须是 test_ac<N>_* / test_ec<N>_* / test_ex<N>_*。"""
    __test__ = False
    files: Dict[str, str]         # {"test_solution.py": "<full content>"}
    notes: str
```

```python
class TestFailure(BaseModel):
    __test__ = False              # 告诉 pytest 这不是测试类
    test_name: str                # "test_ec2_empty_list"
    spec_ref: str                 # "EC-2"，沙箱从测试函数名解析；test_ex* 为空
    error_type: str               # "AssertionError" / "TypeError" / "Timeout"
    message: str                  # 断言信息，不含测试源码，可以给 Coder 看


class TestReport(BaseModel):
    """沙箱生成，不经过 LLM。"""
    __test__ = False
    all_passed: bool
    passed: int
    failed: int
    collection_error: bool = False                  # 测试文件本身无法加载
    failures: List[TestFailure] = Field(default_factory=list)
    error_signature: str = ""                       # 失败集合的哈希，用于停滞检测
    raw_output: str = ""                            # 含测试源码，只给 UI，禁止给 Coder


class FailureVerdict(BaseModel):
    test_name: str
    verdict: Verdict
    spec_ref: str                 # 判断依据的规格条目
    reasoning: str


class AttributionDraft(BaseModel):
    """[LLM] 模型对每个失败测试逐个归因。整体结论由代码计算，不让模型决定。"""
    details: List[FailureVerdict]
    suggestion: str               # 给下游 Agent 的具体修改建议


class Attribution(BaseModel):
    verdict: Verdict              # 整体结论，决定路由
    details: List[FailureVerdict]
    suggestion: str
    by_rule: bool = False         # True 表示由规则直接判定（如测试文件语法错误），没调 LLM

    @classmethod
    def from_draft(cls, draft: AttributionDraft) -> "Attribution":
        # details 为空时（例如 pytest 整体崩溃）默认交给 Coder
        verdict = min((d.verdict for d in draft.details), key=VERDICT_PRIORITY.__getitem__, default="CODE_BUG")
        return cls(verdict=verdict, details=draft.details, suggestion=draft.suggestion)
```

```python
# ---------- Reviewer ----------

class ReviewComment(BaseModel):
    severity: Literal["blocker", "major", "minor"]
    category: Literal["correctness", "spec_mismatch", "security", "complexity", "style"]
    file: str
    line: int = 0                 # 0 表示针对整个文件
    comment: str
    suggestion: str
    source: Literal["rule", "llm"] = "llm"


class ReviewerLLMOutput(BaseModel):
    """[LLM] 模型只给意见，verdict 由代码根据 severity 计算。"""
    comments: List[ReviewComment]


class StaticReport(BaseModel):
    """静态分析结果，不经过 LLM。"""
    ruff_issues: int = 0
    max_complexity: int = 0
    bandit_high: int = 0
    bandit_medium: int = 0
    findings: List[str] = Field(default_factory=list)   # 每条一行，例如 "solution.py:6 B602 shell=True"


class ReviewVerdict(BaseModel):
    verdict: Literal["APPROVE", "REQUEST_CHANGES"]
    comments: List[ReviewComment] = Field(default_factory=list)
    static: StaticReport = Field(default_factory=StaticReport)

    @classmethod
    def from_comments(cls, comments: List[ReviewComment], static: StaticReport) -> "ReviewVerdict":
        blocking = any(c.severity in ("blocker", "major") for c in comments)
        return cls(verdict="REQUEST_CHANGES" if blocking else "APPROVE", comments=comments, static=static)


# ---------- 公共 ----------

class AgentMessage(BaseModel):
    """每个节点每次执行写一条，用于 UI、trace.jsonl 和实验分析。"""
    node: str                     # 图节点名，例如 "coder_fix"
    sender: AgentName
    receivers: List[AgentName]
    type: Literal["plan", "code", "tests", "test_report", "attribution", "review", "final"]
    summary: str                  # 一句话，UI 和视频里展示
    payload: dict = Field(default_factory=dict)
    tokens: int = 0
    iteration: int = 0            # 写这条消息时的 test_iters
```

```python
class RunConfig(BaseModel):
    """一次运行的配置。消融实验通过它切换，不改代码。"""
    max_test_iters: int = 4
    max_review_iters: int = 2
    stall_threshold: int = 2      # 同一 error_signature 出现几次算停滞
    max_replans: int = 1          # Planner 最多重新规划几次
    use_planner: bool = True      # 配置 C 设为 False：Plan 只包一层原始需求
    use_reviewer: bool = True     # 配置 C 设为 False：直接 APPROVE
    use_attribution: bool = True  # 配置 F 设为 False：测试失败直接交给 Coder
    coder_sees_tests: bool = False  # 配置 E 设为 True：Coder 能看到测试源码
```

### 实验配置对应关系

| 实验配置 | `RunConfig` | 谁实现开关 |
|---|---|---|
| A. Single-shot | 不走图，`eval/baselines.py` | B |
| B. Self-refine | 不走图，`eval/baselines.py` | B |
| C. Coder + Tester | `use_planner=False, use_reviewer=False` | A（planner）、D（reviewer） |
| D. Full DevCrew | 默认值 | — |
| E. 去掉信息隔离 | `coder_sees_tests=True` | B（coder 的 `build_context`） |
| F. 去掉错误归因 | `use_attribution=False` | A（已在路由里实现，有契约测试） |

---

## 10. 组员怎么开始开发

1. 拉代码，跑 `python main.py "add two numbers"` 和 `pytest tests`，确认本地环境没问题。
2. 新建自己的文件，例如 B 建 `devcrew/agents/coder.py`，实现 `coder_node(state) -> dict`，返回字段按第 5 节。
3. 单独调试时只替换自己的节点，其他仍用 mock：

```python
from devcrew.graph import RECURSION_LIMIT, build_graph
from devcrew.mocks import MOCK_NODES
from devcrew.state import initial_state
from devcrew.agents.coder import coder_node

app = build_graph({**MOCK_NODES, "coder": coder_node, "coder_fix": coder_node})
final = app.invoke(initial_state("add two numbers"), config={"recursion_limit": RECURSION_LIMIT})
```

4. 提交前跑 `pytest tests`。契约测试用的是 mock，不受你的 Agent 影响，但能发现你是否改坏了公共文件。
5. 不要在自己的 Agent 文件里定义新的跨 Agent 消息类。需要新字段就按第 11 节的流程提。

注意：mock 场景由 `task_id` 的前缀 `mock-<场景>` 控制，真实 Agent 不要依赖 `task_id` 的格式。

---

## 11. 冻结流程

### 11/17 晚会议（30 分钟）要确认的问题

- [ ] 第 4 节字段归属表，每人确认自己节点要读写的字段够用
- [ ] 第 5 节接口契约，每人确认自己节点必须返回的字段
- [ ] `RunConfig` 默认值：测试最多 4 轮、Review 最多 2 轮、停滞阈值 2、最多重新规划 1 次
- [ ] 测试命名约定 `test_ac<N>_*` / `test_ec<N>_*` / `test_ex<N>_*`（C 和 A 确认）
- [ ] Review 判定规则：有 blocker 或 major 才不通过（D 确认）
- [ ] 归因优先级：`SPEC_AMBIGUITY > TEST_BUG > CODE_BUG`（C 确认）

全部打勾后，把文档顶部状态改成"**v1.0 已冻结（日期）**"，A 提交到主分支，组员开始开发。

### 冻结后怎么改

1. 在群里说明要改什么、为什么改，影响谁的模块
2. A 修改 `schemas.py` / `state.py`，同步更新本文档第 4、5 节，版本号加 0.1
3. `pytest tests` 全部通过后合并，通知全组拉代码

只加带默认值的新字段，不影响其他人，可以直接改，事后通知。删字段、改字段类型、改字段含义，必须先在群里确认。
