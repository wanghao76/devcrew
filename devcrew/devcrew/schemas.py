"""DevCrew 共享消息格式 v1.0

所有 Agent 之间传递的数据都在这里定义。修改前先在群里说明，由 A 合并。
带 [LLM] 标记的类会作为 JSON schema 发给模型，模型的输出必须符合它。
"""
from typing import Dict, List, Literal

from pydantic import BaseModel, Field, field_validator

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

    @field_validator("signature")
    @classmethod
    def _strip_trailing_colon(cls, v: str) -> str:
        # 模型常写成 "def f(x) -> int:"，统一去掉结尾冒号，方便 ast 解析
        return v.strip().rstrip(":").rstrip()


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
