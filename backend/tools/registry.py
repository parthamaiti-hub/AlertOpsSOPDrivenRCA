import logging
import os
import subprocess
import sys
import tempfile

from backend.tools.graphql_query import graphql_query
from backend.tools.health_check import health_check
from backend.tools.mcp_client import mcp_client
from backend.tools.prometheus_query import prometheus_query
from backend.tools.shell_script import shell_script
from backend.tools.splunk_query import splunk_query

logger = logging.getLogger(__name__)

# Mutable registry of tool callables. Pre-loaded with static fallbacks so that
# the registry works even when MongoDB is not yet available (e.g. unit tests).
TOOL_REGISTRY: dict[str, callable] = {
    "splunk_query": splunk_query,
    "prometheus_query": prometheus_query,
    "health_check": health_check,
    "mcp_client": mcp_client,
    "graphql_query": graphql_query,
    "shell_script": shell_script,
}


def _make_callable(tool_doc: dict):
    """Build a Python callable from a stored tool document."""
    tool_name = tool_doc["tool"]
    tech = tool_doc.get("tool_tech", "python_script")
    source = tool_doc.get("source_code", "")

    if tech in ("python_script", "mcp_client") and source:
        ns: dict = {}
        try:
            exec(compile(source, f"<tool:{tool_name}>", "exec"), ns)  # noqa: S102
        except Exception as exc:
            logger.warning("Failed to compile tool %s: %s", tool_name, exc)
            return None
        # Prefer a function named 'execute', fall back to tool name
        return ns.get("execute") or ns.get(tool_name)

    if tech == "shell_script" and source:
        _source = source  # capture for closure

        def _shell_runner(**kwargs):
            suffix = ".ps1" if sys.platform == "win32" else ".sh"
            with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8") as f:
                f.write(_source)
                tmp = f.name
            try:
                cmd = ["pwsh", "-File", tmp] if sys.platform == "win32" else ["bash", tmp]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)  # noqa: S603
                return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}
            finally:
                os.unlink(tmp)

        return _shell_runner

    return None


def _load_from_db() -> None:
    """Load tool callables from MongoDB and augment TOOL_REGISTRY.

    Falls back silently if MongoDB is not available.
    """
    try:
        from backend.tools.db import list_active_tools

        for tool_doc in list_active_tools():
            fn = _make_callable(tool_doc)
            if fn is not None:
                TOOL_REGISTRY[tool_doc["tool"]] = fn
    except Exception as exc:
        logger.debug("Tool DB load skipped (DB not ready): %s", exc)


_load_from_db()


def execute_tool(tool_name: str, params: dict) -> dict:
    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None:
        return {"error": f"Unknown tool: {tool_name}"}
    return fn(**params)
