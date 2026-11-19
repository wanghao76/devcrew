# DevCrew 实际运行记录

本文记录一次**真实执行**的完整过程：从 GitHub 克隆代码开始，到 4 个 Agent 调用 DeepSeek 跑完任务。所有命令和输出都是原样复制，只把 API key 换成了 `sk-****`。

想自己跑一遍，按 `README.md` 操作即可；本文用来对照「正常情况下每一步应该看到什么」，以及给 slides 和报告提供真实案例。

## 运行环境

| 项目 | 值 |
|---|---|
| 日期 | 2026-11-19 |
| 系统 | macOS Sonoma |
| Python | 3.9.6（macOS 自带） |
| Git | 2.39.3 |
| 代码版本 | `main` 分支，提交 `9fead17` |
| 模型 | DeepSeek `deepseek-chat` |
| 工作目录 | `/tmp/devcrew_demo`（一个空文件夹，模拟新同学第一次使用） |

---

## 第 1 步：检查 Python 和 Git

```console
$ python3 --version
Python 3.9.6

$ git --version
git version 2.39.3 (Apple Git-146)
```

## 第 2 步：克隆代码，进入运行目录

```console
$ mkdir /tmp/devcrew_demo
$ cd /tmp/devcrew_demo
$ git clone https://github.com/wanghao76/devcrew.git
Cloning into 'devcrew'...

$ cd devcrew/devcrew
$ ls
README.md
TESTER_GUIDE.md
app.py
assets
devcrew
main.py
planner_readme.md
requirements.txt
tests
```

看到 `main.py`、`app.py`、`requirements.txt`、`tests`，说明进对了目录。

## 第 3 步：创建并激活虚拟环境

```console
$ python3 -m venv .venv
$ source .venv/bin/activate
(.venv) $ which python
/private/tmp/devcrew_demo/devcrew/devcrew/.venv/bin/python
(.venv) $ python --version
Python 3.9.6
```

## 第 4 步：安装依赖

```console
(.venv) $ python -m pip install --upgrade pip
...
Successfully installed pip-26.0.1

(.venv) $ pip install -r requirements.txt
...
Successfully installed ... bandit-1.8.6 ... langgraph-0.6.11 ... openai-2.48.0 ... pydantic-2.13.5 ... pytest-8.4.2 ... radon-6.0.1 ... ruff-0.17.5 ... streamlit-1.50.0 ...
```

（中间的下载日志很长，这里省略。最后一行是 `Successfully installed` 就是成功。）

## 第 5 步：跑测试，确认安装没问题

```console
(.venv) $ python -m pytest tests -q
63 passed, 1 warning in 10.52s
```

## 第 6 步：不用 API key 跑一次 mock 流程

```console
(.venv) $ python main.py "add two numbers"
[0] planner       planner -> coder,tester           plan v1
[0] coder           coder -> sandbox                [write] wrote solution.py
[0] tester_write   tester -> sandbox                wrote 3 tests
[1] run_tests     sandbox -> tester                 3 passed, 0 failed
[1] reviewer     reviewer -> coder                  APPROVE
[1] finalize       system -> user                   finished: approved
final_status: approved
output: results/runs/mock-happy
```

输出最前面还会有两条 warning（`NotOpenSSLWarning` 和 `LangChainPendingDeprecationWarning`），完整样子见第 8 步，可以忽略。

## 第 7 步：配置 DeepSeek key

复制模板：

```console
(.venv) $ cp .env.example .env
(.venv) $ cat .env
# DevCrew 读取本文件里的模型配置。复制为 .env 后填写，.env 不会被提交到 Git。
# 只填一种平台。DEVCREW_MODEL 优先级最高，必须和平台匹配。

# DeepSeek（小组默认）
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEVCREW_MODEL=deepseek-chat

# 或者 OpenAI / 其他 OpenAI 兼容平台：填了 OPENAI_API_KEY 就会优先使用它
# OPENAI_API_KEY=
# OPENAI_BASE_URL=
# DEVCREW_MODEL=gpt-4o-mini
```

用编辑器打开 `.env`，只改一行：

```dotenv
DEEPSEEK_API_KEY=sk-****
```

