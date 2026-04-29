import logging
from datetime import UTC, datetime

from backend.eventprocessing.rabbitmq import consume, publish
from backend.models.database import alert_retry_attempts_col_sync, retry_stage_events_col_sync

logger = logging.getLogger(__name__)


def _update_retry_state(batch_id: str | None, alert_id: str, state: str, error: str | None = None):
    if not batch_id:
        return
    alert_retry_attempts_col_sync().update_one(
        {"batch_id": batch_id, "alert_id": alert_id},
        {"$set": {"state": state, **({"error_summary": error, "completed_at": datetime.now(UTC)} if error else {})}},
    )
    retry_stage_events_col_sync().update_one(
        {"batch_id": batch_id, "alert_id": alert_id, "stage": "alert_ingest"},
        {"$set": {"status": state, **({"completed_at": datetime.now(UTC)} if state != "running_stage1" else {"started_at": datetime.now(UTC)})}},
        upsert=True,
    )


def _process_alert(msg: dict):
    alert_id = msg.get("alert_id", "")
    batch_id = msg.get("retry_batch_id")
    logger.info("Event processor received alert %s", alert_id)
    _update_retry_state(batch_id, alert_id, "running_stage1")
    publish("stage1_identify", msg)


def run():
    logger.info("Starting event processor worker")
    consume("alert_ingest", _process_alert)
