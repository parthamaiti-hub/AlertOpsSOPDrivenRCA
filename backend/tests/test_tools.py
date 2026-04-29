from unittest.mock import MagicMock, patch

from backend.tools.splunk_query import splunk_query
from backend.tools.prometheus_query import prometheus_query
from backend.tools.health_check import health_check
from backend.tools.registry import execute_tool, TOOL_REGISTRY


def test_splunk_query():
    result = splunk_query("index=app_logs level=ERROR", "1h")
    assert "entries" in result
    assert result["total_results"] > 0
    assert all("timestamp" in e for e in result["entries"])


def test_prometheus_query():
    result = prometheus_query("rate(cpu[5m])", "60s", "1h")
    assert "values" in result
    assert result["data_points"] > 0
    assert all("value" in v for v in result["values"])


def test_prometheus_cpu_detection():
    result = prometheus_query("rate(process_cpu_seconds_total[5m])")
    assert result["metric_name"] == "process_cpu_seconds_total"


def test_health_check():
    result = health_check("http://localhost:8080/health", 5)
    assert "status_code" in result
    assert "healthy" in result


def test_registry_known_tool():
    result = execute_tool("splunk_query", {"query": "test", "time_range": "1h"})
    assert "entries" in result


def test_registry_unknown_tool():
    result = execute_tool("unknown_tool", {})
    assert "error" in result


def test_registry_unknown_tool_returns_error_dict():
    """Tool returning error dict should be detectable as failure."""
    result = execute_tool("nonexistent_tool", {"query": "test"})
    assert isinstance(result, dict)
    assert "error" in result


def test_execute_tool_exception_handling():
    """A tool that raises an exception should be caught by the caller."""
    def failing_tool(**kwargs):
        raise ConnectionError("connection refused")

    TOOL_REGISTRY["failing_test_tool"] = failing_tool
    try:
        # execute_tool does not catch exceptions itself; the ExecuteSOP agent does.
        # Here we verify the tool raises so the agent's try/except will catch it.
        raised = False
        try:
            execute_tool("failing_test_tool", {"query": "test"})
        except ConnectionError:
            raised = True
        assert raised
    finally:
        del TOOL_REGISTRY["failing_test_tool"]


def test_tool_error_detection_in_output():
    """Verify that error results from tools can be detected programmatically."""
    result = execute_tool("unknown_tool", {})
    # The ExecuteSOP agent checks: isinstance(output, dict) and "error" in output
    assert isinstance(result, dict) and "error" in result


# ── Service layer tests (DB mocked) ─────────────────────────────────────────


def _mock_tool_doc(**overrides):
    base = {
        "tool": "my_tool",
        "tool_version": "1.0",
        "tool_tech": "python_script",
        "description": "Test tool",
        "tool_params": [],
        "source_code": "",
        "source_file": "",
        "change_type": "created",
        "changed_by": "user",
    }
    base.update(overrides)
    return base


def test_service_list_tools_empty():
    """list_tools returns empty list when DB has no tools."""
    with patch("backend.tools.service.list_active_tools", return_value=[]):
        from backend.tools.service import list_tools

        result = list_tools()
        assert result == []


def test_service_get_tool_not_found():
    with patch("backend.tools.service.get_active_tool", return_value=None):
        from backend.tools.service import get_tool

        assert get_tool("no_such_tool") is None


def test_service_get_tool_returns_clean_doc():
    doc = _mock_tool_doc(_id="abc123")
    with patch("backend.tools.service.get_active_tool", return_value=doc):
        from backend.tools.service import get_tool

        result = get_tool("my_tool")
        assert "_id" not in result
        assert result["tool"] == "my_tool"


def test_service_get_allowed_versions():
    doc = _mock_tool_doc(tool_version="1.2")
    with patch("backend.tools.service.get_active_tool", return_value=doc):
        from backend.tools.service import get_allowed_versions

        result = get_allowed_versions("my_tool")
        assert result["current_version"] == "1.2"
        assert "1.3" in result["allowed_versions"]
        assert "2.0" in result["allowed_versions"]


def test_service_create_tool_success():
    with (
        patch("backend.tools.service.get_active_tool", return_value=None),
        patch("backend.tools.service.save_tool", side_effect=lambda d: {**d, "_id": "new_id"}),
        patch("backend.tools.service.archive_tool"),
    ):
        from backend.tools.service import create_tool

        doc, err = create_tool(
            {"tool": "new_tool", "tool_version": "1.0", "tool_tech": "python_script", "description": "A new tool"}
        )
        assert err is None
        assert doc["tool"] == "new_tool"
        assert "_id" not in doc


def test_service_create_tool_duplicate_error():
    existing = _mock_tool_doc()
    with patch("backend.tools.service.get_active_tool", return_value=existing):
        from backend.tools.service import create_tool

        _, err = create_tool({"tool": "my_tool", "tool_version": "1.0", "tool_tech": "python_script"})
        assert err is not None
        assert "already exists" in err


def test_service_update_tool_valid_progression():
    current = _mock_tool_doc(tool_version="1.0")
    with (
        patch("backend.tools.service.get_active_tool", return_value=current),
        patch("backend.tools.service.archive_tool"),
        patch("backend.tools.service.save_tool", side_effect=lambda d: {**d, "_id": "new_id"}),
    ):
        from backend.tools.service import update_tool

        doc, err = update_tool("my_tool", {"tool_version": "1.1", "source_code": "# updated"})
        assert err is None
        assert doc["tool_version"] == "1.1"


def test_service_update_tool_invalid_version():
    current = _mock_tool_doc(tool_version="1.0")
    with patch("backend.tools.service.get_active_tool", return_value=current):
        from backend.tools.service import update_tool

        _, err = update_tool("my_tool", {"tool_version": "1.5"})
        assert err is not None
        assert "1.1" in err or "2.0" in err


def test_make_callable_python_script():
    """_make_callable should exec source code and return the named function."""
    from backend.tools.registry import _make_callable

    source = "def my_tool(**kwargs):\n    return {'ok': True}\n"
    tool_doc = {"tool": "my_tool", "tool_tech": "python_script", "source_code": source}
    fn = _make_callable(tool_doc)
    assert fn is not None
    assert fn() == {"ok": True}

