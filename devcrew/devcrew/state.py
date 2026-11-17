"""DevCrew 共享状态 v1.0

State 是 Agent 之间唯一的通信通道。每个节点读 State，返回要更新的字段。
每个字段只有一个"写入节点"，见 SCHEMA 文档第 4 节。
"""
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
    return DevState(
        task_id=task_id,
        requirement=requirement,
        config=config or RunConfig(),
        plan=None,
        code_files={},
        test_files={},
        test_report=None,
        attribution=None,
        review=None,
        coder_mode="write",
        test_iters=0,
        review_iters=0,
        replan_count=0,
        error_history=[],
        trace=[],
        final_status=None,
    )
