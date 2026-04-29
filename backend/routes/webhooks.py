import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Request

from backend.eventprocessing.rabbitmq import publish
from backend.models.database import alerts_col
from backend.models.schemas import Alert, TextAlert

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)


@router.post("/alerts", status_code=201)
async def webhook_alert(alert: Alert, request: Request):
    doc = alert.model_dump()
    now = datetime.now(UTC)
    doc["created_at"] = now
    doc["logged_at"] = now
    doc["source_type"] = doc.get("source_type") or "webhook"
    doc["source_ref"] = doc.get("source_ref") or str(request.url)
    result = await alerts_col().insert_one(doc)
    alert_id = str(result.inserted_id)
    msg = {k: v for k, v in doc.items() if k != "_id"}
    msg["alert_id"] = alert_id
    msg["created_at"] = doc["created_at"].isoformat()
    publish("alert_ingest", msg)
    return {"alert_id": alert_id}


@router.post("/alerts/text", status_code=201)
async def webhook_text_alert(text_alert: TextAlert, request: Request):
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
        doc["source_type"] = "webhook"
        doc["source_ref"] = str(request.url)
    result = await alerts_col().insert_one(doc)
    alert_id = str(result.inserted_id)
    msg = {k: v for k, v in doc.items() if k != "_id"}
    msg["alert_id"] = alert_id
    msg["created_at"] = doc["created_at"].isoformat()
    publish("alert_ingest", msg)
    return {"alert_id": alert_id}