确认 `.env` 不会被提交（没有任何输出才对）：

```console
(.venv) $ git status --short
(.venv) $
```

测试 key。填 key 之前和之后各执行一次，对比两种结果：

```console
# 填 key 之前
(.venv) $ python -c "from devcrew.llm import chat; print(chat('Reply with OK', 'ping', agent='check'))"
...
devcrew.llm.LLMConfigurationError: Set OPENAI_API_KEY or DEEPSEEK_API_KEY in the environment or .env file.

# 填 key 之后
(.venv) $ python -c "from devcrew.llm import chat; print(chat('Reply with OK', 'ping', agent='check'))"
('OK', 10)
```

`('OK', 10)` 表示模型回复了 `OK`，这次调用消耗 10 个 token。

---

## 第 8 步（例 1）：4 个真实 Agent 完成 merge_intervals

### 命令

```console
(.venv) $ time python main.py "Implement merge_intervals(intervals: list[list[int]]) -> list[list[int]] that merges overlapping closed intervals and returns them sorted by start. Touching intervals such as [1, 2] and [2, 3] count as overlapping. Do not modify the input list." --real --task-id merge_intervals 2>&1
```

`2>&1` 把 warning 也合并到同一个输出里，方便完整记录，自己运行时可以不加。

### 完整输出

```
/private/tmp/devcrew_demo/devcrew/devcrew/.venv/lib/python3.9/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
/private/tmp/devcrew_demo/devcrew/devcrew/.venv/lib/python3.9/site-packages/langgraph/cache/base/__init__.py:8: LangChainPendingDeprecationWarning: The default value of `allowed_objects` will change in a future version. Pass an explicit value (e.g., allowed_objects='messages' or allowed_objects='core') to suppress this warning.
  from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
[0] planner       planner -> coder,tester           planned v1: 6 AC, 7 EC
[0] coder           coder -> sandbox                [write] Implemented merge_intervals in solution.py. It builds a sorted copy of the input (fresh inner lists, sorted by start then end) so the input is never mutated, then sweeps to merge overlapping o
[0] tester_write   tester -> sandbox                Tests derive expected outputs directly from the specification. AC-4 and EC-2 verify non-mutation and fresh object identity. EC-6 uses 100000 disjoint intervals to exercise O(n log n) behavior and avoid recursion. Extra edge cases cover unsorted containment/touching combinations and full-overlap collapse.
[1] run_tests     sandbox -> tester                 15 passed, 0 failed
[1] reviewer     reviewer -> coder,system           APPROVE; 0 comment(s)
[1] finalize       system -> user                   finished: approved
final_status: approved
output: results/runs/merge_intervals
python main.py  --real --task-id merge_intervals 2>&1  1.37s user 0.22s system 12% cpu 12.744 total
```

### 发生了什么

| 步骤 | Agent | 结果 |
|---|---|---|
| 1 | Planner | 写出 6 条验收标准（AC）和 7 条边界情况（EC） |
| 2 | Coder 和 Tester 同时开始 | Coder 只看 Plan 写代码；Tester 只看 Plan 写了 15 个测试，看不到代码 |
| 3 | 运行 pytest | 15 个全部通过 |
| 4 | Reviewer | ruff、radon、bandit 无问题，模型审查无意见，APPROVE |

总用时 12.7 秒，4 次模型调用共 7733 个 token。

### 输出文件

```console
(.venv) $ ls results/runs/merge_intervals
solution.py
test_solution.py
trace.jsonl
```

`solution.py`（Coder 写的最终代码）：

```python
def merge_intervals(intervals: list[list[int]]) -> list[list[int]]:
    """Merge overlapping or touching closed integer intervals.

    Returns a new list of new two-element lists, sorted ascending by start.
    The input list and its inner lists are never mutated.
    """
    if not intervals:
        return []

    # Build a sorted copy of the intervals (fresh inner lists) so the input
    # is never mutated. Sort by start, then end for deterministic ordering.
    ordered = sorted(([int(iv[0]), int(iv[1])] for iv in intervals),
                     key=lambda iv: (iv[0], iv[1]))

    merged: list[list[int]] = []
    for start, end in ordered:
        if not merged or start > merged[-1][1]:
            # No overlap and not touching: start a new merged interval.
            merged.append([start, end])
        else:
            # Overlapping or touching: extend the last merged interval.
            if end > merged[-1][1]:
                merged[-1][1] = end

    return merged
```

