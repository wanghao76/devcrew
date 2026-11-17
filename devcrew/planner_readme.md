# DevCrew Planner 使用说明

本目录包含可运行的 DevCrew LangGraph 流程，以及已经落地的真实 Planner Agent。
当前分支中，Coder、Tester 的错误归因与修复节点、Reviewer 仍然使用 mock 实现，
因此可以在其他成员尚未完成开发时，独立调试和验证 Planner。

## 一、环境准备

进入项目运行目录：

```bash
cd /Users/zhan/Desktop/Agent_polyu/devcrew/devcrew
```

创建并激活虚拟环境，然后安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

复制环境变量模板：

```bash
cp .env.example .env
```

在 `.env` 中配置以下任意一种 API：

```dotenv
# OpenAI
OPENAI_API_KEY=你的_API_Key
OPENAI_MODEL=gpt-4o-mini

# 或使用 DeepSeek
DEEPSEEK_API_KEY=你的_API_Key
DEVCREW_MODEL=deepseek-chat
```

`.env` 已被 Git 忽略，不要把真实 API Key 提交到仓库。

## 二、运行方式

### 1. 运行原有全 mock 流程

此命令不调用外部 LLM：

```bash
python main.py "add two numbers"
```

### 2. 运行真实 Planner

真实 Planner 会调用配置的 LLM，其他下游 Agent 暂时使用 mock：

```bash
python main.py "Implement add(a, b) for integers" --planner real
```

也可以直接输入中文需求：

```bash
python main.py "实现一个接收两个整数并返回它们之和的函数" --planner real
```

运行结果默认写入：

```text
results/runs/mock-happy/
├── trace.jsonl
└── solution.py
```

## 三、Planner 的主要能力

真实 Planner 位于 `devcrew/agents/planner.py`，主要负责：

1. 将自然语言需求转换为符合 `Plan` schema 的结构化规格。
2. 生成文件列表、函数签名、验收标准 AC、边界情况 EC 和明确假设。
3. 对函数名、函数签名、文件归属以及 AC/EC 编号进行确定性校验。
4. 语义校验失败时，将错误反馈给 LLM 并重试一次。
5. 收到 `SPEC_AMBIGUITY` 或停滞升级后，根据 Tester 的归因结果重新规划。
6. 由代码维护 `plan.version` 和 `replan_count`，不让 LLM 决定流程状态。
7. 只通过共享 `DevState` 与其他 Agent 通信，不直接调用 Coder、Tester 或 Reviewer。

## 四、信息隔离

Planner 只读取以下必要信息：

- 原始需求 `requirement`
- 当前运行配置 `config`
- 旧版 `plan`（仅重新规划时）
- Tester 产生的 `attribution.details` 和 `attribution.suggestion`

Planner 不会读取代码、测试源码或 Reviewer 意见来生成规格，从而保持角色边界清晰。

## 五、LLM 公共封装

`devcrew/llm.py` 为所有真实 Agent 提供统一接口：

```python
chat(system, user, agent="planner")
chat_json(system, user, Plan, agent="planner")
```

该封装支持：

- OpenAI 和 DeepSeek OpenAI 兼容接口
- Pydantic JSON schema 校验
- JSON 校验失败后最多重试两次
- `temperature=0`
- 磁盘缓存 `.cache/llm/`
- token 数量统计

其他 Agent 应复用这个封装，不要在自己的模块中直接调用 OpenAI SDK。

## 六、运行测试

激活虚拟环境后执行：

```bash
pytest -q
```

Planner 测试覆盖：

- 首次规划
- Plan 规则校验
- 无效候选 Plan 的修复重试
- 第二次校验失败时安全终止
- 重新规划及版本递增
- Planner 信息隔离
- `use_planner=False` 消融配置
- 真实 Planner 替换 mock Planner 后的 LangGraph 集成

当前测试基线为：

```text
25 passed
```

## 七、与其他开发者集成

其他成员接入时，不需要直接依赖 Planner 模块，只需要遵守共享 State 和 schema：

- Coder 从 `state["plan"]` 读取实现规格。
- Tester Write 从 `state["plan"]` 读取 AC/EC，不读取代码。
- Tester Attribution 通过 `state["attribution"]` 把歧义反馈给 Planner。
- Reviewer 根据当前 `Plan` 检查规格不一致问题。
- UI 从 `state["trace"]` 展示 Plan 版本、AC/EC 数量和重新规划的条目。

如果需要新增或修改跨 Agent 字段，应先更新 `schemas.py`、`state.py` 和契约测试，
不要在单个 Agent 文件中自行定义新的跨 Agent 消息类型。
