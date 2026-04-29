import logging

from fastapi import APIRouter, HTTPException

from backend.eventprocessing.retry_service import request_retry
from backend.models.database import (
    alert_retry_attempts_col,
    classifier_match_logs_col,
    rca_results_col,
    retry_stage_events_col,
    validation_results_col,
)
from backend.models.schemas import RetryAttemptResponse, RetryRequest

router = APIRouter(prefix="/api/retries", tags=["retries"])
logger = logging.getLogger(__name__)


@router.post("", response_model=list[RetryAttemptResponse], status_code=202)
async def submit_retry(body: RetryRequest):
    results = request_retry(body.alert_ids, body.retry_level, body.reason)
    return results


@router.get("/{batch_id}")
async def get_retry_batch(batch_id: str):
    attempts = []
    async for doc in alert_retry_attempts_col().find({"batch_id": batch_id}):
        doc["_id"] = str(doc["_id"])
        if doc.get("requested_at"):
            doc["requested_at"] = doc["requested_at"].isoformat()
        if doc.get("completed_at"):
            doc["completed_at"] = doc["completed_at"].isoformat()
        attempts.append(doc)

    if not attempts:
        raise HTTPException(404, "Retry batch not found")

    events = []
    async for doc in retry_stage_events_col().find({"batch_id": batch_id}):
        doc["_id"] = str(doc["_id"])
        if doc.get("started_at"):
            doc["started_at"] = doc["started_at"].isoformat()
        if doc.get("completed_at"):
            doc["completed_at"] = doc["completed_at"].isoformat()
        events.append(doc)

    states = [a["state"] for a in attempts]
    if all(s == "completed" for s in states):
        overall = "completed"
    elif any(s == "failed" for s in states) and all(s in ("completed", "failed") for s in states):
        overall = "partially_completed"
    elif any(s == "failed" for s in states):
        overall = "failed"
    else:
        overall = "in_progress"

    return {"batch_id": batch_id, "overall_status": overall, "attempts": attempts, "stage_events": events}


@router.get("/{batch_id}/run-output")
async def get_retry_run_output(batch_id: str, alert_id: str):
    """Return RCA, validation, and classifier match for a specific retry batch run."""
    rca = None
    async for doc in rca_results_col().find({"alert_id": alert_id, "retry_batch_id": batch_id}, limit=1):
        rca = doc
    if not rca:
        raise HTTPException(404, "RCA not found for this retry batch")

    rca["_id"] = str(rca["_id"])
    if rca.get("created_at"):
        rca["created_at"] = rca["created_at"].isoformat()

    validation = None
    async for v in validation_results_col().find(
        {"alert_id": alert_id, "retry_batch_id": batch_id}, limit=1
    ):
        validation = v
    if validation:
        rca["validation_assessment"] = validation.get("assessment", "")
        rca["confidence_score"] = validation.get("confidence_score")

    classifier = None
    async for c in classifier_match_logs_col().find(
        {"alert_id": alert_id, "retry_batch_id": batch_id}, limit=1
    ):
        classifier = c
    if classifier:
        classifier["_id"] = str(classifier["_id"])
        rca["classifier_match"] = classifier

    return rca
