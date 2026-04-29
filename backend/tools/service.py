import logging
from datetime import UTC, datetime

from backend.sopmanagement.version_utils import (
    get_next_valid_versions,
    is_valid_progression,
    validate_version_format,
)
from backend.tools.db import archive_tool, get_active_tool, list_active_tools, save_tool

logger = logging.getLogger(__name__)

VALID_TECHS = {"python_script", "shell_script", "mcp_client"}


def list_tools() -> list[dict]:
    """Return all active tools (one per tool name, highest version)."""
    return [_clean(t) for t in list_active_tools()]


def get_tool(tool_name: str) -> dict | None:
    doc = get_active_tool(tool_name)
    return _clean(doc) if doc else None


def get_tool_history(tool_name: str) -> list[dict]:
    from backend.models.database import tools_history_col_sync

    docs = list(tools_history_col_sync().find({"tool": tool_name}, sort=[("archived_at", -1)]))
    return [_clean_hist(d) for d in docs]


def get_allowed_versions(tool_name: str) -> dict:
    doc = get_active_tool(tool_name)
    if not doc:
        return {"current_version": None, "allowed_versions": []}
    current = doc["tool_version"]
    minor_bump, major_bump = get_next_valid_versions(current)
    return {"current_version": current, "allowed_versions": [minor_bump, major_bump]}


def create_tool(data: dict) -> tuple[dict, str | None]:
    """Create a new tool definition. Returns (tool_doc, error_message)."""
    tool_name = data.get("tool", "").strip()
    version = data.get("tool_version", "1.0")
    tech = data.get("tool_tech", "python_script")

    if not tool_name:
        return {}, "tool name is required"
    if not validate_version_format(version):
        return {}, f"invalid version format: {version}"
    if tech not in VALID_TECHS:
        return {}, f"invalid tool_tech: {tech}. Must be one of {sorted(VALID_TECHS)}"
    if get_active_tool(tool_name):
        return {}, f"tool '{tool_name}' already exists. Use PUT to add a new version."

    now = datetime.now(UTC)
    doc = {
        "tool": tool_name,
        "tool_version": version,
        "tool_tech": tech,
        "description": data.get("description", ""),
        "tool_params": data.get("tool_params", []),
        "source_code": data.get("source_code", ""),
        "source_file": data.get("source_file", ""),
        "change_type": "created",
        "changed_by": data.get("changed_by", "user"),
        "version_created_at": now,
        "created_at": now,
    }
    saved = save_tool(doc)
    archive_tool(saved, change_type="created", changed_by=doc["changed_by"])
    return _clean(saved), None


def update_tool(tool_name: str, data: dict) -> tuple[dict, str | None]:
    """Create a new version of an existing tool. Returns (tool_doc, error_message)."""
    current_doc = get_active_tool(tool_name)
    if not current_doc:
        return {}, f"tool '{tool_name}' not found"

    new_version = data.get("tool_version", "")
    if not validate_version_format(new_version):
        return {}, f"invalid version format: {new_version}"
    if not is_valid_progression(current_doc["tool_version"], new_version):
        minor_bump, major_bump = get_next_valid_versions(current_doc["tool_version"])
        return {}, f"version must be {minor_bump} or {major_bump}"

    tech = data.get("tool_tech", current_doc["tool_tech"])
    if tech not in VALID_TECHS:
        return {}, f"invalid tool_tech: {tech}"

    changed_by = data.get("changed_by", "user")
    archive_tool(current_doc, change_type="new_version", changed_by=changed_by)

    now = datetime.now(UTC)
    doc = {
        "tool": tool_name,
        "tool_version": new_version,
        "tool_tech": tech,
        "description": data.get("description", current_doc.get("description", "")),
        "tool_params": data.get("tool_params", current_doc.get("tool_params", [])),
        "source_code": data.get("source_code", current_doc.get("source_code", "")),
        "source_file": data.get("source_file", current_doc.get("source_file", "")),
        "change_type": "new_version",
        "changed_by": changed_by,
        "version_created_at": now,
        "created_at": current_doc.get("created_at", now),
    }
    saved = save_tool(doc)
    return _clean(saved), None


def _clean(doc: dict | None) -> dict:
    if not doc:
        return {}
    d = dict(doc)
    d.pop("_id", None)
    return d


def _clean_hist(doc: dict) -> dict:
    d = dict(doc)
    d.pop("_id", None)
    if isinstance(d.get("snapshot"), dict):
        d["snapshot"].pop("_id", None)
    return d
