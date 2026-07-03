# 问数评测集 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为现有问数 Agent 增加一套可重复运行的离线评测体系，包含 20 条中文评测问题、结果正确率/执行成功率/召回覆盖率统计以及明细报告输出。

**Architecture:** 新增独立的 `app.evaluation` 模块承载评测数据模型、数据集加载、运行器和打分逻辑；复用现有 LangGraph 工作流与仓储依赖执行真实问数链路；只对 Agent 状态做最小增强，让 `run_sql` 把最终执行结果写回状态，供离线评测读取。

**Tech Stack:** Python 3.14、LangGraph、FastAPI 现有依赖、MySQL/Qdrant/Elasticsearch 现有仓储、PyYAML、pytest、pytest-asyncio

---

### Task 1: 补齐评测所需的状态可观测性

**Files:**
- Modify: `app/agent/state.py`
- Modify: `app/agent/nodes/run_sql.py`
- Test: `tests/agent/nodes/test_run_sql.py`

- [ ] **Step 1: 写失败测试，锁定 `run_sql` 需要把执行结果写回状态**

```python
import pytest

from app.agent.nodes.run_sql import run_sql


class DummyRepository:
    async def run(self, sql: str):
        return [{"gmv": 100}]


class DummyRuntime:
    def __init__(self):
        self.context = {"dw_mysql_repository": DummyRepository()}
        self.events = []

    def stream_writer(self, payload):
        self.events.append(payload)


@pytest.mark.asyncio
async def test_run_sql_returns_execution_result():
    runtime = DummyRuntime()
    runtime.stream_writer = runtime.stream_writer

    state = {"sql": "select 1 as gmv"}
    result = await run_sql(state, runtime)

    assert result == {"execution_result": [{"gmv": 100}], "execution_error": None}
```

- [ ] **Step 2: 运行测试，确认当前实现还不会返回 `execution_result`**

Run: `uv run pytest tests/agent/nodes/test_run_sql.py -q`
Expected: FAIL，断言 `run_sql` 返回值不包含 `execution_result`

- [ ] **Step 3: 扩展状态定义并修改 `run_sql` 返回结构**

```python
from typing import NotRequired, TypedDict


class DataAgentState(TypedDict):
    query: str
    keywords: list[str]
    retrieved_column_infos: list[ColumnInfo]
    retrieved_metric_infos: list[MetricInfo]
    retrieved_value_infos: list[ValueInfo]
    table_infos: list[TableInfoState]
    metric_infos: list[MetricInfoState]
    date_info: DateInfoState
    db_info: DBInfoState
    sql: str
    error: str
    execution_result: NotRequired[list[dict] | None]
    execution_error: NotRequired[str | None]
```

```python
async def run_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    step = "执行SQL"
    writer({"type": "progress", "step": step, "status": "running"})

    try:
        sql = state["sql"]
        dw_mysql_repository = runtime.context["dw_mysql_repository"]
        result = await dw_mysql_repository.run(sql)
        writer({"type": "progress", "step": step, "status": "success"})
        writer({"type": "result", "data": result})
        return {"execution_result": result, "execution_error": None}
    except Exception as e:
        writer({"type": "progress", "step": step, "status": "error"})
        return {"execution_result": None, "execution_error": str(e)}
```

- [ ] **Step 4: 重新运行测试，确认状态可供评测器消费**

Run: `uv run pytest tests/agent/nodes/test_run_sql.py -q`
Expected: PASS

- [ ] **Step 5: 提交这一小步改动**

```bash
git add app/agent/state.py app/agent/nodes/run_sql.py tests/agent/nodes/test_run_sql.py
git commit -m "feat: expose query execution result in agent state"
```

### Task 2: 新增评测领域模型、数据集加载和打分逻辑

**Files:**
- Create: `app/evaluation/__init__.py`
- Create: `app/evaluation/models.py`
- Create: `app/evaluation/dataset.py`
- Create: `app/evaluation/scoring.py`
- Create: `app/evaluation/datasets/query_eval_set.yaml`
- Test: `tests/evaluation/test_dataset.py`
- Test: `tests/evaluation/test_scoring.py`

- [ ] **Step 1: 写失败测试，锁定数据集加载和结果对比规则**

