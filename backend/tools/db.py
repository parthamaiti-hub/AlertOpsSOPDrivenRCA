import logging
from datetime import UTC, datetime
from typing import Optional

from backend.models.database import tools_col_sync, tools_history_col_sync
from backend.sopmanagement.version_utils import version_tuple

logger = logging.getLogger(__name__)


def list_active_tools() -> list[dict]:
    """Return one active tool doc per tool name (highest version)."""
    col = tools_col_sync()
    tools_by_name: dict[str, dict] = {}
    for doc in col.find({}):
        name = doc["tool"]
        if name not in tools_by_name:
            tools_by_name[name] = doc
        elif version_tuple(doc["tool_version"]) > version_tuple(tools_by_name[name]["tool_version"]):
            tools_by_name[name] = doc
    return list(tools_by_name.values())


def get_active_tool(tool_name: str) -> Optional[dict]:
    """Return the active (highest version) doc for a named tool."""
    col = tools_col_sync()
    docs = list(col.find({"tool": tool_name}))
    if not docs:
        return None
    return max(docs, key=lambda d: version_tuple(d["tool_version"]))


def archive_tool(tool_doc: dict, change_type: str = "new_version", changed_by: str = "system") -> None:
    """Append a snapshot of tool_doc to the history collection."""
    hist_col = tools_history_col_sync()
    snapshot = {k: v for k, v in tool_doc.items() if k != "_id"}
    hist_col.insert_one(
        {
            "tool": tool_doc["tool"],
            "tool_version": tool_doc["tool_version"],
            "archived_at": datetime.now(UTC),
            "change_type": change_type,
            "changed_by": changed_by,
            "snapshot": snapshot,
        }
    )


def save_tool(doc: dict) -> dict:
    """Insert a tool doc into the tools collection and return it with _id stringified."""
    col = tools_col_sync()
    result = col.insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    return doc
