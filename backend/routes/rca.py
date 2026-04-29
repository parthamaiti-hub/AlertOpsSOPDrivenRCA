import logging

from bson import ObjectId
from fastapi import APIRouter, HTTPException
from pymongo import DESCENDING

from backend.models.database import rca_results_col, validation_results_col

router = APIRouter(prefix="/api/rca", tags=["rca"])
logger = logging.getLogger(__name__)


@router.get("/{alert_id}")
async def get_rca(alert_id: str):
    # Prefer the active-latest RCA; fall back to newest by created_at for primary-run docs
    doc = None
    async for candidate in rca_results_col().find(
        {"alert_id": alert_id},
        sort=[("is_active_latest", DESCENDING), ("created_at", DESCENDING)],
        limit=1,
    ):
        doc = candidate
    if not doc:
        raise HTTPException(404, "RCA not found")
    doc["_id"] = str(doc["_id"])
    # Prefer active-latest validation
    validation = None
    async for v in validation_results_col().find(
        {"alert_id": alert_id},
        sort=[("is_active_latest", DESCENDING), ("created_at", DESCENDING)],
        limit=1,
    ):
        validation = v
    if validation:
        doc["validation_assessment"] = validation.get("assessment", "")
        doc["confidence_score"] = validation.get("confidence_score")
    return doc