```python
from pathlib import Path

from app.evaluation.dataset import load_eval_cases
from app.evaluation.scoring import compare_results, score_recall


def test_load_eval_cases_reads_yaml_dataset(tmp_path: Path):
    dataset = tmp_path / "cases.yaml"
    dataset.write_text(
        """
cases:
  - id: case_001
    question: 统计华北地区销售额
    reference_sql: select 1 as gmv
    expected_columns: [fact_order.order_amount]
    expected_metrics: [GMV]
    expected_values: [dim_region.region_name.华北]
    tags: [region, metric]
""".strip(),
        encoding="utf-8",
    )

    cases = load_eval_cases(dataset)

    assert len(cases) == 1
    assert cases[0].id == "case_001"


def test_compare_results_treats_row_order_as_irrelevant():
    generated = [{"region": "华北", "gmv": 10}, {"region": "华东", "gmv": 20}]
    reference = [{"gmv": 20, "region": "华东"}, {"gmv": 10, "region": "华北"}]

    assert compare_results(generated, reference) is True


def test_score_recall_requires_all_expected_anchors():
    result = score_recall(
        expected_ids=["GMV", "AOV"],
        actual_ids=["AOV", "GMV", "ORDER_CNT"],
    )

    assert result is True
```

- [ ] **Step 2: 运行测试，确认评测模块尚未存在**

Run: `uv run pytest tests/evaluation/test_dataset.py tests/evaluation/test_scoring.py -q`
Expected: FAIL，提示 `app.evaluation` 模块不存在

- [ ] **Step 3: 实现评测模型、加载器、结果比较与召回覆盖率逻辑**

```python
from dataclasses import dataclass


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

```python
import yaml

from app.evaluation.models import QueryEvalCase


def load_eval_cases(path):
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [QueryEvalCase(**item) for item in payload["cases"]]
```

```python
from decimal import Decimal


def _normalize_cell(value):
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def compare_results(generated: list[dict] | None, reference: list[dict] | None) -> bool:
    if generated is None or reference is None:
        return False

    def normalize(rows: list[dict]) -> list[tuple[tuple[str, str], ...]]:
        normalized = []
        for row in rows:
            normalized.append(
                tuple(sorted((key, _normalize_cell(value)) for key, value in row.items()))
            )
        return sorted(normalized)

    return normalize(generated) == normalize(reference)


def score_recall(expected_ids: list[str], actual_ids: list[str]) -> bool:
    return set(expected_ids).issubset(set(actual_ids))
```

- [ ] **Step 4: 编写首版 20 条评测样本**

```yaml
cases:
  - id: case_001
    question: 统计华北地区销售总额
    reference_sql: >
      select sum(order_amount) as gmv
      from fact_order
      where region_name = '华北'
    expected_columns: [fact_order.order_amount]
    expected_metrics: [GMV]
    expected_values: [dim_region.region_name.华北]
    tags: [region, aggregation, metric]
```

要求数据集覆盖：

- 地区过滤
- 品类过滤
- 会员等级过滤
- 时间过滤
- 分组统计
- TopN
- GMV / AOV / 订单量 / 用户数等指标

- [ ] **Step 5: 重新运行测试**

Run: `uv run pytest tests/evaluation/test_dataset.py tests/evaluation/test_scoring.py -q`
Expected: PASS

- [ ] **Step 6: 提交这一小步改动**

```bash
git add app/evaluation tests/evaluation
git commit -m "feat: add evaluation dataset and scoring primitives"
```

### Task 3: 新增评测运行器和 CLI 入口

**Files:**
- Create: `app/evaluation/runner.py`
- Create: `app/scripts/evaluate_query_set.py`
- Modify: `pyproject.toml`
- Test: `tests/evaluation/test_runner.py`

- [ ] **Step 1: 写失败测试，锁定运行器要同时返回执行结果和召回锚点**

```python
import pytest

from app.evaluation.models import QueryEvalCase
from app.evaluation.runner import build_eval_result


