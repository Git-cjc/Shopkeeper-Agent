# 问数评测集设计说明

## 背景

当前仓库已经具备完整的问数主链路：

- 自然语言问题输入
- 关键词抽取
- 字段 / 指标 / 字段取值三路召回
- SQL 生成、校验、修正、执行

这足以证明系统“能跑通”，但还不能系统证明：

- 生成出来的 SQL 是否真的答对了问题
- 执行链路的稳定性如何
- 召回阶段是否拿到了支撑 SQL 生成的关键信息

本设计的目标，是在不改造前端交互形态的前提下，为当前仓库补一套**可重复运行的离线评测体系**。

## 目标

新增一套“问数评测集 + 离线评测脚本 + 指标报告”能力，用 20 条起步、可扩展到 50 条的中文问题，对现有问数 Agent 统计以下指标：

- `SQL 正确率`
- `SQL 执行成功率`
- `召回质量`

其中：

- `SQL 正确率` 以**结果是否正确**为主，而不是 SQL 文本是否逐字一致
- `SQL 执行成功率` 以是否成功走到执行并返回结果为准
- `召回质量` 以字段 / 指标 / 取值的**召回覆盖率**为主，而不是排序指标

## 非目标

本次不做以下内容：

- 不新增前端评测页面
- 不新增独立评测 API
- 不做在线实时评测
- 不引入复杂打分平台或外部标注系统
- 不把评测结果自动回写数据库

## 设计原则

### 1. 复用现有问数链路

评测脚本直接复用现有 LangGraph 图和仓储依赖，不新造一套“模拟问数流程”。

这样评测结果才反映真实系统表现，而不是反映一个旁路 demo。

### 2. 结果正确优先于 SQL 文本一致

同一个问题可能存在多种等价 SQL 写法。  
因此主指标不采用“与标注 SQL 完全匹配”，而采用：

- 执行生成 SQL
- 执行参考 SQL
- 对比两个结果集是否一致

如果结果一致，则记为 `SQL 正确`。

### 3. 召回质量先做覆盖率，不做 hit@k

当前三路召回节点会把多个关键词的命中结果合并去重，但不会保留稳定排序。  
在这种前提下，做 `hit@k` 或 `MRR` 会得到不可信结果。

因此 v1 的召回指标定义为：

- 字段召回覆盖率
- 指标召回覆盖率
- 取值召回覆盖率
- 问题级全量召回率

如果后续召回链路显式保存排序，再扩展 `hit@k` 类指标。

## 交付物

### 1. 评测数据集

新增一份人工设计的中文问数评测集，首版包含 20 条问题，后续可扩展到 50 条。

每条样本至少包含：

- `id`: 样本唯一标识
- `question`: 自然语言问题
- `reference_sql`: 参考 SQL
- `expected_columns`: 期望召回到的字段 id 列表
- `expected_metrics`: 期望召回到的指标 id 列表
- `expected_values`: 期望召回到的字段取值 id 列表
- `tags`: 题目标签，用于分组统计
- `notes`: 可选说明，记录口径或边界解释

### 2. 离线评测脚本

新增一个可直接运行的 CLI 脚本，完成以下流程：

1. 加载评测数据集
2. 初始化现有依赖（Embedding、Qdrant、ES、Meta MySQL、DW MySQL）
3. 对每条问题运行问数 Agent
4. 收集最终 SQL、执行结果、召回结果、错误信息
5. 执行参考 SQL
6. 比对结果并打分
7. 输出汇总报告和逐题明细

### 3. 评测报告

脚本输出两类报告：

- `summary.json` / `summary.md`
  - 总样本数
  - SQL 正确率
  - SQL 执行成功率
  - 字段 / 指标 / 取值召回覆盖率
  - 问题级全量召回率
  - 按标签分组的子指标
- `details.json`
  - 每题原始问题
  - 生成 SQL
  - 参考 SQL
  - 执行状态
  - 结果是否一致
  - 各类召回是否命中
  - 失败原因

## 数据模型

### 评测样本

建议引入独立的数据模型，例如：

```python
@dataclass
class QueryEvalCase:
    id: str
    question: str
    reference_sql: str
    expected_columns: list[str]
    expected_metrics: list[str]
    expected_values: list[str]
    tags: list[str]
    notes: str | None = None
```

### 单题评测结果

```python
@dataclass
class QueryEvalResult:
    case_id: str
    question: str
    generated_sql: str | None
    reference_sql: str
    execution_success: bool
    sql_correct: bool
    generated_result: list[dict] | None
    reference_result: list[dict] | None
    retrieved_column_ids: list[str]
    retrieved_metric_ids: list[str]
    retrieved_value_ids: list[str]
    column_recall_hit: bool
    metric_recall_hit: bool
    value_recall_hit: bool
    full_recall_hit: bool
    error_message: str | None
    tags: list[str]
```

### 汇总结果

