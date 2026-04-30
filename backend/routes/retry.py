import logging
from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, HTTPException

from backend.eventprocessing.retry_service import request_retry
from backend.models.database import (
    alert_retry_attempts_col,
    alerts_col,
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


@router.get("/stats")
async def get_retry_stats(
    application: str | None = None,
    domain: str | None = None,
    category: str | None = None,
    severity: str | None = None,
    alert_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
):
    # Build alert-level filter to resolve matching alert_ids
    alert_query: dict = {}
    if alert_id:
        try:
            alert_query["_id"] = ObjectId(alert_id)
        except Exception:
            pass
    if application:
        alert_query["source_application"] = {"$regex": application, "$options": "i"}
    if domain:
        alert_query["domain"] = {"$regex": domain, "$options": "i"}
    if category:
        alert_query["category"] = {"$regex": category, "$options": "i"}
    if severity:
        alert_query["severity"] = severity

    attempt_match: dict = {}
    if alert_query:
        matching_ids: list[str] = []
        async for doc in alerts_col().find(alert_query, {"_id": 1}):
            matching_ids.append(str(doc["_id"]))
        attempt_match["alert_id"] = {"$in": matching_ids}

    if date_from or date_to:
        date_filter: dict = {}
        if date_from:
            date_filter["$gte"] = datetime.fromisoformat(date_from)
        if date_to:
            date_filter["$lte"] = datetime.fromisoformat(date_to + "T23:59:59")
        attempt_match["requested_at"] = date_filter

    pipeline = [
        {"$match": attempt_match},
        {"$facet": {
            "by_state": [{"$group": {"_id": "$state", "count": {"$sum": 1}}}],
            "mean_time": [
                {"$match": {"completed_at": {"$ne": None}, "requested_at": {"$exists": True}}},
                {"$project": {"diff_ms": {"$subtract": ["$completed_at", "$requested_at"]}}},
                {"$group": {"_id": None, "avg_ms": {"$avg": "$diff_ms"}}},
            ],
            "distinct_alerts": [
                {"$group": {"_id": "$alert_id"}},
                {"$count": "count"},
            ],
        }},
    ]

    result = await alert_retry_attempts_col().aggregate(pipeline).to_list(length=None)
    facet = result[0] if result else {"by_state": [], "mean_time": [], "distinct_alerts": []}

    counts: dict[str, int] = {}
    for bucket in facet.get("by_state", []):
        counts[bucket["_id"]] = bucket["count"]

    total = sum(counts.values())
    success = counts.get("completed", 0)
    failed = counts.get("failed", 0)
    incomplete = total - success - failed

    mean_time_raw = facet.get("mean_time", [])
    mean_seconds: float | None = None
    if mean_time_raw and mean_time_raw[0].get("avg_ms") is not None:
        mean_seconds = round(mean_time_raw[0]["avg_ms"] / 1000, 1)

    distinct = facet.get("distinct_alerts", [])
    total_alerts = distinct[0]["count"] if distinct else 0

    return {
        "total": total,
        "success": success,
        "failed": failed,
        "incomplete": max(incomplete, 0),
        "mean_processing_time_seconds": mean_seconds,
        "total_alerts": total_alerts,
    }


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
