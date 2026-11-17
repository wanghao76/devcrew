# DevCrew：由 Planner、Coder、Tester、Reviewer 组成的多 Agent 软件开发系统

> COMP5584 Group Project 方案
> Topic：Software Development and Coding
> 提交截止：**2026-11-23 23:59**（Canvas，一人代表全组提交）

---

## 一、对准评分标准

指南原文："A technically complicated system does not necessarily receive a higher score. Greater emphasis will be placed on whether the multi-agent design is well motivated, clearly implemented, and genuinely contributes to solving the selected task."

所以重点放在**为什么必须拆成多个 Agent**，以及**用实验证明拆分有用**，不在功能堆砌。

| 评分项 | 权重 | 本方案的得分点 |
|---|---|---|
| Problem & Motivation | 15% | 单个 LLM 写代码的三类问题：漏掉边界情况、自己验证自己（确认偏差）、针对测试过拟合 |
| MAS Design | 30% | 信息隔离、各 Agent 工具不同、两条反馈回路、错误归因机制、终止策略 |
| Implementation | 25% | LangGraph 状态机、真实 pytest 沙箱、结构化消息、可视化 UI |
| Analysis & Innovation | 15% | 消融实验（6 种配置）、失败案例分析、错误归因的作用 |
| Presentation | 15% | 实时展示 Agent 对话的 Streamlit UI，视频脚本按时间分段 |

---

## 二、核心设计：每个 Agent 的必要性

一个常见的坑是做成"4 个 prompt 串起来调用"，这正是指南说的 "simply invoking multiple LLMs independently"。本方案用三个设计点让每个角色都有存在的理由。

### 设计点 1：信息隔离

- **Tester 只看需求规格（Planner 的输出），不看代码**来写测试。测试独立于实现，避免"自己写代码自己出题"的确认偏差。
- **Coder 看不到测试源码**，只拿到失败时的 traceback 和断言信息，防止 Coder 为通过测试而硬编码（overfitting to tests）。
- 这两点在单 Agent 架构里做不到，可以直接作为 motivation 的论据。

### 设计点 2：错误归因（创新点）

测试失败时，错误不一定在代码里，LLM 写的测试本身也可能是错的。一般的 Coder-Tester 循环会让 Coder 去"修"本来正确的代码，结果越改越错。

本方案在测试失败后加一步 **Fault Attribution**：Tester 此时可以看到代码，对照规格判断错误属于 `CODE_BUG`、`TEST_BUG` 还是 `SPEC_AMBIGUITY`，再分别路由给 Coder、Tester 自己或 Planner。

### 设计点 3：工具不同

| Agent | 能看到的信息 | 可用工具 | 输出 |
|---|---|---|---|
| **Planner** | 用户需求 | 无（纯推理） | `plan.json`：模块、函数签名、验收标准、边界情况 |
| **Coder** | plan + 失败 traceback + Reviewer 意见 | `write_file`、`read_file`、语法检查 | 源代码文件 |
| **Tester** | plan（写测试时）；plan + 代码（归因时） | `write_test`、`run_pytest`（沙箱） | 测试文件、测试报告、归因结果 |
| **Reviewer** | plan + 代码 + 测试报告 + 静态分析结果 | `ruff`（lint）、`radon`（圈复杂度）、`bandit`（安全） | 结构化 verdict：APPROVE / REQUEST_CHANGES + 逐条意见 |

---

## 三、系统架构

```
用户需求
   │
   ▼
┌─────────┐   plan.json（规格 + 验收标准 + 边界情况）
│ Planner │──────────────┬──────────────────┐
└─────────┘              ▼                  ▼
     ▲             ┌─────────┐        ┌─────────┐
     │             │  Coder  │        │ Tester  │  ← 并行；Tester 看不到代码
     │             └────┬────┘        └────┬────┘
     │                  └────────┬─────────┘
     │                           ▼
     │                  ┌─────────────────┐
     │                  │ Sandbox: pytest │
     │                  └────────┬────────┘
     │                  fail ↙       ↘ pass
     │         ┌──────────────────┐   │
     │         │ Fault Attribution│   │
     │         │    (Tester)      │   │
     │         └──┬─────┬──────┬──┘   │
     │  SPEC_AMBIG│ CODE│  TEST│      ▼
     └────────────┘  →Coder →Tester ┌──────────┐
                                    │ Reviewer │──REQUEST_CHANGES──→ Coder
                                    └────┬─────┘
                                         ▼ APPROVE
                              最终代码 + 测试 + 报告
```