```python
@dataclass
class QueryEvalSummary:
    total_cases: int
    sql_accuracy: float
    execution_success_rate: float
    column_recall_coverage: float
    metric_recall_coverage: float
    value_recall_coverage: float
    full_recall_rate: float
    by_tag: dict[str, dict[str, float]]
```

## 需要补的链路可观测性

当前状态里已经有：

- `retrieved_column_infos`
- `retrieved_metric_infos`
- `retrieved_value_infos`
- `sql`

因此召回结果和最终 SQL 基本够用。

但 `run_sql` 节点当前只把结果写进流式输出，没有写回最终状态。  
为了让离线评测不依赖 SSE 文本解析，需要做一个最小改动：

- 在 `DataAgentState` 中新增执行结果字段
- `run_sql` 成功时把结果写回 state
- `run_sql` 失败时把错误文本写回 state

这样评测脚本就可以通过图的最终状态拿到：

- 最终 SQL
- 最终执行结果
- 执行错误

## 打分定义

### SQL 正确率

定义：

`sql_correct == True` 的样本数 / 总样本数

判定方式：

1. 如果生成 SQL 没有成功执行，记为 `False`
2. 成功执行参考 SQL，得到基准结果
3. 对生成结果和参考结果做归一化比较
4. 完全一致则记为 `True`

归一化规则：

- 结果统一转成 `list[dict]`
- 按键名字典序稳定排序字段
- 按整行内容排序行顺序
- 将 `Decimal`、日期等不可直接比较对象转成稳定字符串

这样可以避免仅因返回顺序不同而误判。

### SQL 执行成功率

定义：

`execution_success == True` 的样本数 / 总样本数

只要生成 SQL 在真实数仓中执行成功并返回结果，就算成功；结果是否正确另算。

### 召回质量

对每个样本，根据人工标注的锚点做覆盖率判定：

- `column_recall_hit`: `expected_columns` 是否全部包含在实际召回字段 id 中
- `metric_recall_hit`: `expected_metrics` 是否全部包含在实际召回指标 id 中
- `value_recall_hit`: `expected_values` 是否全部包含在实际召回取值 id 中
- `full_recall_hit`: 三者同时为真

汇总层输出：

- 字段召回覆盖率
- 指标召回覆盖率
- 取值召回覆盖率
- 问题级全量召回率

## 题目设计范围

首版 20 条问题建议覆盖以下类型：

- 基础聚合：总销售额、总订单数、总用户数
- 过滤查询：按地区、品类、用户等级、支付方式过滤
- 时间分析：昨日、最近 7 天、本月、上月、今年
- 分组统计：按地区 / 品类 / 日期分组
- TopN：销量前 10、销售额最高的品类
- 指标理解：GMV、AOV、订单量、用户数
- 枚举值识别：华北、华东、会员、家电、美妆等

要求每题尽量只验证一到两个核心能力，避免单题混入过多隐含约束。

## 文件布局

建议新增：

- `app/evaluation/`
  - 评测模型、数据集加载、执行器、打分逻辑
- `app/evaluation/datasets/query_eval_set.yaml`
  - 人工标注评测集
- `app/scripts/evaluate_query_set.py`
  - CLI 入口
- `tests/evaluation/`
  - 评测模块单测

建议修改：

- `app/agent/state.py`
- `app/agent/nodes/run_sql.py`
- 如有必要，补少量 README 文档说明

## 运行方式

建议先支持最小 CLI：

```bash
uv run python -m app.scripts.evaluate_query_set
```

可选参数：

- `--dataset-path`
- `--output-dir`
- `--case-id`
- `--tag`

这样既能全量评测，也能只跑单题或某一类题目。

## 风险与取舍

### 1. LLM 输出不稳定

同一问题多次执行可能生成不同 SQL。  
这是评测对象本身的一部分，不在 v1 中做多次采样平均，先按单次运行统计。

### 2. 参考 SQL 本身可能写错

人工标注集必须可执行，并且需要至少做一次人工校验。  
否则会把错误标注当成系统错误。

### 3. 结果正确不代表过程完全正确

某些问题可能“碰巧答对”，但召回质量较差。  
因此必须同时保留结果指标和召回指标，而不是只看最终结果。

### 4. 当前不做排序型召回指标

这是刻意限制，不是缺陷遗漏。  
等召回链路保留稳定分数和排序后，再引入 `hit@k` / `MRR`。

## 默认实现决策

本设计锁定以下默认决策：

- 主交付形态：离线脚本 + 数据集 + 报告
- `SQL 正确率` 主口径：结果正确，而不是 SQL 文本完全匹配
- 召回质量主口径：覆盖率，而不是排序指标
- 首版数据集规模：20 条
- 结果报告格式：`summary.md + summary.json + details.json`
- 评测脚本直接复用现有 LangGraph 和 Repository 依赖

## 后续扩展

如果 v1 跑通，后续可以继续补：

- 从 20 条扩展到 50 条
- 增加按步骤耗时统计
- 增加失败类型分类（召回失败 / SQL 生成失败 / 执行失败）
- 增加多次采样评测
- 增加排序型召回指标