@pytest.mark.asyncio
async def test_build_eval_result_collects_sql_execution_and_recall():
    case = QueryEvalCase(
        id="case_001",
        question="统计华北地区销售总额",
        reference_sql="select 1 as gmv",
        expected_columns=["fact_order.order_amount"],
        expected_metrics=["GMV"],
        expected_values=["dim_region.region_name.华北"],
        tags=["smoke"],
    )

    final_state = {
        "sql": "select 1 as gmv",
        "execution_result": [{"gmv": 1}],
        "execution_error": None,
        "retrieved_column_infos": [{"id": "fact_order.order_amount"}],
        "retrieved_metric_infos": [{"id": "GMV"}],
        "retrieved_value_infos": [{"id": "dim_region.region_name.华北"}],
    }

    result = await build_eval_result(case, final_state, [{"gmv": 1}])

    assert result.sql_correct is True
    assert result.full_recall_hit is True
```

- [ ] **Step 2: 运行测试，确认运行器尚未实现**

Run: `uv run pytest tests/evaluation/test_runner.py -q`
Expected: FAIL，提示 `app.evaluation.runner` 不存在

- [ ] **Step 3: 实现运行器，直接复用现有图和仓储依赖**

```python
async def run_eval_case(case: QueryEvalCase, context: DataAgentContext, dw_repository):
    initial_state = {"query": case.question}
    final_state = await graph.ainvoke(initial_state, context=context)
    reference_result = await dw_repository.run(case.reference_sql)
    return await build_eval_result(case, final_state, reference_result)
```

```python
async def build_eval_result(case, final_state, reference_result):
    generated_sql = final_state.get("sql")
    generated_result = final_state.get("execution_result")
    execution_error = final_state.get("execution_error")

    retrieved_column_ids = [item["id"] if isinstance(item, dict) else item.id for item in final_state.get("retrieved_column_infos", [])]
    retrieved_metric_ids = [item["id"] if isinstance(item, dict) else item.id for item in final_state.get("retrieved_metric_infos", [])]
    retrieved_value_ids = [item["id"] if isinstance(item, dict) else item.id for item in final_state.get("retrieved_value_infos", [])]

    column_hit = score_recall(case.expected_columns, retrieved_column_ids)
    metric_hit = score_recall(case.expected_metrics, retrieved_metric_ids)
    value_hit = score_recall(case.expected_values, retrieved_value_ids)

    return QueryEvalResult(
        case_id=case.id,
        question=case.question,
        generated_sql=generated_sql,
        reference_sql=case.reference_sql,
        execution_success=execution_error is None and generated_result is not None,
        sql_correct=compare_results(generated_result, reference_result),
        generated_result=generated_result,
        reference_result=reference_result,
        retrieved_column_ids=retrieved_column_ids,
        retrieved_metric_ids=retrieved_metric_ids,
        retrieved_value_ids=retrieved_value_ids,
        column_recall_hit=column_hit,
        metric_recall_hit=metric_hit,
        value_recall_hit=value_hit,
        full_recall_hit=column_hit and metric_hit and value_hit,
        error_message=execution_error,
        tags=case.tags,
    )
```

- [ ] **Step 4: 实现 CLI，支持全量和按 case/tag 子集运行**

```python
import argparse
import asyncio
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-path", type=Path, default=Path("app/evaluation/datasets/query_eval_set.yaml"))
    parser.add_argument("--output-dir", type=Path, default=Path("reports/query-eval"))
    parser.add_argument("--case-id")
    parser.add_argument("--tag")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main())
```

`pyproject.toml` 的 `dev` 依赖同步补上：

```toml
[dependency-groups]
dev = [
    "pre-commit>=4.3.0",
    "pytest>=8.4.2",
    "pytest-asyncio>=1.2.0",
    "ruff>=0.11.0",
]
```

- [ ] **Step 5: 重新运行测试**

Run: `uv run pytest tests/evaluation/test_runner.py -q`
Expected: PASS

- [ ] **Step 6: 提交这一小步改动**

```bash
git add app/evaluation app/scripts/evaluate_query_set.py pyproject.toml tests/evaluation/test_runner.py
git commit -m "feat: add offline query evaluation runner"
```

### Task 4: 输出汇总报告并补文档说明

**Files:**
- Modify: `app/evaluation/runner.py`
- Modify: `README.md`
- Test: `tests/evaluation/test_runner.py`

- [ ] **Step 1: 写失败测试，锁定汇总统计和 Markdown 报告格式**

```python
from app.evaluation.runner import summarize_results
from app.evaluation.models import QueryEvalResult


