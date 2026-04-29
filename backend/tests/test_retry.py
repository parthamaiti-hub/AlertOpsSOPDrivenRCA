"""Tests for retry service, routes, and state transitions."""
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, call, patch

import pytest
from bson import ObjectId
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.models.schemas import RetryAttemptResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_alert(overrides: dict | None = None) -> dict:
    base = {
        "_id": ObjectId(),
        "source_application": "test-app",
        "domain": "infra",
        "category": "performance",
        "severity": "critical",
        "processing_status": "completed",
        "status": "completed",
        "sop_id": "sop-001",
        "sop_document_id": "sop-001",
        "sop_workflow_id": str(ObjectId()),
        "latest_effective_rca_id": str(ObjectId()),
        "retry_in_progress": False,
        "retry_attempt_count": 0,
    }
    if overrides:
        base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Prerequisite validation tests
# ---------------------------------------------------------------------------

class TestPrerequisiteValidation:
    """request_retry rejects alerts when prerequisites are not met."""

    def _run(self, alert: dict, retry_level: str):
        from backend.eventprocessing.retry_service import request_retry
        alert_id = str(alert["_id"])
        with (
            patch("backend.eventprocessing.retry_service.alerts_col_sync") as mock_alerts,
            patch("backend.eventprocessing.retry_service.rca_results_col_sync") as mock_rca,
            patch("backend.eventprocessing.retry_service.alert_retry_attempts_col_sync"),
            patch("backend.eventprocessing.retry_service.retry_stage_events_col_sync"),
            patch("backend.eventprocessing.retry_service.validation_results_col_sync"),
            patch("backend.eventprocessing.retry_service.classifier_match_logs_col_sync"),
            patch("backend.eventprocessing.retry_service.publish"),
        ):
            mock_alerts.return_value.find_one.return_value = alert
            mock_alerts.return_value.update_one.return_value = MagicMock()
            mock_rca.return_value.find_one.return_value = None
            mock_rca.return_value.update_many.return_value = MagicMock()
            results = request_retry([alert_id], retry_level)
        return results

    def test_level1_accepts_existing_alert(self):
        alert = _make_alert()
        results = self._run(alert, "level1")
        assert results[0].accepted is True

    def test_level2_accepts_no_extra_prereq(self):
        alert = _make_alert({"sop_workflow_id": None})
        results = self._run(alert, "level2")
        assert results[0].accepted is True

    def test_level3_rejects_missing_sop_workflow_id(self):
        alert = _make_alert({"sop_workflow_id": None})
        results = self._run(alert, "level3")
        assert results[0].accepted is False
        assert "level2" in results[0].reason or "level1" in results[0].reason

    def test_level3_accepts_when_workflow_exists(self):
        alert = _make_alert()
        results = self._run(alert, "level3")
        assert results[0].accepted is True

    def test_level4_rejects_no_active_rca(self):
        alert = _make_alert({"latest_effective_rca_id": None})
        results = self._run(alert, "level4")
        assert results[0].accepted is False
        assert "RCA" in results[0].reason or "rca" in results[0].reason.lower()

    def test_level4_accepts_when_rca_exists(self):
        from backend.eventprocessing.retry_service import request_retry
        alert = _make_alert()
        alert_id = str(alert["_id"])
        with (
            patch("backend.eventprocessing.retry_service.alerts_col_sync") as mock_alerts,
            patch("backend.eventprocessing.retry_service.rca_results_col_sync"),
            patch("backend.eventprocessing.retry_service.alert_retry_attempts_col_sync"),
            patch("backend.eventprocessing.retry_service.retry_stage_events_col_sync"),
            patch("backend.eventprocessing.retry_service.validation_results_col_sync"),
            patch("backend.eventprocessing.retry_service.classifier_match_logs_col_sync"),
            patch("backend.eventprocessing.retry_service.publish"),
        ):
            mock_alerts.return_value.find_one.return_value = alert
            mock_alerts.return_value.update_one.return_value = MagicMock()
            results = request_retry([alert_id], "level4")
        assert results[0].accepted is True

    def test_rejects_retry_in_progress(self):
        alert = _make_alert({"retry_in_progress": True})
        results = self._run(alert, "level1")
        assert results[0].accepted is False
        assert "in progress" in results[0].reason

    def test_rejects_invalid_alert_id(self):
        from backend.eventprocessing.retry_service import request_retry
        results = request_retry(["not-a-valid-id"], "level1")
        assert results[0].accepted is False

    def test_rejects_nonexistent_alert(self):
        from backend.eventprocessing.retry_service import request_retry
        with (
            patch("backend.eventprocessing.retry_service.alerts_col_sync") as mock_alerts,
        ):
            mock_alerts.return_value.find_one.return_value = None
            results = request_retry([str(ObjectId())], "level1")
        assert results[0].accepted is False
        assert "not found" in results[0].reason


