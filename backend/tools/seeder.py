import logging
import pathlib
from datetime import UTC, datetime

from backend.models.database import tools_col_sync, tools_history_col_sync

logger = logging.getLogger(__name__)

_TOOLS_DIR = pathlib.Path(__file__).parent

_INITIAL_TOOL_DEFS = [
    {
        "tool": "splunk_query",
        "tool_version": "1.0",
        "tool_tech": "python_script",
        "description": "Query Splunk logs using SPL. Returns matching log entries.",
        "tool_params": [
            {"name": "query", "description": "SPL query string", "required": True, "default": None},
            {"name": "time_range", "description": "Time range (e.g. 1h, 24h)", "required": False, "default": "1h"},
        ],
        "source_file": "backend/tools/splunk_query.py",
        "_source_filename": "splunk_query.py",
    },
    {
        "tool": "prometheus_query",
        "tool_version": "1.0",
        "tool_tech": "python_script",
        "description": "Query Prometheus metrics using PromQL. Returns time-series data.",
        "tool_params": [
            {"name": "query", "description": "PromQL expression", "required": True, "default": None},
            {"name": "step", "description": "Resolution step (e.g. 60s)", "required": False, "default": "60s"},
            {"name": "duration", "description": "Query duration (e.g. 1h)", "required": False, "default": "1h"},
        ],
        "source_file": "backend/tools/prometheus_query.py",
        "_source_filename": "prometheus_query.py",
    },
    {
        "tool": "health_check",
        "tool_version": "1.0",
        "tool_tech": "python_script",
        "description": "Check the health of an HTTP endpoint. Returns status and response time.",
        "tool_params": [
            {"name": "url", "description": "HTTP endpoint URL to check", "required": True, "default": None},
            {"name": "timeout", "description": "Request timeout in seconds", "required": False, "default": "5"},
        ],
        "source_file": "backend/tools/health_check.py",
        "_source_filename": "health_check.py",
    },
    {
        "tool": "mcp_client",
        "tool_version": "1.0",
        "tool_tech": "mcp_client",
        "description": "Call a named tool on a remote MCP (Model Context Protocol) server. Supports file reads, search, list, and generic JSON tool calls.",
        "tool_params": [
            {"name": "server_url", "description": "MCP server base URL", "required": True, "default": None},
            {"name": "tool_name", "description": "Name of the MCP tool to invoke", "required": True, "default": None},
            {"name": "arguments", "description": "Key-value arguments to pass to the MCP tool", "required": False, "default": "{}"},
        ],
        "source_file": "backend/tools/mcp_client.py",
        "_source_filename": "mcp_client.py",
    },
    {
        "tool": "graphql_query",
        "tool_version": "1.0",
        "tool_tech": "python_script",
        "description": "Execute a GraphQL query against an API endpoint. Returns deployment, incident, or service metric data.",
        "tool_params": [
            {"name": "endpoint", "description": "GraphQL API endpoint URL", "required": True, "default": None},
            {"name": "query", "description": "GraphQL query string", "required": True, "default": None},
            {"name": "variables", "description": "GraphQL query variables as key-value dict", "required": False, "default": "{}"},
        ],
        "source_file": "backend/tools/graphql_query.py",
        "_source_filename": "graphql_query.py",
    },
    {
        "tool": "shell_script",
        "tool_version": "1.0",
        "tool_tech": "python_script",
        "description": "Run a diagnostic shell script on a remote host. Supports df, top/ps, free, netstat, kubectl commands.",
        "tool_params": [
            {"name": "script", "description": "Shell command or script body to execute", "required": True, "default": None},
            {"name": "args", "description": "Additional arguments passed to the script as a key-value dict", "required": False, "default": "{}"},
        ],
        "source_file": "backend/tools/shell_script.py",
        "_source_filename": "shell_script.py",
    },
]


def _read_source(filename: str) -> str:
    p = _TOOLS_DIR / filename
    return p.read_text(encoding="utf-8") if p.exists() else ""


def seed_tools() -> int:
    """Seed initial tool definitions into MongoDB. Idempotent: skips tools already in DB.

    Returns count of newly seeded tools.
    """
    col = tools_col_sync()
    hist_col = tools_history_col_sync()
    seeded = 0
    now = datetime.now(UTC)

    for defn in _INITIAL_TOOL_DEFS:
        tool_name = defn["tool"]
        if col.find_one({"tool": tool_name}):
            continue

        source = _read_source(defn["_source_filename"])
        doc = {k: v for k, v in defn.items() if not k.startswith("_")}
        doc["source_code"] = source
        doc["change_type"] = "initial_seed"
        doc["changed_by"] = "system"
        doc["version_created_at"] = now
        doc["created_at"] = now

        col.insert_one(doc)

        snapshot = {k: v for k, v in doc.items() if k != "_id"}
        hist_col.insert_one(
            {
                "tool": tool_name,
                "tool_version": defn["tool_version"],
                "archived_at": now,
                "change_type": "initial_seed",
                "changed_by": "system",
                "snapshot": snapshot,
            }
        )
        seeded += 1
        logger.info("Seeded tool: %s v%s", tool_name, defn["tool_version"])

    return seeded
