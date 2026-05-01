import logging

from bson import ObjectId
from fastapi import APIRouter, HTTPException

from backend.models.database import pending_actions_col
from backend.tools.registry import execute_tool

router = APIRouter(prefix="/api/alerts", tags=["pending_actions"])
logger = logging.getLogger(__name__)


@router.get("/{alert_id}/pending-actions")
async def list_pending_actions(alert_id: str):
    docs = []
    async for doc in pending_actions_col().find(
        {"alert_id": alert_id},
        sort=[("step_id", 1)],
    ):
        doc["_id"] = str(doc["_id"])
        docs.append(doc)
    return docs


@router.post("/{alert_id}/pending-actions/{step_id}/approve")
async def approve_pending_action(alert_id: str, step_id: int):
    doc = await pending_actions_col().find_one({"alert_id": alert_id, "step_id": step_id})
    if not doc:
        raise HTTPException(404, "Pending action not found")
    if doc.get("status") == "executed":
        raise HTTPException(400, "Action already executed")

    tool_name = doc.get("tool", "")
    tool_params = doc.get("tool_params", {})
    try:
        result = execute_tool(tool_name, tool_params)
    except Exception as exc:
        logger.exception("Approved tool %s failed for alert %s step %s", tool_name, alert_id, step_id)
        raise HTTPException(500, f"Tool execution failed: {exc}") from exc

    await pending_actions_col().update_one(
        {"_id": doc["_id"]},
        {"$set": {"status": "executed", "result": result}},
    )
    return {"step_id": step_id, "status": "executed", "result": result}