### 协作机制（slides 按指南要求的三个问题来讲）

- **任务怎么分解**：Planner 输出结构化 plan，Coder 和 Tester 按 plan 并行工作。
- **Agent 之间怎么通信**：共享工作区（`workspace/` 目录，放代码和测试文件）加结构化消息（Pydantic schema），所有消息写入 `trace.jsonl`。
- **最终结果怎么产生**：Reviewer APPROVE，或者达到预算上限时输出当前最好的版本并附上未解决问题。

### 终止策略（防止死循环，也是一个设计亮点）

- Test 循环最多 4 轮，Review 循环最多 2 轮。
- **停滞检测**：同一个错误签名连续出现 2 次时，不再重复交给 Coder，而是升级给 Planner 重新规划。
- Token 预算上限。

---

## 四、技术栈

| 组件 | 选择 | 理由 |
|---|---|---|
| 编排 | **LangGraph** | 条件边天然对应反馈回路，能导出 Mermaid 图直接放进 slides |
| LLM | `gpt-4o-mini` 或 `deepseek-chat`（OpenAI 兼容接口） | 便宜；能力偏弱的模型更容易体现多 Agent 带来的提升 |
| 结构化输出 | Pydantic + JSON mode | 消息格式可校验 |
| 沙箱 | `subprocess` + 临时目录 + 超时 30s（有条件可用 Docker `--network none`） | 执行 LLM 生成的代码必须隔离 |
| 静态分析 | ruff、radon、bandit | 给 Reviewer 提供客观依据，而不是只凭 LLM 感觉 |
| 评测 | **EvalPlus（HumanEval+）** | 测试比原版 HumanEval 严格得多，边界情况多，最能体现 Tester 的价值 |
| UI | Streamlit | 实时显示每个 Agent 的消息，录视频效果好 |

设置 `temperature=0` 并缓存 LLM 响应，保证实验可复现，demo 现场也不会翻车。

---

## 五、项目结构

```
devcrew/
├── README.md                 # 安装、配置 API key、运行命令
├── requirements.txt
├── .env.example              # API key 放环境变量，不要写进代码
├── devcrew/
│   ├── state.py              # 共享状态定义
│   ├── schemas.py            # Plan / TestReport / Attribution / ReviewVerdict
│   ├── llm.py                # LLM 封装 + 缓存 + token 统计
│   ├── agents/
│   │   ├── planner.py
│   │   ├── coder.py
│   │   ├── tester.py         # 写测试 + 错误归因
│   │   └── reviewer.py
│   ├── tools/
│   │   ├── sandbox.py        # 运行 pytest
│   │   ├── workspace.py      # 文件读写，做权限隔离
│   │   └── static_analysis.py
│   └── graph.py              # LangGraph 编排
├── eval/
│   ├── run_benchmark.py      # 跑 6 种配置
│   ├── baselines.py          # 单 Agent 基线
│   └── analyze.py            # 出图、出表
├── tasks/                    # 3 个自定义的项目级 demo 任务
├── app.py                    # Streamlit UI
└── results/
```

### 核心代码骨架

**state.py**

```python
class DevState(TypedDict):
    requirement: str
    plan: Plan | None
    code_files: dict[str, str]
    test_files: dict[str, str]
    test_report: TestReport | None
    attribution: Attribution | None
    review: ReviewVerdict | None
    test_iters: int
    review_iters: int
    error_history: list[str]      # 用于停滞检测
    trace: list[AgentMessage]     # 所有 Agent 消息
```

**graph.py**（关键路由逻辑）

