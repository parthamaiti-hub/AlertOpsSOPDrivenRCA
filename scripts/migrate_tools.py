"""Migrate existing tool definitions into MongoDB.

Run once (idempotent) to populate the tools collection from the source files
already present on disk. Any tool whose name already exists in the DB is skipped.

Usage:
    uv run python scripts/migrate_tools.py
"""
import pathlib
import sys

# Allow running from the project root
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from datetime import UTC, datetime

from backend.config.settings import settings
from backend.models.database import tools_col_sync, tools_history_col_sync

_TOOLS_DIR = pathlib.Path(__file__).parent.parent / "backend" / "tools"

_TOOL_DEFS = [
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
        "_filename": "splunk_query.py",
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
        "_filename": "prometheus_query.py",
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
        "_filename": "health_check.py",
    },
]


def migrate():
    col = tools_col_sync()
    hist_col = tools_history_col_sync()
    now = datetime.now(UTC)
    migrated = 0
    skipped = 0

    for defn in _TOOL_DEFS:
        tool_name = defn["tool"]
        if col.find_one({"tool": tool_name}):
            print(f"  SKIP  {tool_name} (already in DB)")
            skipped += 1
            continue

        src_path = _TOOLS_DIR / defn["_filename"]
        source_code = src_path.read_text(encoding="utf-8") if src_path.exists() else ""

        doc = {k: v for k, v in defn.items() if not k.startswith("_")}
        doc["source_code"] = source_code
        doc["change_type"] = "migration"
        doc["changed_by"] = "migrate_script"
        doc["version_created_at"] = now
        doc["created_at"] = now

        col.insert_one(doc)

        snapshot = {k: v for k, v in doc.items() if k != "_id"}
        hist_col.insert_one(
            {
                "tool": tool_name,
                "tool_version": defn["tool_version"],
                "archived_at": now,
                "change_type": "migration",
                "changed_by": "migrate_script",
                "snapshot": snapshot,
            }
        )
        migrated += 1
        print(f"  OK    {tool_name} v{defn['tool_version']}")

    print(f"\nMigration complete: {migrated} migrated, {skipped} skipped.")


if __name__ == "__main__":
    print(f"Connecting to {settings.mongodb_uri} / {settings.mongodb_db} ...")
    migrate()
