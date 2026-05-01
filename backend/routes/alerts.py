import json
import logging
from datetime import UTC, datetime

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Query, Request

from backend.eventprocessing.rabbitmq import publish
from backend.models.database import alerts_col, classifier_match_logs_col
from backend.models.schemas import Alert, TextAlert

router = APIRouter(prefix="/api/alerts", tags=["alerts"])
logger = logging.getLogger(__name__)


@router.post("", status_code=201)
async def create_alert(alert: Alert, request: Request):
    doc = alert.model_dump()
    now = datetime.now(UTC)
    doc["created_at"] = now
    doc["logged_at"] = now
    doc["source_type"] = doc.get("source_type") or "api"
    doc["source_ref"] = doc.get("source_ref") or str(request.url)
    result = await alerts_col().insert_one(doc)
    alert_id = str(result.inserted_id)
    msg = {k: v for k, v in doc.items() if k != "_id"}
    msg["alert_id"] = alert_id
    msg["created_at"] = doc["created_at"].isoformat()
    publish("alert_ingest", msg)
    return {"alert_id": alert_id}


@router.post("/text", status_code=201)
async def create_text_alert(text_alert: TextAlert, request: Request):
    alert = Alert(
        alert_type="text",
        alert_text=text_alert.alert_text,
        raw_payload=text_alert.raw_payload,
    )
    doc = alert.model_dump()
    now = datetime.now(UTC)
    doc["created_at"] = now
    doc["logged_at"] = now
    filename = ""
    if isinstance(doc.get("raw_payload"), dict):
        filename = str(doc["raw_payload"].get("filename") or "").strip()
    if filename:
        doc["source_type"] = "file"
        doc["source_ref"] = filename
    else:
        doc["source_type"] = "api"
        doc["source_ref"] = str(request.url)
    result = await alerts_col().insert_one(doc)
    alert_id = str(result.inserted_id)
    msg = {k: v for k, v in doc.items() if k != "_id"}
    msg["alert_id"] = alert_id
    msg["created_at"] = doc["created_at"].isoformat()
    publish("alert_ingest", msg)
    return {"alert_id": alert_id}


@router.get("")
async def list_alerts(
    skip: int = 0,
    limit: int = 50,
    application: str | None = None,
    domain: str | None = None,
    category: str | None = None,
    severity: str | None = None,
    sop_id: str | None = None,
    processing_status: str | None = None,
    feedback_received: bool | None = None,
    root_cause: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    alert_id: str | None = None,
):
    query: dict = {}
    if alert_id:
        try:
            query["_id"] = ObjectId(alert_id)
        except Exception:
            return []
    if application:
        query["source_application"] = {"$regex": application, "$options": "i"}
    if domain:
        query["domain"] = {"$regex": domain, "$options": "i"}
    if category:
        query["category"] = {"$regex": category, "$options": "i"}
    if severity:
        query["severity"] = severity
    if sop_id:
        query["$or"] = [
            {"sop_id": {"$regex": sop_id, "$options": "i"}},
            {"sop_document_id": {"$regex": sop_id, "$options": "i"}},
            {"alert_sop_identifier_keys": {"$regex": sop_id, "$options": "i"}},
        ]
    if processing_status:
        query["processing_status"] = processing_status
    if feedback_received is not None:
        query["feedback_received"] = feedback_received
    if date_from or date_to:
        date_filter: dict = {}
        if date_from:
            date_filter["$gte"] = datetime.fromisoformat(date_from)
        if date_to:
            date_filter["$lte"] = datetime.fromisoformat(date_to + "T23:59:59")
        query["created_at"] = date_filter

    cursor = alerts_col().find(query).sort("created_at", -1).skip(skip).limit(limit)
    alerts = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        alerts.append(doc)

    # If root_cause filter, do a secondary lookup in rca_results
    if root_cause and alerts:
        from backend.models.database import rca_results_col
        alert_ids = [a["_id"] for a in alerts]
        rca_cursor = rca_results_col().find({
            "alert_id": {"$in": alert_ids},
            "root_cause": {"$regex": root_cause, "$options": "i"},
        })
        matching_ids = set()
        async for rca_doc in rca_cursor:
            matching_ids.add(rca_doc["alert_id"])
        alerts = [a for a in alerts if a["_id"] in matching_ids]

    total = await alerts_col().count_documents(query)
    return {"alerts": alerts, "total": total}


