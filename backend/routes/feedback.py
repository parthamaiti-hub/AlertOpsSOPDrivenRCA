import logging
from datetime import UTC, datetime

from bson import ObjectId
from fastapi import APIRouter, HTTPException

from backend.models.database import alerts_col, feedback_col
from backend.models.schemas import Feedback
from backend.validateRCA.rag import index_feedback

router = APIRouter(prefix="/api/feedback", tags=["feedback"])
logger = logging.getLogger(__name__)


@router.post("", status_code=201)
async def submit_feedback(fb: Feedback):
    doc = fb.model_dump()
    doc["created_at"] = datetime.now(UTC)
    await feedback_col().insert_one(doc)
    index_feedback(fb.alert_id, fb.comment, fb.confidence_score)
    # Mark alert as feedback received
    try:
        await alerts_col().update_one(
            {"_id": ObjectId(fb.alert_id)},
            {"$set": {"feedback_received": True}},
        )
    except Exception:
        pass
    return {"status": "ok"}


@router.get("/{alert_id}")
async def get_feedback(alert_id: str):
    cursor = feedback_col().find({"alert_id": alert_id}).sort("created_at", -1)
    items = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        items.append(doc)
    if not items:
        raise HTTPException(404, "No feedback found")
    return items