```python
def route_after_test(s: DevState) -> str:
    if s["test_report"].all_passed:
        return "reviewer"
    if s["test_iters"] >= MAX_TEST_ITERS:
        return END                 # 达到上限，输出当前最好版本
    return "attribute"

def route_after_attribution(s: DevState) -> str:
    sig = s["test_report"].error_signature
    if s["error_history"].count(sig) >= 2:      # 停滞，升级给 Planner
        return "planner"
    return {"CODE_BUG": "coder_fix",
            "TEST_BUG": "tester_fix",
            "SPEC_AMBIGUITY": "planner"}[s["attribution"].verdict]

g = StateGraph(DevState)
g.add_node("planner", planner_node)
g.add_node("coder", coder_node)
g.add_node("coder_fix", coder_node)       # 修复路径单独注册，原因见分工文档第 4 节
g.add_node("tester_write", tester_write_node)
g.add_node("run_tests", run_tests_node)
g.add_node("attribute", attribution_node)
g.add_node("tester_fix", tester_fix_node)
g.add_node("reviewer", reviewer_node)
# planner → coder 与 tester_write 并行 → run_tests → 条件路由 ...
# 完整可运行版本见 DevCrew_分工与协作方案.md 第 4 节
```

**Tester 的 prompt 要点**（体现信息隔离）

```
You are a QA engineer. You will NOT see the implementation.
Based ONLY on the specification below, write pytest tests that cover:
1. Every acceptance criterion
2. Every listed edge case
3. At least 2 edge cases the spec did not mention (empty input, boundary values, invalid types)
For each test, add a one-line comment citing which spec item it verifies.
```

"每个测试都要标出对应的规格条目"这条约束有两个作用：减少凭空编造的错误测试，并且让错误归因有依据可查。

---

## 六、实验设计（Analysis & Innovation 的主要得分点）

### 数据集

- **HumanEval+ 抽 50 题**（固定随机种子）。Agent 只能看到题目描述，**评测用 EvalPlus 的隐藏测试**。Tester 自己写的测试和最终评分分开，结果可信。
- **3 个自定义项目级任务**，用于 demo 和案例分析：
  1. 带 TTL 的 LRU 缓存
  2. 简易 Markdown 转 HTML（标题、列表、粗体、代码块）
  3. 命令行记账工具（增删查 + JSON 持久化 + 月度统计）

### 6 种配置（消融实验）

| 配置 | 说明 | 用来证明什么 |
|---|---|---|
| A. Single-shot | 单个 LLM 直接写 | 基线 |
| B. Self-refine | 单个 LLM 写完自查自改 | "多次调用"和"多 Agent"的区别 |
| C. Coder + Tester | 去掉 Planner 和 Reviewer | Tester 反馈回路的贡献 |
| D. **Full DevCrew** | 完整系统 | 主结果 |
| E. Full − 信息隔离 | Coder 能看到测试源码 | 隔离能否防止过拟合 |
| F. Full − 错误归因 | 测试失败一律交给 Coder | 归因机制的作用 |

### 指标

- **pass@1**（隐藏测试）：主指标
- 平均迭代轮数、平均 token、成本、耗时
- 错误归因判断为 `TEST_BUG` 的比例，以及判断的准确率（人工抽查 10 个）
- Reviewer 发现的问题类型分布

**预期**：D 优于 A/B；E 在隐藏测试上低于 D（说明隔离有用）；F 的迭代次数更多、通过率更低。**如果实验结果和预期不符，也如实报告并分析原因**，这在 Analysis 部分同样能得分。

**成本估算**：50 题 × 6 配置 × 平均约 2 万 token ≈ 600 万 token，用 gpt-4o-mini 或 deepseek 大约几美元。

### 案例分析（每类挑 1 个）

1. **成功案例**：Tester 写了一个空列表边界测试，Coder 原来的实现在这里崩溃，修复后通过了隐藏测试。
2. **归因生效案例**：Tester 的测试期望值算错了，归因判为 `TEST_BUG`，由 Tester 自己修正，正确的代码没有被改坏。
3. **失败案例**：需求本身有歧义，Planner 和 Tester 理解一致但都是错的，测试全过而隐藏测试失败。这说明所有 Agent 用同一个底座模型时存在**相关性错误**。

### Limitations（必须写）

- 所有 Agent 共享同一个模型，错误可能相关；改进方向是不同 Agent 用不同模型
- 多 Agent 的 token 成本是单 Agent 的 3 到 5 倍，需要给出实际数字
- 只验证了单文件或小型多文件项目
- 错误归因本身也会判断错

---

## 七、6 天时间表