# ---------------------------------------------------------------------------
# Batch size cap tests
# ---------------------------------------------------------------------------

class TestBatchSizeCap:
    def test_excess_alerts_rejected(self):
        from backend.eventprocessing.retry_service import request_retry
        many_ids = [str(ObjectId()) for _ in range(3)]
        with (
            patch("backend.eventprocessing.retry_service.settings") as mock_settings,
            patch("backend.eventprocessing.retry_service.alerts_col_sync") as mock_alerts,
            patch("backend.eventprocessing.retry_service.alert_retry_attempts_col_sync"),
            patch("backend.eventprocessing.retry_service.retry_stage_events_col_sync"),
            patch("backend.eventprocessing.retry_service.validation_results_col_sync"),
            patch("backend.eventprocessing.retry_service.classifier_match_logs_col_sync"),
            patch("backend.eventprocessing.retry_service.rca_results_col_sync"),
            patch("backend.eventprocessing.retry_service.publish"),
        ):
            mock_settings.retry_max_batch_size = 2
            alert = _make_alert()
            mock_alerts.return_value.find_one.return_value = alert
            mock_alerts.return_value.update_one.return_value = MagicMock()
            results = request_retry(many_ids, "level1")

        assert len(results) == 3
        accepted = [r for r in results if r.accepted]
        rejected = [r for r in results if not r.accepted]
        assert len(accepted) == 2
        assert len(rejected) == 1
        assert "maximum" in rejected[0].reason


# ---------------------------------------------------------------------------
# Soft-invalidation tests
# ---------------------------------------------------------------------------

class TestSoftInvalidation:
    def _run_invalidation(self, retry_level: str):
        from backend.eventprocessing.retry_service import _soft_invalidate
        valid_id = str(ObjectId())
        with (
            patch("backend.eventprocessing.retry_service.rca_results_col_sync") as mock_rca,
            patch("backend.eventprocessing.retry_service.validation_results_col_sync") as mock_val,
            patch("backend.eventprocessing.retry_service.alerts_col_sync") as mock_alerts,
        ):
            mock_rca.return_value.update_many.return_value = MagicMock()
            mock_val.return_value.update_many.return_value = MagicMock()
            mock_alerts.return_value.update_one.return_value = MagicMock()
            _soft_invalidate(valid_id, retry_level)
            return mock_rca.return_value, mock_val.return_value, mock_alerts.return_value

    def test_level1_clears_rca_and_validation(self):
        rca_col, val_col, alerts = self._run_invalidation("level1")
        rca_col.update_many.assert_called_once()
        val_col.update_many.assert_called_once()
        alerts.update_one.assert_called_once()  # SOP fields cleared

    def test_level2_clears_rca_and_validation_keeps_classifier(self):
        rca_col, val_col, alerts = self._run_invalidation("level2")
        rca_col.update_many.assert_called_once()
        val_col.update_many.assert_called_once()
        alerts.update_one.assert_not_called()  # SOP fields preserved

    def test_level3_clears_validation_only(self):
        rca_col, val_col, alerts = self._run_invalidation("level3")
        rca_col.update_many.assert_not_called()
        val_col.update_many.assert_called_once()

    def test_level4_clears_validation_only(self):
        rca_col, val_col, alerts = self._run_invalidation("level4")
        rca_col.update_many.assert_not_called()
        val_col.update_many.assert_called_once()


# ---------------------------------------------------------------------------
# Queue routing tests
# ---------------------------------------------------------------------------

class TestQueueRouting:
    def _submit(self, retry_level: str) -> str:
        from backend.eventprocessing.retry_service import request_retry
        alert = _make_alert()
        alert_id = str(alert["_id"])
        with (
            patch("backend.eventprocessing.retry_service.alerts_col_sync") as mock_alerts,
            patch("backend.eventprocessing.retry_service.rca_results_col_sync"),
            patch("backend.eventprocessing.retry_service.alert_retry_attempts_col_sync"),
            patch("backend.eventprocessing.retry_service.retry_stage_events_col_sync"),
            patch("backend.eventprocessing.retry_service.validation_results_col_sync"),
            patch("backend.eventprocessing.retry_service.classifier_match_logs_col_sync"),
            patch("backend.eventprocessing.retry_service.publish") as mock_publish,
        ):
            mock_alerts.return_value.find_one.return_value = alert
            mock_alerts.return_value.update_one.return_value = MagicMock()
            request_retry([alert_id], retry_level)
            if mock_publish.called:
                return mock_publish.call_args[0][0]
        return ""

    def test_level1_routes_to_alert_ingest(self):
        assert self._submit("level1") == "alert_ingest"

    def test_level2_routes_to_stage1_identify(self):
        assert self._submit("level2") == "stage1_identify"

    def test_level3_routes_to_stage2_execute(self):
        assert self._submit("level3") == "stage2_execute"

    def test_level4_routes_to_stage3_validate(self):
        assert self._submit("level4") == "stage3_validate"


