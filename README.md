# DevCrew：Planner、Coder、Tester、Reviewer 组成的多 Agent 开发团队

COMP5584 Group Project。输入一段 Python 函数需求，4 个 Agent 分工完成：Planner 写规格，Coder 写代码，Tester 只看规格写测试并在本地运行，测试失败时判断是代码错还是测试错，Reviewer 做静态检查和代码审查。最后输出通过测试和审查的 `solution.py`。

```
用户需求 → Planner ──→ Coder ──┐
                  └──→ Tester ─┴→ 运行 pytest ─┬─ 全部通过 → Reviewer ─┬─ 通过 → 结束
                                              │                      └─ 要求修改 → Coder 修复 → 重新测试
                                              └─ 有失败 → 错误归因 ─┬─ 代码错 → Coder 修复 → 重新测试
                                                                  ├─ 测试错 → Tester 修复 → 重新测试
                                                                  └─ 需求有歧义 → Planner 重新规划
```

本文档从零开始，一步不跳。第一次使用请按第 1 到第 6 节顺序做。

## 目录

1. [准备工作](#1-准备工作)
2. [下载代码并安装](#2-下载代码并安装)
3. [不用 API key 先跑一遍](#3-不用-api-key-先跑一遍)
4. [配置 API key](#4-配置-api-key)
5. [用真实 Agent 运行（命令行）](#5-用真实-agent-运行命令行)
6. [用图形界面运行](#6-用图形界面运行)
7. [项目结构](#7-项目结构)
8. [工作流程和规则](#8-工作流程和规则)
9. [开发和提交代码](#9-开发和提交代码)
10. [常见问题](#10-常见问题)
11. [其他文档](#11-其他文档)

---

## 1. 准备工作

### 1.1 你需要

| 东西 | 用途 | 什么时候需要 |
|---|---|---|
| Python 3.9 或更高版本 | 运行项目 | 必须 |
| Git | 下载和提交代码 | 必须 |
| GitHub 账号 | 推送代码 | 只有要提交代码时 |
| DeepSeek API key | 让 Agent 调用大模型 | 只有真实运行时（第 5、6 节） |

### 1.2 检查 Python

打开终端（macOS：「终端」App；Windows：开始菜单搜索「PowerShell」），输入：

macOS / Linux：

```bash
python3 --version
```

Windows：

```powershell
py --version
```

看到 `Python 3.9.x` 或更高（例如 `Python 3.12.4`）就可以。如果提示找不到命令：

- macOS：到 https://www.python.org/downloads/ 下载安装包，或者用 Homebrew 执行 `brew install python@3.12`
- Windows：到 https://www.python.org/downloads/ 下载安装包。**安装第一页勾选「Add python.exe to PATH」**，然后关闭并重新打开 PowerShell

推荐 Python 3.10 及以上。3.9 也能完整运行，只是图形界面的配色主题不生效（见第 6.4 节）。

### 1.3 检查 Git

```bash
git --version
```

看到 `git version 2.x.x` 就可以。没有的话：macOS 执行 `xcode-select --install`；Windows 到 https://git-scm.com/download/win 下载安装，全部选默认。

---

## 2. 下载代码并安装

### 2.1 下载代码

先进入你想放项目的文件夹，例如桌面：

```bash
cd ~/Desktop
```

Windows PowerShell 里同样可以用 `cd ~/Desktop`。

然后下载（两种方式选一种）：

```bash
# 方式 A：HTTPS，不需要配置 SSH，最简单
git clone https://github.com/wanghao76/devcrew.git

# 方式 B：SSH，需要已经把 SSH 公钥添加到 GitHub
git clone git@github.com:wanghao76/devcrew.git
```

### 2.2 进入运行目录

仓库里有两层同名的 `devcrew` 文件夹，容易搞混：

```
devcrew/                 ← 仓库根目录（git clone 下来的文件夹，放方案文档）
└── devcrew/             ← 运行目录：main.py、app.py、requirements.txt 都在这里
    └── devcrew/         ← Python 包（Agent 代码），不用进去
```

**之后所有命令都在「运行目录」里执行**：

```bash
cd devcrew/devcrew
```

确认位置正确：

```bash
ls            # Windows 用 dir
```

应该能看到 `main.py`、`app.py`、`requirements.txt`、`tests`。看不到就说明目录不对，回到 2.1 的文件夹重新 `cd`。

### 2.3 创建虚拟环境

虚拟环境把本项目的依赖和电脑上其他 Python 项目隔开。只需要创建一次。

macOS / Linux：

```bash
python3 -m venv .venv
```

Windows：

```powershell
py -m venv .venv
```

执行后运行目录里会多一个 `.venv` 文件夹。

### 2.4 激活虚拟环境

**每次新开终端都要重新激活一次。**

macOS / Linux：

```bash
source .venv/bin/activate
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
```

如果 Windows 报错「无法加载文件 ……因为在此系统上禁止运行脚本」，先执行下面这行，输入 `Y` 确认，再重新激活：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

激活成功后，命令行开头会出现 `(.venv)`。再确认一下用的是虚拟环境里的 Python：

```bash
python --version
which python        # Windows 用：where python
```

`which python` 的结果应该以 `.venv/bin/python` 结尾。**激活之后统一用 `python`，不用再写 `python3` 或 `py`。**

### 2.5 安装依赖

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

第一次安装大约需要 1 到 3 分钟。最后没有红色的 `ERROR` 就是成功。会装上 langgraph、pydantic、openai、pytest、ruff、radon、bandit、streamlit 等。

### 2.6 验证安装

```bash
python -m pytest tests -q
```

最后一行应该是：

```
62 passed, 1 warning in 9.20s
```

数量以当前代码为准，关键是**没有 `failed`**。那 1 个 warning 来自 LangGraph 自身，不用管。这一步不需要 API key，也不会调用大模型。

---

## 3. 不用 API key 先跑一遍

这一步用 mock Agent（返回固定内容的假 Agent）跑完整流程，测试执行是真的 pytest。用来确认流程本身没问题。

### 3.1 运行

```bash
python main.py "add two numbers"
```

输出（每行是一个 Agent 的一步，方括号里是第几轮测试）：

```
[0] planner       planner -> coder,tester           plan v1
[0] coder           coder -> sandbox                [write] wrote solution.py
[0] tester_write   tester -> sandbox                wrote 3 tests
[1] run_tests     sandbox -> tester                 3 passed, 0 failed
[1] reviewer     reviewer -> coder                  APPROVE
[1] finalize       system -> user                   finished: approved
final_status: approved
output: results/runs/mock-happy
```

### 3.2 试试其他场景

加 `--scenario` 可以模拟不同情况，看流程怎么走：

| 场景 | 命令 | 会看到 |
|---|---|---|
| 一次通过 | `python main.py "add two numbers" --scenario happy` | 测试通过 → Review 通过 |
| 代码有 bug | `python main.py "add two numbers" --scenario code_bug` | 测试失败 → 归因 `CODE_BUG` → `coder_fix` → 重测通过 |
| 测试写错 | `python main.py "add two numbers" --scenario test_bug` | 归因 `TEST_BUG` → `tester_fix` → 重测通过 |
| 需求歧义 | `python main.py "add two numbers" --scenario spec` | 归因 `SPEC_AMBIGUITY` → Planner 生成 plan v2 → 重新编写 |
| Review 要求修改 | `python main.py "add two numbers" --scenario review` | Reviewer 第一轮要求修改 → `coder_fix` → 第二轮通过 |
| 一直修不好 | `python main.py "add two numbers" --scenario stall` | 同一错误重复 → 重新规划 → 4 轮后停止，`final_status: max_test_iters` |

例如 `code_bug` 的输出：

```
[0] planner       planner -> coder,tester           plan v1
[0] coder           coder -> sandbox                [write] wrote solution.py
[0] tester_write   tester -> sandbox                wrote 3 tests
[1] run_tests     sandbox -> tester                 1 passed, 2 failed
[1] attribute      tester -> coder,tester,planner   CODE_BUG
[1] coder_fix       coder -> sandbox                [fix_tests] wrote solution.py
[2] run_tests     sandbox -> tester                 3 passed, 0 failed
[2] reviewer     reviewer -> coder                  APPROVE
[2] finalize       system -> user                   finished: approved
final_status: approved
output: results/runs/mock-code_bug
```

### 3.3 查看输出文件

每次运行的结果放在 `results/runs/<任务名>/`：

| 文件 | 内容 |
|---|---|
| `solution.py` | 最终代码 |
| `test_solution.py` | Tester 写的测试 |
| `trace.jsonl` | 每个 Agent 每一步的消息，一行一条 JSON，可用于分析和做 slides |

同一个任务名再次运行会覆盖旧结果。

---

## 4. 配置 API key

### 4.1 获取 DeepSeek API key

1. 打开 https://platform.deepseek.com/ 并登录
2. 左侧菜单进入「API keys」
3. 点「创建 API key」，名字随便填，例如 `devcrew`
4. **复制弹出的 key**，格式是 `sk-` 开头加 32 位字母数字。这个 key 只显示一次
5. 左侧「充值」确认账户有余额。余额为 0 时调用会失败

### 4.2 创建 .env 文件

在运行目录执行：

```bash
cp .env.example .env          # Windows：Copy-Item .env.example .env
```

用任意文本编辑器打开 `.env`（VS Code：`code .env`；macOS 也可以 `open -e .env`），把第一行改成你的 key：

```dotenv
DEEPSEEK_API_KEY=sk-你复制的key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEVCREW_MODEL=deepseek-chat
```

注意：

- 等号两边不要有空格，key 不要加引号
- `DEVCREW_MODEL` 必须和平台对应。用 DeepSeek 就写 `deepseek-chat`，写成 `gpt-4o-mini` 会报模型不存在
- 用 OpenAI 或其他兼容平台时，填 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`DEVCREW_MODEL` 三项。**只要填了 `OPENAI_API_KEY`，程序就优先用它，DeepSeek 配置会被忽略**

### 4.3 确认 .env 不会被提交

**这个仓库是公开的，key 一旦推到 GitHub 任何人都能看到。** 执行：

```bash
git status --short
```

输出里**不能出现 `.env`**（`.env.example` 可以出现）。`.env` 已经写在 `.gitignore` 里，正常情况下看不到它。如果 key 不小心推上去了，立刻到 DeepSeek 控制台删除这个 key 并重新生成。

### 4.4 测试 key 是否可用

```bash
python -c "from devcrew.llm import chat; print(chat('Reply with OK', 'ping', agent='check'))"
```

- 成功：输出类似 `('OK', 12)`，第二个数字是消耗的 token 数
- `LLMConfigurationError: Set OPENAI_API_KEY or DEEPSEEK_API_KEY ...`：没找到 `.env`，确认你在运行目录，并且文件名是 `.env` 而不是 `.env.txt`
- `AuthenticationError: Error code: 401 ... api key ... is invalid`：key 错了、被删除了或者复制不完整，回到 4.1 重新生成
- `Error code: 402` 或 `Insufficient Balance`：账户余额不足，去充值

### 4.5 关于缓存

所有模型回复会缓存到运行目录的 `.cache/llm/`。完全相同的请求第二次直接读缓存，不花钱，结果也完全一样，适合录 demo 视频。想让模型重新生成，删掉缓存：

```bash
rm -rf .cache/llm             # Windows：Remove-Item -Recurse -Force .cache\llm
```

---

## 5. 用真实 Agent 运行（命令行）

先完成第 4 节。

### 5.1 四个 Agent 全部用真实模型

```bash
python main.py "Implement is_palindrome(s: str) -> bool that ignores case and non-alphanumeric characters." --real
```

一次运行一般调用模型 5 到 15 次，用时 30 秒到几分钟，取决于测试失败、修复了几轮。屏幕上的格式和第 3 节一样，结果放在 `results/runs/real/`。

### 5.2 只替换一部分 Agent

调试自己负责的 Agent 时，可以只把它换成真实的，其他仍用 mock：

```bash
python main.py "add two numbers" --planner real
python main.py "add two numbers" --coder real
python main.py "add two numbers" --tester real
python main.py "add two numbers" --reviewer real
python main.py "add two numbers" --planner real --coder real     # 可以组合
```

注意：mock 的测试和代码都是针对 `add(a, b)` 写的。只换一部分 Agent 时，需求请保持为加法，否则真实 Agent 和 mock 的内容对不上。

### 5.3 怎么写需求

- 用英文写，写清楚**函数名、参数和返回类型**，例如 `Implement merge_intervals(intervals: list[list[int]]) -> list[list[int]] ...`
- 目前的 Plan 只能描述**顶层函数**，不能描述类。「实现一个 LRU 缓存类」这类需求请改写成函数形式
- 只使用 Python 标准库
- 需求越具体，Tester 写的测试越准确

### 5.4 看结果

最后一行 `final_status` 的含义：

| 值 | 含义 |
|---|---|
| `approved` | 测试全部通过，Review 也通过。`solution.py` 可以用 |
| `max_test_iters` | 测试修了 4 轮仍有失败，停止。查看 `trace.jsonl` 里的失败原因 |
| `max_review_iters` | 测试通过，但 Review 2 轮后仍要求修改 |

`--task-id` 可以给每次运行起不同的名字，避免互相覆盖：

```bash
python main.py "Implement fizzbuzz(n: int) -> list[str] ..." --real --task-id fizzbuzz
# 结果在 results/runs/fizzbuzz/
```

### 5.5 全部参数

```bash
python main.py --help
```

| 参数 | 作用 | 默认 |
|---|---|---|
| `requirement` | 需求文本，必填，用引号括起来 | — |
| `--real` | 4 个 Agent 全部用真实模型 | 关 |
| `--planner/--coder/--tester/--reviewer real` | 单独替换某个 Agent | `mock` |
| `--scenario` | mock 场景，只影响 mock Agent | `happy` |
| `--task-id` | 输出文件夹名 | 全真实时 `real`，否则 `mock-<场景>` |
| `--out` | 输出根目录 | `results/runs` |

---

## 6. 用图形界面运行

界面里 4 个 Agent 都是真实的，需要先完成第 4 节。

### 6.1 启动

在运行目录、虚拟环境已激活的状态下：

```bash
streamlit run app.py
```

第一次启动 Streamlit 可能问你要邮箱，直接按回车跳过。看到下面的输出后，浏览器会自动打开；没打开就手动访问 `Local URL`：

```
  Local URL: http://localhost:8501
```

### 6.2 使用

1. 在「What would you like DevCrew to build?」输入框里写需求（写法见 5.3），默认填了一个加法示例
2. 点「Run DevCrew」
3. 「Execution progress」显示 4 个阶段的状态；Coder 修复代码后，Tester 和 Reviewer 的状态会重置，等重新测试和审查
4. 「Execution timeline」按顺序列出每一步
5. 运行结束后，下方标签页分别显示 Plan、Code、Tests、Review；点「Download solution.py」下载代码
6. 点「Clear results」清空，开始新任务

### 6.3 停止

回到运行 `streamlit` 的终端，按 `Ctrl + C`。

### 6.4 Python 3.9 上的已知差异

Python 3.9 只能安装 Streamlit 1.50，比开发时用的版本旧：

- 启动时终端会打印几行 `"theme.light" is not a valid config option` 之类的提示，界面使用默认配色。不影响功能
- 时间线不会自动滚动到最新一步，需要手动往下拉

用 Python 3.10 及以上就没有这些差异。

### 6.5 界面报错

| 界面提示 | 原因 | 处理 |
|---|---|---|
| Model authentication failed | key 无效 | 按 4.4 检查 key |
| Model configuration failed | 没找到 `.env` 或模型返回格式不对 | 确认 `.env` 在运行目录；重试一次 |
| Workflow failed | 其他错误 | 看运行 `streamlit` 的终端里的完整报错 |

---

## 7. 项目结构

```
devcrew/                                仓库根目录
├── README.md                           本文档
├── DevCrew_方案.md                     总体方案、实验设计、时间表
├── DevCrew_分工与协作方案.md           每人负责的 Agent 和协作方式
├── DevCrew_Schema规范.md               消息格式、字段归属、节点接口（开发前必读）
├── COMP5584_project_guidelines.pdf     课程要求
└── devcrew/                            运行目录
    ├── main.py                         命令行入口
    ├── app.py                          Streamlit 图形界面
    ├── requirements.txt                依赖
    ├── .env.example                    模型配置模板（复制成 .env 再填）
    ├── planner_readme.md               Planner 说明（A）
    ├── TESTER_GUIDE.md                 Tester 说明（C）
    ├── README.md                       Reviewer 和界面说明（D）
    ├── devcrew/
    │   ├── schemas.py                  所有 Agent 之间传递的消息格式
    │   ├── state.py                    共享状态 DevState
    │   ├── graph.py                    LangGraph 流程和路由规则
    │   ├── llm.py                      调用大模型的统一入口，带缓存
    │   ├── mocks.py                    mock Agent，用于不花钱地测试流程
    │   ├── ui_adapter.py / ui_trace.py 界面用的流程封装和消息展示
    │   ├── agents/
    │   │   ├── __init__.py             select_nodes()：选择哪些 Agent 用真实实现
    │   │   ├── planner.py              A
    │   │   ├── coder.py                B
    │   │   ├── tester.py               C
    │   │   └── reviewer.py             D
    │   └── tools/
    │       ├── sandbox.py              在临时目录里运行 pytest
    │       └── static_analysis.py      ruff / radon / bandit 静态检查
    └── tests/                          所有单元测试和契约测试
```

运行后会生成、但不会提交到 Git 的内容：`.venv/`、`.env`、`.cache/`、`results/runs/`。

---

## 8. 工作流程和规则

### 8.1 每个 Agent 做什么

| Agent | 能看到 | 做什么 | 输出 |
|---|---|---|---|
| Planner | 需求 | 写函数签名、验收标准 AC-1…、边界情况 EC-1…、假设；规则校验不通过会让模型重写一次 | Plan |
| Coder | Plan、自己的代码、失败信息、归因结论、Review 意见 | 写或修改代码；提交前自检语法和函数签名，最多重试 2 次 | `solution.py` |
| Tester | 写测试时只看 Plan；归因时看 Plan、代码、测试和失败信息 | 写 pytest 测试；运行；判断失败原因；修正自己写错的测试 | 测试文件、测试报告、归因结论 |
| Reviewer | Plan、代码、测试报告、静态检查结果 | 先跑 ruff、radon、bandit，再让模型审查 | APPROVE 或 REQUEST_CHANGES |

**信息隔离**：Coder 永远看不到测试源码，只能看到「哪个测试失败、输入是什么、实际输出是什么」，防止它针对测试硬编码。Tester 写测试时看不到代码，保证测试独立于实现。

### 8.2 停止条件

| 规则 | 默认值 |
|---|---|
| 测试最多跑几轮 | 4 |
| Review 最多几轮 | 2 |
| 同一个错误出现几次算「卡住」，交给 Planner 重新规划 | 2 |
| Planner 最多重新规划几次 | 1 |
| Review 不通过的条件 | 有 blocker 或 major 级别的意见。bandit 高危自动算 blocker，圈复杂度 > 10 自动算 major |

这些值在 `devcrew/schemas.py` 的 `RunConfig` 里。

### 8.3 安全说明

测试在系统临时目录里执行，有 30 秒超时，能防止死循环，**但不是安全沙箱**。只运行课程任务和自己写的需求，不要让它生成或执行来源不明的代码。

---

## 9. 开发和提交代码

### 9.1 每次开始工作前

```bash
cd 仓库根目录                    # 例如 cd ~/Desktop/devcrew
git switch main
git pull
cd devcrew
source .venv/bin/activate        # Windows：.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt  # 别人加了依赖时需要
python -m pytest tests -q        # 确认拉下来的代码是好的
```

### 9.2 新建自己的分支

分支名用 `feat/<内容>`，例如：

```bash
git switch -c feat/eval-baselines
```

### 9.3 改代码时的规则

- 只改自己负责的文件。文件归属见 `DevCrew_分工与协作方案.md` 第 9.3 节
- 要改 `schemas.py`、`state.py`、`graph.py` 时，先在群里说明，按 `DevCrew_Schema规范.md` 第 11 节的流程来
- 自己的 Agent 写单元测试时，用 `monkeypatch` 替换模型调用，不要在测试里真的调用大模型。参考 `tests/test_coder.py`
- 用 Python 3.9 能运行的写法：类型写 `Optional[str]`、`List[int]`，不要用 `str | None`、`zip(..., strict=True)`、`match` 语句

### 9.4 提交

```bash
python -m pytest tests -q        # 必须全部通过
git status --short               # 确认没有 .env、.cache、results
git add <你改的文件>
git commit -m "feat(coder): 简要说明改了什么"
git push -u origin feat/eval-baselines
```

推送后终端会打印一个 `https://github.com/wanghao76/devcrew/pull/new/...` 链接。打开它创建 Pull Request，写清楚改了什么、怎么验证的，请另一位组员看过后合并到 `main`。

推送时报 `Permission denied` 或 `Repository not found`，说明你还不是仓库的协作者，找仓库所有者（wanghao76）在 Settings → Collaborators 里邀请你，接受邮件里的邀请后再推。

---

## 10. 常见问题

| 报错或现象 | 原因 | 处理 |
|---|---|---|
| `ModuleNotFoundError: No module named 'devcrew'` | 不在运行目录 | `cd` 到有 `main.py` 的目录再执行（见 2.2） |
| `ModuleNotFoundError: No module named 'langgraph'`（或 `pydantic`、`openai`） | 虚拟环境没激活，或依赖没装 | 按 2.4 激活，再执行 `pip install -r requirements.txt` |
| 命令行开头没有 `(.venv)` | 新开的终端还没激活 | 按 2.4 激活 |
| `NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+` | macOS 自带 Python 3.9 的提示 | 不影响使用，可以忽略 |
| `LangChainPendingDeprecationWarning` | LangGraph 自身的提示 | 不影响使用，可以忽略 |
| `LLMConfigurationError` | 没有 `.env` 或里面没填 key | 按 4.2 创建并填写 |
| `AuthenticationError: Error code: 401` | key 无效 | 按 4.1 重新生成，按 4.4 测试 |
| `Model Not Exist` 或 `model ... does not exist` | `DEVCREW_MODEL` 和平台不匹配 | DeepSeek 写 `deepseek-chat` |
| `PlannerValidationError` | 模型两次生成的 Plan 都不合规（例如验收标准少于 3 条） | 把需求写得更具体（见 5.3），再运行一次 |
| `LLMResponseError: ... did not return valid ... JSON` | 模型连续 3 次返回的 JSON 格式不对 | 再运行一次；仍失败就删掉 `.cache/llm` 后重试 |
| `final_status: max_test_iters` | 4 轮测试仍有失败 | 打开 `results/runs/<任务名>/trace.jsonl`，看 `run_tests` 和 `attribute` 两类消息里的失败原因 |
| 每次结果都一样 | 读的是缓存 | 见 4.5，删除 `.cache/llm` |
| `git push` 报 `Repository not found` | 远程地址写错，或者没有仓库权限 | `git remote -v` 应该是 `wanghao76/devcrew`；没有权限见 9.4 |
| `streamlit: command not found` | 虚拟环境没激活 | 按 2.4 激活；或者用 `python -m streamlit run app.py` |
| 浏览器打不开 `localhost:8501` | 端口被占用 | `streamlit run app.py --server.port 8502`，然后访问 `http://localhost:8502` |
| Windows 上 `cp`、`rm -rf` 不能用 | PowerShell 命令不同 | 用本文档里标注的 Windows 写法 |

---

## 11. 其他文档

| 文档 | 什么时候看 |
|---|---|
| `DevCrew_实际运行记录.md` | 对照一次真实运行的完整命令和输出，包括一个成功案例和一个失败案例 |
| `DevCrew_方案.md` | 了解项目目标、评分对应、实验设计、slides 和视频安排 |
| `DevCrew_分工与协作方案.md` | 了解每人负责什么、每天的计划 |
| `DevCrew_Schema规范.md` | 写或修改 Agent 之前，查字段归属和节点接口 |
| `devcrew/planner_readme.md` | Planner 的实现细节 |
| `devcrew/TESTER_GUIDE.md` | Tester 的实现细节 |
| `devcrew/README.md` | Reviewer 和界面的实现细节 |