@router.get("/stats")
async def get_alert_stats(
    application: str | None = None,
    domain: str | None = None,
    category: str | None = None,
    severity: str | None = None,
    sop_id: str | None = None,
    processing_status: str | None = None,
    feedback_received: bool | None = None,
    root_cause: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    alert_id: str | None = None,
):
    query: dict = {}
    if alert_id:
        try:
            query["_id"] = ObjectId(alert_id)
        except Exception:
            pass
    if application:
        query["source_application"] = {"$regex": application, "$options": "i"}
    if domain:
        query["domain"] = {"$regex": domain, "$options": "i"}
    if category:
        query["category"] = {"$regex": category, "$options": "i"}
    if severity:
        query["severity"] = severity
    if sop_id:
        query["$or"] = [
            {"sop_id": {"$regex": sop_id, "$options": "i"}},
            {"sop_document_id": {"$regex": sop_id, "$options": "i"}},
            {"alert_sop_identifier_keys": {"$regex": sop_id, "$options": "i"}},
        ]
    if processing_status:
        query["processing_status"] = processing_status
    if feedback_received is not None:
        query["feedback_received"] = feedback_received
    if date_from or date_to:
        date_filter: dict = {}
        if date_from:
            date_filter["$gte"] = datetime.fromisoformat(date_from)
        if date_to:
            date_filter["$lte"] = datetime.fromisoformat(date_to + "T23:59:59")
        query["created_at"] = date_filter

    failed_statuses = ["SOPNotFound", "RCANotFound", "RCANotValidated", "sop_workflow_processfailed"]

    pipeline = [
        {"$match": query},
        {"$facet": {
            "by_status": [{"$group": {"_id": "$processing_status", "count": {"$sum": 1}}}],
            "mean_time": [
                {"$match": {"processed_at": {"$exists": True}, "created_at": {"$exists": True}}},
                {"$project": {"diff_ms": {"$subtract": ["$processed_at", "$created_at"]}}},
                {"$group": {"_id": None, "avg_ms": {"$avg": "$diff_ms"}}},
            ],
        }},
    ]

    result = await alerts_col().aggregate(pipeline).to_list(length=None)
    facet = result[0] if result else {"by_status": [], "mean_time": []}

    counts: dict[str, int] = {}
    for bucket in facet.get("by_status", []):
        counts[bucket["_id"]] = bucket["count"]

    total = sum(counts.values())
    success = counts.get("processedSuccessfully", 0)
    failed = sum(counts.get(s, 0) for s in failed_statuses)
    incomplete = total - success - failed

    mean_time_raw = facet.get("mean_time", [])
    mean_seconds: float | None = None
    if mean_time_raw and mean_time_raw[0].get("avg_ms") is not None:
        mean_seconds = round(mean_time_raw[0]["avg_ms"] / 1000, 1)

    return {
        "total": total,
        "success": success,
        "failed": failed,
        "incomplete": max(incomplete, 0),
        "mean_processing_time_seconds": mean_seconds,
    }


@router.get("/{alert_id}")
async def get_alert(alert_id: str):
    doc = await alerts_col().find_one({"_id": ObjectId(alert_id)})
    if not doc:
        raise HTTPException(404, "Alert not found")
    doc["_id"] = str(doc["_id"])
    return doc


@router.get("/{alert_id}/classifier-match")
async def get_classifier_match(alert_id: str):
    doc = await classifier_match_logs_col().find_one(
        {"alert_id": alert_id},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    if not doc:
        return {}
    if "created_at" in doc:
        doc["created_at"] = doc["created_at"].isoformat()
    return doc


@router.get("/{alert_id}/retries")
async def get_alert_retries(alert_id: str):
    from backend.models.database import alert_retry_attempts_col, retry_stage_events_col

    attempts = []
    async for doc in alert_retry_attempts_col().find(
        {"alert_id": alert_id}, sort=[("requested_at", -1)]
    ):
        doc["_id"] = str(doc["_id"])
        if doc.get("requested_at"):
            doc["requested_at"] = doc["requested_at"].isoformat()
        if doc.get("completed_at"):
            doc["completed_at"] = doc["completed_at"].isoformat()

        # Attach stage events for this attempt
        batch_id = doc.get("batch_id")
        stage_events = []
        if batch_id:
            async for ev in retry_stage_events_col().find({"batch_id": batch_id, "alert_id": alert_id}):
                ev["_id"] = str(ev["_id"])
                if ev.get("started_at"):
                    ev["started_at"] = ev["started_at"].isoformat()
                if ev.get("completed_at"):
                    ev["completed_at"] = ev["completed_at"].isoformat()
                stage_events.append(ev)
        doc["stage_events"] = stage_events
        attempts.append(doc)

    return {"alert_id": alert_id, "retries": attempts}