def test_summarize_results_computes_global_and_tag_metrics():
    results = [
        QueryEvalResult(
            case_id="case_001",
            question="q1",
            generated_sql="select 1",
            reference_sql="select 1",
            execution_success=True,
            sql_correct=True,
            generated_result=[{"v": 1}],
            reference_result=[{"v": 1}],
            retrieved_column_ids=["c1"],
            retrieved_metric_ids=["m1"],
            retrieved_value_ids=["v1"],
            column_recall_hit=True,
            metric_recall_hit=True,
            value_recall_hit=True,
            full_recall_hit=True,
            error_message=None,
            tags=["smoke"],
        )
    ]

    summary = summarize_results(results)

    assert summary.total_cases == 1
    assert summary.sql_accuracy == 1.0
    assert summary.by_tag["smoke"]["sql_accuracy"] == 1.0
```

- [ ] **Step 2: 运行测试，确认汇总函数尚未完整实现**

Run: `uv run pytest tests/evaluation/test_runner.py -q`
Expected: FAIL，断言汇总结构不完整

- [ ] **Step 3: 实现汇总、JSON 明细输出和 Markdown 摘要输出**

```python
def summarize_results(results: list[QueryEvalResult]) -> QueryEvalSummary:
    total = len(results)
    return QueryEvalSummary(
        total_cases=total,
        sql_accuracy=sum(item.sql_correct for item in results) / total,
        execution_success_rate=sum(item.execution_success for item in results) / total,
        column_recall_coverage=sum(item.column_recall_hit for item in results) / total,
        metric_recall_coverage=sum(item.metric_recall_hit for item in results) / total,
        value_recall_coverage=sum(item.value_recall_hit for item in results) / total,
        full_recall_rate=sum(item.full_recall_hit for item in results) / total,
        by_tag=build_tag_metrics(results),
    )
```

Markdown 摘要至少包含：

- 总样本数
- SQL 正确率
- 执行成功率
- 三类召回覆盖率
- 问题级全量召回率
- 标签分组表格

- [ ] **Step 4: 在 `README.md` 补一个最小使用说明**

```markdown
## 问数评测

运行离线评测：

~~~bash
uv run python -m app.scripts.evaluate_query_set
~~~

默认读取 `app/evaluation/datasets/query_eval_set.yaml`，并输出汇总与明细报告到 `reports/query-eval/`。
```

- [ ] **Step 5: 运行目标测试和一次 smoke 评测**

Run: `uv run pytest tests/agent/nodes/test_run_sql.py tests/evaluation -q`
Expected: PASS

Run: `uv run python -m app.scripts.evaluate_query_set --case-id case_001 2>&1 | head -c 4000`
Expected: 生成 `summary.json`、`summary.md`、`details.json`

- [ ] **Step 6: 提交这一小步改动**

```bash
git add README.md app/evaluation/runner.py tests/evaluation
git commit -m "docs: document offline query evaluation workflow"
```

### Task 5: 做一次全量验收

**Files:**
- Modify: `app/evaluation/datasets/query_eval_set.yaml`
- Test: `tests/agent/nodes/test_run_sql.py`
- Test: `tests/evaluation/test_dataset.py`
- Test: `tests/evaluation/test_scoring.py`
- Test: `tests/evaluation/test_runner.py`

- [ ] **Step 1: 逐条人工检查 20 条样本的参考 SQL 是否都能执行**

Run: `uv run python -m app.scripts.evaluate_query_set --output-dir /tmp/query-eval-smoke 2>&1 | head -c 4000`
Expected: 无参考 SQL 执行错误

- [ ] **Step 2: 如有失败样本，只修数据集，不先改业务逻辑**

```yaml
cases:
  - id: case_00x
    notes: 修正时间口径，避免参考 SQL 与题意不一致
```

- [ ] **Step 3: 跑完整测试集**

Run: `uv run pytest tests/agent/nodes/test_run_sql.py tests/evaluation -q`
Expected: PASS

- [ ] **Step 4: 记录当前首版基线指标**

至少记录：

- 样本总数
- SQL 正确率
- 执行成功率
- 字段 / 指标 / 取值召回覆盖率
- 问题级全量召回率

- [ ] **Step 5: 提交最终实现**

```bash
git add app README.md pyproject.toml tests
git commit -m "feat: add offline query evaluation suite"
```