# ---------------------------------------------------------------------------
# Retry attempt state transition tests
# ---------------------------------------------------------------------------

class TestRetryAttemptLifecycle:
    def test_attempt_created_with_queued_state(self):
        from backend.eventprocessing.retry_service import request_retry
        alert = _make_alert()
        alert_id = str(alert["_id"])
        with (
            patch("backend.eventprocessing.retry_service.alerts_col_sync") as mock_alerts,
            patch("backend.eventprocessing.retry_service.rca_results_col_sync"),
            patch("backend.eventprocessing.retry_service.alert_retry_attempts_col_sync") as mock_attempts,
            patch("backend.eventprocessing.retry_service.retry_stage_events_col_sync") as mock_events,
            patch("backend.eventprocessing.retry_service.validation_results_col_sync"),
            patch("backend.eventprocessing.retry_service.classifier_match_logs_col_sync"),
            patch("backend.eventprocessing.retry_service.publish"),
        ):
            mock_alerts.return_value.find_one.return_value = alert
            mock_alerts.return_value.update_one.return_value = MagicMock()
            mock_attempts.return_value.insert_one.return_value = MagicMock()
            mock_events.return_value.insert_one.return_value = MagicMock()
            request_retry([alert_id], "level2")

            attempt_doc = mock_attempts.return_value.insert_one.call_args[0][0]
            assert attempt_doc["state"] == "queued"
            assert attempt_doc["alert_id"] == alert_id
            assert attempt_doc["retry_level"] == "level2"

    def test_attempt_number_increments(self):
        from backend.eventprocessing.retry_service import request_retry
        alert = _make_alert({"retry_attempt_count": 2})
        alert_id = str(alert["_id"])
        with (
            patch("backend.eventprocessing.retry_service.alerts_col_sync") as mock_alerts,
            patch("backend.eventprocessing.retry_service.rca_results_col_sync"),
            patch("backend.eventprocessing.retry_service.alert_retry_attempts_col_sync") as mock_attempts,
            patch("backend.eventprocessing.retry_service.retry_stage_events_col_sync"),
            patch("backend.eventprocessing.retry_service.validation_results_col_sync"),
            patch("backend.eventprocessing.retry_service.classifier_match_logs_col_sync"),
            patch("backend.eventprocessing.retry_service.publish"),
        ):
            mock_alerts.return_value.find_one.return_value = alert
            mock_alerts.return_value.update_one.return_value = MagicMock()
            mock_attempts.return_value.insert_one.return_value = MagicMock()
            request_retry([alert_id], "level1")

            doc = mock_attempts.return_value.insert_one.call_args[0][0]
            assert doc["attempt_number"] == 3


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_submit_accepted():
    with patch("backend.routes.retry.request_retry") as mock_service:
        mock_service.return_value = [
            RetryAttemptResponse(alert_id="abc", accepted=True, batch_id="batch-1"),
        ]
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/retries", json={
                "alert_ids": ["abc"],
                "retry_level": "level2",
            })
        assert resp.status_code == 202
        data = resp.json()
        assert data[0]["accepted"] is True
        assert data[0]["batch_id"] == "batch-1"


@pytest.mark.asyncio
async def test_retry_submit_mixed():
    with patch("backend.routes.retry.request_retry") as mock_service:
        mock_service.return_value = [
            RetryAttemptResponse(alert_id="abc", accepted=True, batch_id="b1"),
            RetryAttemptResponse(alert_id="def", accepted=False, reason="not found"),
        ]
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/retries", json={
                "alert_ids": ["abc", "def"],
                "retry_level": "level3",
            })
        assert resp.status_code == 202
        data = resp.json()
        assert len(data) == 2
        assert data[1]["accepted"] is False
        assert data[1]["reason"] == "not found"


class _AsyncIter:
    """Helper to create an async iterator from a list for mocking Motor cursors."""
    def __init__(self, items):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


@pytest.mark.asyncio
async def test_retry_batch_not_found():
    with patch("backend.routes.retry.alert_retry_attempts_col") as mock_col:
        mock_col.return_value.find.return_value = _AsyncIter([])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/retries/nonexistent-batch")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_alert_retries_empty():
    with patch("backend.models.database.alert_retry_attempts_col") as mock_attempts:
        mock_attempts.return_value.find.return_value = _AsyncIter([])
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/alerts/{str(ObjectId())}/retries")
        assert resp.status_code == 200
        data = resp.json()
        assert data["retries"] == []