`test_solution.py` 里的 15 个测试（Tester 写的），名字里的 `ac`/`ec` 编号对应 Plan 里的条目，`ex` 是 Tester 自己补充的边界情况：

```
test_ac1_basic_merge
test_ac2_touching_intervals_merged
test_ac3_output_sorted_by_start
test_ac4_input_not_modified_and_fresh_objects
test_ac5_empty_and_single
test_ac6_nested_intervals_merge
test_ec1_empty_input
test_ec2_single_interval_is_copy
test_ec3_degenerate_intervals
test_ec4_duplicate_intervals
test_ec5_adjacent_not_touching_stay_separate
test_ec6_large_input
test_ec7_negative_and_mixed_sign
test_ex1_unsorted_with_containment_and_touching
test_ex2_all_overlapping_into_one
```

其中两个测试的内容：

```python
def test_ac2_touching_intervals_merged():
    assert merge_intervals([[1, 2], [2, 3]]) == [[1, 3]]
    assert merge_intervals([[1, 4], [4, 5], [5, 9]]) == [[1, 9]]


def test_ac4_input_not_modified_and_fresh_objects():
    data = [[3, 4], [1, 2]]
    snapshot = copy.deepcopy(data)
    result = merge_intervals(data)
    assert data == snapshot
    assert result == [[1, 2], [3, 4]]
    assert result is not data
    for inner in result:
        assert all(inner is not orig for orig in data)
```

`trace.jsonl` 每行一条消息，第一行是 Planner 的：

```json
{"node":"planner","sender":"planner","receivers":["coder","tester"],"type":"plan","summary":"planned v1: 6 AC, 7 EC","payload":{"plan_version":1,"ac_count":6,"ec_count":7,"changed_spec_ids":[]},"tokens":1726,"iteration":0}
```

---

## 第 9 步（例 2）：is_palindrome，一个没有通过的真实案例

这个例子没有得到 `approved`。保留它是因为它完整展示了错误归因、停滞检测、重新规划和轮数上限，也暴露了系统的局限，可以直接用在 slides 的「失败案例」部分。

### 命令

```console
(.venv) $ time python main.py "Implement is_palindrome(s: str) -> bool that ignores case and non-alphanumeric characters." --real --task-id palindrome 2>&1 | grep -v "NotOpenSSLWarning\|warnings.warn\|LangChainPendingDeprecationWarning\|JsonPlusSerializer"
```

后面的 `grep -v` 只是把两条 warning 过滤掉，自己运行时可以不加。

### 完整输出

