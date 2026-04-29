import logging
import uuid
from datetime import UTC, datetime

from bson import ObjectId

from backend.config.settings import settings
from backend.eventprocessing.rabbitmq import publish
from backend.models.database import (
    alert_retry_attempts_col_sync,
    alerts_col_sync,
    classifier_match_logs_col_sync,
    rca_results_col_sync,
    retry_stage_events_col_sync,
    validation_results_col_sync,
)
from backend.models.schemas import RetryAttemptResponse, RetryLevel

logger = logging.getLogger(__name__)

_LEVEL_QUEUE: dict[str, str] = {
    "level1": "alert_ingest",
    "level2": "stage1_identify",
    "level3": "stage2_execute",
    "level4": "stage3_validate",
}


def _validate_prerequisite(alert: dict, retry_level: str) -> str | None:
    """Return an error reason string if the alert cannot be retried at this level, else None."""
    if retry_level == "level3":
        if not alert.get("sop_workflow_id"):
            return "no SOP workflow ID on alert; run level2 or level1 first"
    elif retry_level == "level4":
        if not alert.get("latest_effective_rca_id"):
            # Also check rca_results collection directly
            rca = rca_results_col_sync().find_one(
                {"alert_id": str(alert["_id"]), "is_active_latest": True}
            )
            if not rca:
                return "no active RCA found; run level3, level2, or level1 first"
    return None


def _soft_invalidate(alert_id: str, retry_level: str):
    """Mark prior stage outputs as inactive based on retry level. No deletes."""
    if retry_level in ("level1", "level2"):
        rca_results_col_sync().update_many(
            {"alert_id": alert_id, "is_active_latest": True},
            {"$set": {"is_active_latest": False}},
        )
        validation_results_col_sync().update_many(
            {"alert_id": alert_id, "is_active_latest": True},
            {"$set": {"is_active_latest": False}},
        )
    elif retry_level in ("level3", "level4"):
        validation_results_col_sync().update_many(
            {"alert_id": alert_id, "is_active_latest": True},
            {"$set": {"is_active_latest": False}},
        )

    if retry_level == "level1":
        alerts_col_sync().update_one(
            {"_id": ObjectId(alert_id)},
            {"$set": {"sop_document_id": None, "sop_workflow_id": None, "sop_id": None}},
        )


def _build_payload(alert: dict, alert_id: str, batch_id: str, retry_level: str) -> dict:
    """Build the queue message for the retry, adding retry metadata."""
    msg: dict = {}
    for k, v in alert.items():
        if k == "_id":
            continue
        if hasattr(v, "isoformat"):
            msg[k] = v.isoformat()
        else:
            msg[k] = v
    msg["alert_id"] = alert_id
    msg["retry_batch_id"] = batch_id
    msg["retry_level"] = retry_level
    msg["run_kind"] = "retry"
    msg["initiated_from_stage"] = _LEVEL_QUEUE[retry_level]
    return msg


def request_retry(
    alert_ids: list[str],
    retry_level: RetryLevel,
    reason: str | None = None,
) -> list[RetryAttemptResponse]:
    """Validate, soft-invalidate, and requeue each alert for a retry run.

    Returns per-alert accepted/rejected results. Never raises — errors are
    captured per-alert in the response.
    """
    max_batch = settings.retry_max_batch_size
    results: list[RetryAttemptResponse] = []

    if len(alert_ids) > max_batch:
        for aid in alert_ids[max_batch:]:
            results.append(RetryAttemptResponse(
                alert_id=aid,
                accepted=False,
                reason=f"batch size exceeds maximum of {max_batch}",
            ))
        alert_ids = alert_ids[:max_batch]

    batch_id = str(uuid.uuid4())

    for alert_id in alert_ids:
        try:
            alert = alerts_col_sync().find_one({"_id": ObjectId(alert_id)})
        except Exception:
            results.append(RetryAttemptResponse(alert_id=alert_id, accepted=False, reason="invalid alert ID"))
            continue

        if not alert:
            results.append(RetryAttemptResponse(alert_id=alert_id, accepted=False, reason="alert not found"))
            continue

        if alert.get("retry_in_progress"):
            results.append(RetryAttemptResponse(alert_id=alert_id, accepted=False, reason="retry already in progress"))
            continue

        prereq_error = _validate_prerequisite(alert, retry_level)
        if prereq_error:
            results.append(RetryAttemptResponse(alert_id=alert_id, accepted=False, reason=prereq_error))
            continue

        # Soft-invalidate prior outputs
        _soft_invalidate(alert_id, retry_level)

        # Determine attempt number
        attempt_number = (alert.get("retry_attempt_count") or 0) + 1

        # Record retry attempt
        attempt_doc = {
            "alert_id": alert_id,
            "batch_id": batch_id,
            "retry_level": retry_level,
            "attempt_number": attempt_number,
            "prior_status_snapshot": alert.get("processing_status", ""),
            "triggered_queue": _LEVEL_QUEUE[retry_level],
            "state": "queued",
            "reason": reason,
            "requested_at": datetime.now(UTC),
            "completed_at": None,
            "error_summary": None,
        }
        alert_retry_attempts_col_sync().insert_one(attempt_doc)

        # Seed initial stage event
        retry_stage_events_col_sync().insert_one({
            "batch_id": batch_id,
            "alert_id": alert_id,
            "stage": _LEVEL_QUEUE[retry_level],
            "status": "queued",
            "started_at": datetime.now(UTC),
            "completed_at": None,
            "detail": None,
        })

        # Update alert retry metadata
        alerts_col_sync().update_one(
            {"_id": ObjectId(alert_id)},
            {"$set": {
                "retry_in_progress": True,
                "latest_retry_batch_id": batch_id,
                "latest_retry_level": retry_level,
                "retry_requested_at": datetime.now(UTC),
                "retry_attempt_count": attempt_number,
            }},
        )

        # Publish to queue
        payload = _build_payload(alert, alert_id, batch_id, retry_level)
        publish(_LEVEL_QUEUE[retry_level], payload)
        logger.info("Retry queued: alert=%s level=%s batch=%s", alert_id, retry_level, batch_id)

        results.append(RetryAttemptResponse(alert_id=alert_id, accepted=True, batch_id=batch_id))

    return results
