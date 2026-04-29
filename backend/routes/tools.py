import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.tools.service import (
    create_tool,
    get_allowed_versions,
    get_tool,
    get_tool_history,
    list_tools,
    update_tool,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tools", tags=["tools"])


class ToolCreateRequest(BaseModel):
    tool: str
    tool_version: str = "1.0"
    tool_tech: str = "python_script"
    description: str = ""
    tool_params: list[dict] = []
    source_code: str = ""
    source_file: str = ""
    changed_by: str = "user"


class ToolUpdateRequest(BaseModel):
    tool_version: str
    tool_tech: str | None = None
    description: str | None = None
    tool_params: list[dict] | None = None
    source_code: str | None = None
    source_file: str | None = None
    changed_by: str = "user"


@router.get("")
def api_list_tools() -> list[dict[str, Any]]:
    """List all active tools (source_code excluded)."""
    tools = list_tools()
    for t in tools:
        t.pop("source_code", None)
    return tools


@router.get("/{tool_name}/source")
def api_get_tool_source(tool_name: str) -> dict[str, Any]:
    """Get the source code of the active tool."""
    doc = get_tool(tool_name)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
    return {"tool": doc["tool"], "tool_version": doc["tool_version"], "source_code": doc.get("source_code", "")}


@router.get("/{tool_name}/history")
def api_get_tool_history(tool_name: str) -> list[dict[str, Any]]:
    """Get version history for a tool."""
    return get_tool_history(tool_name)


@router.get("/{tool_name}/allowed-versions")
def api_get_allowed_versions(tool_name: str) -> dict[str, Any]:
    """Get allowed next versions for a tool."""
    return get_allowed_versions(tool_name)


@router.get("/{tool_name}")
def api_get_tool(tool_name: str) -> dict[str, Any]:
    """Get active tool metadata (source_code excluded)."""
    doc = get_tool(tool_name)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found")
    result = dict(doc)
    result.pop("source_code", None)
    return result


@router.post("", status_code=201)
def api_create_tool(req: ToolCreateRequest) -> dict[str, Any]:
    """Create a new tool definition."""
    doc, err = create_tool(req.model_dump())
    if err:
        raise HTTPException(status_code=400, detail=err)
    result = dict(doc)
    result.pop("source_code", None)
    return result


@router.put("/{tool_name}")
def api_update_tool(tool_name: str, req: ToolUpdateRequest) -> dict[str, Any]:
    """Update a tool (creates a new version)."""
    data = {k: v for k, v in req.model_dump().items() if v is not None}
    doc, err = update_tool(tool_name, data)
    if err:
        raise HTTPException(status_code=400, detail=err)
    result = dict(doc)
    result.pop("source_code", None)
    return result