```
[0] planner       planner -> coder,tester           planned v1: 7 AC, 6 EC
[0] coder           coder -> sandbox                [write] Implemented is_palindrome in solution.py. It validates the input type (raising TypeError for non-str inputs per AC-7/EC-6), normalizes by filtering with str.isalnum() and lowercasing each kept
[0] tester_write   tester -> sandbox                Tests derive expected values directly from the specification. AC-1..AC-7 and EC-1..EC-6 are each covered by a dedicated test. Two extra edge cases: EX-1 (punctuation-heavy palindrome normalizing to 'abccba') and EX-2 (Unicode Arabic-Indic digits treated as alphanumeric). EC-4 uses escaped Unicode to avoid encoding issues. EC-5 builds a 1,000,001-char palindrome to exercise linear-time behavior. All assertions use 'is True'/'is False' to enforce a plain bool return.
[1] run_tests     sandbox -> tester                 14 passed, 1 failed
[1] attribute      tester -> coder,tester,planner   TEST_BUG
[1] tester_fix     tester -> sandbox                Fixed test_ec4_unicode_alnum: 'Ésope é' normalizes to 'ésopeé' which is not a palindrome, so it now asserts False. Added a genuine Unicode palindrome 'Ésope éposÉ' (normalizes to 'ésopeéposé') asserting True. All other tests retained unchanged.
[2] run_tests     sandbox -> tester                 14 passed, 1 failed
[2] attribute      tester -> coder,tester,planner   TEST_BUG
[2] planner       planner -> coder,tester           replanned v2: 7 AC, 6 EC; changed EC-4
[2] coder           coder -> sandbox                [write] The existing implementation already matches the revised plan: it validates the input type (raising TypeError for non-str, covering AC-7 and EC-6), normalizes by keeping only str.isalnum() char
[2] tester_write   tester -> sandbox                Tests derive expected values directly from the specification. AC-1..AC-7 and EC-1..EC-6 each have a dedicated test. Two extra edge cases: test_ex1 checks the return is a plain bool (not a truthy non-bool), test_ex2 checks the input string is not mutated. EC-4 uses the corrected Unicode examples from the revised plan. EC-5 builds a 1,000,001-char palindrome to exercise linear-time behavior.
[3] run_tests     sandbox -> tester                 14 passed, 1 failed
[3] attribute      tester -> coder,tester,planner   SPEC_AMBIGUITY
[3] coder_fix       coder -> sandbox                [fix_tests] The implementation already correctly normalizes by keeping alphanumeric characters and lowercasing, then compares to the reverse. The failing test test_ec4_unicode_alnum is based on an inc
[4] run_tests     sandbox -> tester                 14 passed, 1 failed
[4] finalize       system -> user                   finished: max_test_iters
final_status: max_test_iters
output: results/runs/palindrome
python main.py  --real --task-id palindrome 2>&1  2.50s user 0.39s system 9% cpu 31.204 total
```

总用时 31.2 秒，共 26282 个 token。

### 每一轮失败的是什么

从 `trace.jsonl` 里提取的失败信息（这正是 Coder 能看到的内容，不包含测试源码）：

| 轮次 | 失败的测试 | 失败信息 | 归因结论 | 下一步 |
|---|---|---|---|---|
| 1 | `test_ec4_unicode_alnum` | `assert False is True`，`False = is_palindrome('Ésope é')` | TEST_BUG | Tester 修测试 |
| 2 | 同上 | `False = is_palindrome('Ésope éposÉ')` | TEST_BUG | 同一错误出现第 2 次，判定卡住，交给 Planner |
| 3 | 同上 | `False = is_palindrome('Ésope éposÉ é')` | SPEC_AMBIGUITY | Planner 已用完 1 次重新规划，交给 Coder |
| 4 | 同上 | 同上 | — | 达到 4 轮上限，停止 |

第 1 轮归因的理由（Tester 自己写的，摘录）：

> The test asserts is_palindrome('Ésope é') is True, claiming normalization yields a palindrome. However, normalization keeps alphanumeric chars and lowercases: 'Ésope é' -> 'ésopeé'. Reversed is 'éeposé', which is not equ…

最终的 `solution.py`：

```python
def is_palindrome(s: str) -> bool:
    """Return True if s is a palindrome ignoring case and non-alphanumeric chars.

    Normalization keeps only characters where ``ch.isalnum()`` is True and
    lowercases each kept character. The normalized string is then compared to
    its reverse. Empty or single-character normalized results are palindromes.

    Raises:
        TypeError: If ``s`` is not a ``str``.
    """
    if not isinstance(s, str):
        raise TypeError(
            "is_palindrome() argument must be a str, not %s"
            % type(s).__name__
        )

    normalized = "".join(ch.lower() for ch in s if ch.isalnum())
    return normalized == normalized[::-1]
```

最后一版仍然失败的测试：

```python
def test_ec4_unicode_alnum():
    assert is_palindrome('Ésope') is False
    assert is_palindrome('Ésope éposÉ') is False
    assert is_palindrome('Ésope éposÉ é') is True
```

`'Ésope éposÉ é'` 规范化后是 `ésopeéposéé`，倒过来是 `éésopéeposé`，两者不相等，所以返回 `False` 是对的。**代码从第一版起就是正确的，错的一直是测试里的期望值。**

### 从这个案例能看到什么

**做对了的部分**

