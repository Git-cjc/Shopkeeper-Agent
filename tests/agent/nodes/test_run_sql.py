from types import SimpleNamespace
from typing import get_type_hints
from unittest.mock import AsyncMock, Mock, call

import pytest

from app.agent.nodes.run_sql import RunSQLInputState, run_sql
from app.agent.state import DataAgentState


def test_run_sql_accepts_narrow_input_state_type():
    assert get_type_hints(run_sql)["state"] is RunSQLInputState


def test_data_agent_state_marks_progressive_fields_as_optional():
    assert "query" in DataAgentState.__required_keys__
    assert "error" in DataAgentState.__optional_keys__
    assert "execution_result" in DataAgentState.__optional_keys__
    assert "execution_error" in DataAgentState.__optional_keys__


@pytest.mark.anyio
async def test_run_sql_returns_execution_result_and_preserves_stream_events():
    writer = Mock()
    result = [{"total_sales": 123}]
    repository = SimpleNamespace(run=AsyncMock(return_value=result))
    runtime = SimpleNamespace(
        stream_writer=writer,
        context={"dw_mysql_repository": repository},
    )

    state: RunSQLInputState = {"sql": "select 1"}

    updated_state = await run_sql(state, runtime)

    assert updated_state == {
        "execution_result": result,
        "execution_error": None,
    }
    repository.run.assert_awaited_once_with("select 1")
    assert writer.call_args_list == [
        call({"type": "progress", "step": "执行SQL", "status": "running"}),
        call({"type": "progress", "step": "执行SQL", "status": "success"}),
        call({"type": "result", "data": result}),
    ]


@pytest.mark.anyio
async def test_run_sql_returns_execution_error_and_keeps_error_stream_event():
    writer = Mock()
    repository = SimpleNamespace(run=AsyncMock(side_effect=RuntimeError("boom")))
    runtime = SimpleNamespace(
        stream_writer=writer,
        context={"dw_mysql_repository": repository},
    )

    state: RunSQLInputState = {"sql": "select 1"}

    updated_state = await run_sql(state, runtime)

    assert updated_state == {
        "execution_result": None,
        "execution_error": "boom",
    }
    repository.run.assert_awaited_once_with("select 1")
    assert writer.call_args_list == [
        call({"type": "progress", "step": "执行SQL", "status": "running"}),
        call({"type": "progress", "step": "执行SQL", "status": "error"}),
        call({"type": "error", "message": "boom"}),
    ]