| 日期 | 任务 | 当天产出 |
|---|---|---|
| **11/17** | 确定方案和分工；搭项目框架、LLM 封装、schema、沙箱 | 能在沙箱里跑 pytest |
| **11/18** | 4 个 Agent + LangGraph 编排 | 一个任务能端到端跑通 |
| **11/19** | 错误归因、停滞检测、Reviewer 静态分析工具；Streamlit UI；评测脚本 | 完整系统 + UI |
| **11/20** | 跑 6 种配置的实验（建议后台跑一整夜） | `results/` 里的原始数据 |
| **11/21** | 出图表、挑案例、写 slides | slides 初稿 |
| **11/22** | 录视频、写 README、写个人贡献声明 | 全部材料 |
| **11/23** | 缓冲时间；检查、打包 zip、**上午提交**，不要拖到深夜 | 提交完成 |

---

## 八、分工（每人负责一个 Agent，详见 `DevCrew_分工与协作方案.md`）

| 成员 | 负责模块 | 和其他人的接口 |
|---|---|---|
| A | Planner；schemas、llm 封装、LangGraph 编排、停滞检测、集成 | 定义 `state.py` 和 `schemas.py`，**第一天就要定好**，其他人都依赖它 |
| B | Coder；评测框架、基线、消融实验 | 消费 Plan、失败信息和审查意见，产出代码 |
| C | Tester；沙箱、错误归因 | 消费 Plan，产出测试、TestReport 和 Attribution |
| D | Reviewer；静态分析工具、Streamlit UI、slides 主笔 | 消费代码和测试报告，产出 ReviewVerdict；读取 trace 做可视化 |

视频和 slides 大家一起完成，每人讲自己负责的模块。这样个人贡献声明自然清晰，也符合指南里 "how their work interacts with or contributes to other members' modules" 的要求。

---

## 九、Slides 大纲（约 14 页，对应指南要求的 4 部分）

1. 标题页、组号、成员
2. **Problem**：LLM 写代码的三类典型问题（配一个真实失败例子）
3. **Why multi-agent**：信息隔离和角色分工能解决什么，单 Agent 为什么做不到
4. **Architecture**：LangGraph 导出的流程图
5. 各 Agent 的角色、能看到的信息、工具
6. 通信机制：共享工作区 + 结构化消息（展示一条真实 JSON 消息）
7. 创新点：错误归因 + 停滞检测
8. **Implementation**：技术栈
9. Demo 截图：完整流程
10. **Results**：主结果柱状图（6 种配置的 pass@1）
11. 消融分析：信息隔离和错误归因的作用
12. 成本和迭代次数分析
13. 案例分析：成功、归因生效、失败各一个
14. Limitations 与未来工作

---

## 十、Demo 视频脚本（不超过 10 分钟）

| 时间 | 内容 |
|---|---|
| 0:00–1:00 | 问题和动机 |
| 1:00–3:00 | 架构讲解（对着流程图） |
| 3:00–6:30 | **现场 demo**：在 Streamlit 输入"带 TTL 的 LRU 缓存"，展示 Planner 输出 → Coder 和 Tester 并行 → 测试失败 → 错误归因 → 修复 → Reviewer 提出复杂度问题 → 修改 → APPROVE |
| 6:30–8:30 | 实验结果和消融分析 |
| 8:30–10:00 | 失败案例和局限 |

**录制技巧**：demo 用缓存好的 LLM 响应回放，保证选中的流程恰好出现"测试失败 → 归因 → 修复"。视频里要说明这是缓存回放。

---

## 十一、提交清单与注意事项

### 提交材料

- [ ] 系统源代码 + README（运行说明）
- [ ] Demo 视频（≤ 10 分钟）
- [ ] Presentation slides
- [ ] Individual Contribution Statement（每人负责的模块及与他人模块的交互）
- [ ] 打包为 `COMP5584+GroupProject+Group[组号].zip`，一人在 Canvas 上传

### 注意事项

- **API key** 放在 `.env` 里，打包前确认 zip 中没有 `.env`，只附带 `.env.example`。
- **执行 LLM 生成的代码**必须在临时目录里运行并设置超时，不要在项目根目录直接执行。
- 有问题发邮件给 TA Qi Peng（qi0125.peng@connect.polyu.hk），标题以 `COMP5584+GroupProject+Group[ID]` 开头。