- **错误归因生效**：前两轮都判为 TEST_BUG，交给 Tester 修，没有让 Coder 去改本来正确的代码。如果没有归因（对比实验 F），测试失败会直接交给 Coder，而 Coder 能改的只有这份本来正确的代码。
- **停滞检测生效**：同一个测试以同样的方式失败两次后，系统不再让 Tester 重复修，而是升级给 Planner 重新规划，Planner 只改了 EC-4。
- **轮数上限生效**：4 轮后停止，输出 `max_test_iters`，没有无限循环。
- **信息隔离下 Coder 没有乱改**：第 3 轮 Coder 只拿到失败信息，它在说明里指出代码已经符合规格、错在测试，最终代码保持原来的正确逻辑，没有为了让测试通过去硬编码。

**暴露的问题**

1. **Tester 手算 Unicode 字符串的期望值容易出错**。三次给出的「回文」例子都不是回文。Planner 在 v2 里修改 EC-4 后，新例子仍然是错的。4 个 Agent 用的是同一个模型，会犯相关的错误，这正是方案里写到的局限。
2. **路由有一个可以改进的地方**：第 3 轮归因是 SPEC_AMBIGUITY，但重新规划次数已经用完，按 `graph.py` 的规则交给了 Coder。Coder 改不了测试，这一轮白跑了。改进方向：重新规划次数用完时，SPEC_AMBIGUITY 交给 `tester_fix`；或者让 Tester 先用一段参考代码算出期望值，再写进测试。

这两点可以直接放进报告的 Analysis 和 Limitations 部分。

---

## 第 10 步：重复运行读缓存

再执行一次例 1 的同一条命令：

```console
(.venv) $ time python main.py "Implement merge_intervals(...同例 1...)" --real --task-id merge_intervals 2>&1 | tail -2
final_status: approved
output: results/runs/merge_intervals
python main.py  --real --task-id merge_intervals 2>&1  1.06s user 0.17s system 85% cpu 1.426 total
```

用时从 12.7 秒降到 1.4 秒，结果完全相同，没有新的模型调用（`.cache/llm/` 里的文件数运行前后都是 16）。录 demo 视频时先跑一遍，正式录制时就能稳定复现同样的流程。

---

## 第 11 步：图形界面

启动方式见 `README.md` 第 6 节：

```console
(.venv) $ streamlit run app.py
```

本次验证用 Streamlit 自带的测试工具 `AppTest` 自动操作界面：在输入框填入例 1 的需求，点击「Run DevCrew」。界面上 4 个指标卡片的值：

| 指标 | 值 |
|---|---|
| Steps completed | 6 |
| Test rounds | 1 |
| Tests passed | 15 |
| Review decision | Approved |

没有报错。因为需求和例 1 完全相同，这次读的是缓存。

---

## 附：真实运行中发现并修复的问题

在本次记录之前，第一次用真实模型运行时，Planner 直接报错：

```
devcrew.agents.planner.PlannerValidationError: invalid signature for is_palindrome: invalid syntax (<unknown>, line 1)
```

原因：DeepSeek 返回的函数签名带结尾冒号 `def is_palindrome(s: str) -> bool:`，Planner 和 Coder 的校验会在后面再拼一个 `: pass` 去解析，变成 `::` 导致语法错误。mock 测试里的签名都不带冒号，所以离线测试没有发现。

修复：`schemas.py` 的 `FunctionSpec` 在读入签名时统一去掉结尾冒号，并新增契约测试 `test_signature_trailing_colon_is_stripped`。修复已在提交 `9fead17` 中，本文记录的运行都基于这个版本。

---

## 汇总

| 运行 | 结果 | 测试轮数 | 用时 | token |
|---|---|---|---|---|
| mock 流程 | approved | 1 | 未计时 | 不调用模型 |
| 例 1 merge_intervals | approved | 1 | 12.7 秒 | 7733 |
| 例 2 is_palindrome | max_test_iters | 4 | 31.2 秒 | 26282 |
| 例 1 重复运行（缓存） | approved | 1 | 1.4 秒 | 不产生新调用 |
| 图形界面（例 1 需求） | Approved | 1 | 未计时 | 不产生新调用 |
