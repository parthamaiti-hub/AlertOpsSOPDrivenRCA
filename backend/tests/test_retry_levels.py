"""Integration tests for all four retry levels using the JSON test data files.

Each test:
1. Loads the corresponding data file from data/retry_test_alerts/
2. Seeds mock MongoDB with the alert + supporting documents in the right state
3. Calls request_retry() with the correct level
4. Confirms: accepted=True, correct queue used, attempt record created,
   soft-invalidation applied as expected.

Data files:
  data/retry_test_alerts/level1_high_cpu_alert.json
  data/retry_test_alerts/level2_memory_leak_alert.json
  data/retry_test_alerts/level3_db_connection_pool_alert.json
  data/retry_test_alerts/level4_disk_space_alert.json
"""

import json
import pathlib
from datetime import UTC, datetime
from unittest.mock import MagicMock, call, patch

import pytest
from bson import ObjectId

DATA_DIR = pathlib.Path(__file__).parent.parent.parent / "data" / "retry_test_alerts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_data_file(filename: str) -> dict:
    path = DATA_DIR / filename
    assert path.exists(), f"Test data file not found: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _build_db_alert(data_file: dict, alert_oid: ObjectId) -> dict:
    """Merge the data file alert dict with a real ObjectId for DB simulation."""
    doc = dict(data_file["alert"])
    doc["_id"] = alert_oid
    doc.setdefault("created_at", datetime.now(UTC))
    return doc


def _run_retry(alert_doc: dict, retry_level: str, rca_doc: dict | None = None) -> tuple:
    """Run request_retry with all MongoDB/RabbitMQ mocked.

    Returns (results, mock_publish, mock_attempts_col, mock_val_col, mock_rca_col).
    """
    from backend.eventprocessing.retry_service import request_retry

    alert_id = str(alert_doc["_id"])

    with (
        patch("backend.eventprocessing.retry_service.alerts_col_sync") as mock_alerts,
        patch("backend.eventprocessing.retry_service.rca_results_col_sync") as mock_rca,
        patch("backend.eventprocessing.retry_service.validation_results_col_sync") as mock_val,
        patch("backend.eventprocessing.retry_service.classifier_match_logs_col_sync") as mock_cls,
        patch("backend.eventprocessing.retry_service.alert_retry_attempts_col_sync") as mock_attempts,
        patch("backend.eventprocessing.retry_service.retry_stage_events_col_sync") as mock_events,
        patch("backend.eventprocessing.retry_service.publish") as mock_publish,
    ):
        mock_alerts.return_value.find_one.return_value = alert_doc
        mock_alerts.return_value.update_one.return_value = MagicMock()

        # Level 4: return a real rca_doc from rca_results when latest_effective_rca_id absent
        if rca_doc:
            mock_rca.return_value.find_one.return_value = rca_doc
        else:
            mock_rca.return_value.find_one.return_value = None
        mock_rca.return_value.update_many.return_value = MagicMock()
        mock_val.return_value.update_many.return_value = MagicMock()
        mock_cls.return_value.update_many.return_value = MagicMock()
        mock_attempts.return_value.find_one.return_value = None  # no existing attempt
        mock_attempts.return_value.insert_one.return_value = MagicMock(inserted_id=ObjectId())
        mock_events.return_value.insert_one.return_value = MagicMock(inserted_id=ObjectId())

        results = request_retry([alert_id], retry_level)

    return results, mock_publish, mock_attempts, mock_val, mock_rca, mock_alerts


# ---------------------------------------------------------------------------
# Level 1 — full pipeline re-run (alert_ingest queue)
# ---------------------------------------------------------------------------

class TestLevel1Retry:
    """Level 1: fresh ingested alert with no SOP or RCA. Re-runs full pipeline."""

    def setup_method(self):
        self.data = _load_data_file("level1_high_cpu_alert.json")
        self.alert_oid = ObjectId()
        self.alert_doc = _build_db_alert(self.data, self.alert_oid)

    def test_data_file_has_correct_retry_level(self):
        assert self.data["retry_level"] == "level1"
        assert self.data["expected_queue"] == "alert_ingest"

    def test_alert_has_no_sop_or_rca(self):
        assert self.data["alert"]["sop_workflow_id"] is None
        assert self.data["alert"]["sop_document_id"] is None
        assert self.data["alert"]["latest_effective_rca_id"] is None

    def test_accepted(self):
        results, *_ = _run_retry(self.alert_doc, "level1")
        assert len(results) == 1
        result = results[0]
        assert result.accepted is True, f"Expected accepted=True but got: {result.reason}"

    def test_batch_id_assigned(self):
        results, *_ = _run_retry(self.alert_doc, "level1")
        assert results[0].batch_id is not None
        assert len(results[0].batch_id) > 0

    def test_published_to_alert_ingest_queue(self):
        results, mock_publish, *_ = _run_retry(self.alert_doc, "level1")
        assert results[0].accepted is True
        mock_publish.assert_called_once()
        queue_name = mock_publish.call_args[0][0]
        assert queue_name == "alert_ingest", f"Expected alert_ingest but got: {queue_name}"

    def test_published_payload_has_retry_metadata(self):
        results, mock_publish, *_ = _run_retry(self.alert_doc, "level1")
        payload = mock_publish.call_args[0][1]
        assert payload["run_kind"] == "retry"
        assert payload["retry_level"] == "level1"
        assert payload["retry_batch_id"] == results[0].batch_id
        assert payload["initiated_from_stage"] == "alert_ingest"

    def test_attempt_record_inserted(self):
        results, _, mock_attempts, *_ = _run_retry(self.alert_doc, "level1")
        assert results[0].accepted is True
        mock_attempts.return_value.insert_one.assert_called_once()
        attempt_doc = mock_attempts.return_value.insert_one.call_args[0][0]
        assert attempt_doc["state"] == "queued"
        assert attempt_doc["retry_level"] == "level1"
        assert attempt_doc["alert_id"] == str(self.alert_oid)

    def test_sop_fields_cleared_on_alert(self):
        """Level 1 must null out sop_document_id, sop_workflow_id, sop_id on the alert."""
        results, _, _, _, _, mock_alerts = _run_retry(self.alert_doc, "level1")
        assert results[0].accepted is True
        update_calls = mock_alerts.return_value.update_one.call_args_list
        # Find the call that nullifies SOP fields
        sop_clear = any(
            "$set" in str(c) and "sop_workflow_id" in str(c)
            for c in update_calls
        )
        assert sop_clear, "Expected sop_workflow_id to be cleared in an update_one call"

    def test_source_application_matches_data_file(self):
        assert self.data["alert"]["source_application"] == "order-service"
        assert self.alert_doc["source_application"] == "order-service"

    def test_severity_is_critical(self):
        assert self.data["alert"]["severity"] == "critical"


# ---------------------------------------------------------------------------
# Level 2 — re-classify (stage1_identify queue)
# ---------------------------------------------------------------------------

class TestLevel2Retry:
    """Level 2: SOP identification previously failed. Re-run classifier."""

    def setup_method(self):
        self.data = _load_data_file("level2_memory_leak_alert.json")
        self.alert_oid = ObjectId()
        self.alert_doc = _build_db_alert(self.data, self.alert_oid)

    def test_data_file_has_correct_retry_level(self):
        assert self.data["retry_level"] == "level2"
        assert self.data["expected_queue"] == "stage1_identify"

    def test_alert_processing_status_is_sop_not_found(self):
        assert self.data["alert"]["processing_status"] == "SOPNotFound"

    def test_alert_has_no_sop_workflow(self):
        assert self.data["alert"]["sop_workflow_id"] is None

    def test_accepted(self):
        results, *_ = _run_retry(self.alert_doc, "level2")
        assert results[0].accepted is True, f"Expected accepted=True but got: {results[0].reason}"

    def test_published_to_stage1_identify_queue(self):
        results, mock_publish, *_ = _run_retry(self.alert_doc, "level2")
        assert results[0].accepted is True
        mock_publish.assert_called_once()
        queue_name = mock_publish.call_args[0][0]
        assert queue_name == "stage1_identify", f"Expected stage1_identify but got: {queue_name}"

    def test_published_payload_has_retry_metadata(self):
        results, mock_publish, *_ = _run_retry(self.alert_doc, "level2")
        payload = mock_publish.call_args[0][1]
        assert payload["run_kind"] == "retry"
        assert payload["retry_level"] == "level2"
        assert payload["initiated_from_stage"] == "stage1_identify"

    def test_attempt_record_inserted_with_correct_level(self):
        results, _, mock_attempts, *_ = _run_retry(self.alert_doc, "level2")
        assert results[0].accepted is True
        attempt_doc = mock_attempts.return_value.insert_one.call_args[0][0]
        assert attempt_doc["retry_level"] == "level2"
        assert attempt_doc["state"] == "queued"

    def test_rca_and_validation_soft_invalidated(self):
        """Level 2 must mark prior rca_results and validation_results inactive."""
        results, _, _, mock_val, mock_rca, _ = _run_retry(self.alert_doc, "level2")
        assert results[0].accepted is True
        mock_rca.return_value.update_many.assert_called_once()
        mock_val.return_value.update_many.assert_called_once()

    def test_source_application_is_auth_service(self):
        assert self.data["alert"]["source_application"] == "user-auth-service"

    def test_retry_attempt_count_is_1(self):
        """Data file models a second retry attempt (count=1 from first attempt)."""
        assert self.data["alert"]["retry_attempt_count"] == 1


# ---------------------------------------------------------------------------
# Level 3 — re-execute SOP (stage2_execute queue)
# ---------------------------------------------------------------------------

class TestLevel3Retry:
    """Level 3: SOP identified and mapped, but RCA execution failed. Re-run from stage2."""

    def setup_method(self):
        self.data = _load_data_file("level3_db_connection_pool_alert.json")
        self.alert_oid = ObjectId()
        self.alert_doc = _build_db_alert(self.data, self.alert_oid)

    def test_data_file_has_correct_retry_level(self):
        assert self.data["retry_level"] == "level3"
        assert self.data["expected_queue"] == "stage2_execute"

    def test_alert_has_sop_workflow_id(self):
        """Level 3 prerequisite: sop_workflow_id must be present."""
        assert self.data["alert"]["sop_workflow_id"] is not None
        assert len(self.data["alert"]["sop_workflow_id"]) > 0

    def test_alert_processing_status_is_failed(self):
        assert self.data["alert"]["processing_status"] == "sop_workflow_processfailed"

    def test_supporting_doc_workflow_provided(self):
        """Data file includes the SOP workflow document for context."""
        wf = self.data["supporting_docs"]["sop_workflow"]
        assert wf is not None
        assert wf["sop_id"] == "SOP_DB_CONN_POOL"
        assert len(wf["triaging_steps"]) == 3

    def test_accepted(self):
        results, *_ = _run_retry(self.alert_doc, "level3")
        assert results[0].accepted is True, f"Expected accepted=True but got: {results[0].reason}"

    def test_published_to_stage2_execute_queue(self):
        results, mock_publish, *_ = _run_retry(self.alert_doc, "level3")
        assert results[0].accepted is True
        mock_publish.assert_called_once()
        queue_name = mock_publish.call_args[0][0]
        assert queue_name == "stage2_execute", f"Expected stage2_execute but got: {queue_name}"

    def test_published_payload_has_retry_metadata(self):
        results, mock_publish, *_ = _run_retry(self.alert_doc, "level3")
        payload = mock_publish.call_args[0][1]
        assert payload["run_kind"] == "retry"
        assert payload["retry_level"] == "level3"
        assert payload["initiated_from_stage"] == "stage2_execute"

    def test_published_payload_preserves_sop_fields(self):
        """SOP fields must be forwarded in the payload so stage2 can use them."""
        results, mock_publish, *_ = _run_retry(self.alert_doc, "level3")
        payload = mock_publish.call_args[0][1]
        assert payload.get("sop_workflow_id") == self.data["alert"]["sop_workflow_id"]
        assert payload.get("sop_id") == self.data["alert"]["sop_id"]

    def test_attempt_record_inserted_with_correct_level(self):
        results, _, mock_attempts, *_ = _run_retry(self.alert_doc, "level3")
        assert results[0].accepted is True
        attempt_doc = mock_attempts.return_value.insert_one.call_args[0][0]
        assert attempt_doc["retry_level"] == "level3"

    def test_validation_results_soft_invalidated(self):
        """Level 3 must mark prior validation_results inactive (not rca_results)."""
        results, _, _, mock_val, mock_rca, _ = _run_retry(self.alert_doc, "level3")
        assert results[0].accepted is True
        mock_val.return_value.update_many.assert_called_once()
        mock_rca.return_value.update_many.assert_not_called()

    def test_level3_rejected_without_sop_workflow_id(self):
        """Confirm rejection when sop_workflow_id is missing (prerequisite check)."""
        bad_alert = dict(self.alert_doc)
        bad_alert["sop_workflow_id"] = None
        results, *_ = _run_retry(bad_alert, "level3")
        assert results[0].accepted is False
        assert "level2" in results[0].reason or "level1" in results[0].reason


# ---------------------------------------------------------------------------
# Level 4 — re-validate RCA (stage3_validate queue)
# ---------------------------------------------------------------------------

class TestLevel4Retry:
    """Level 4: RCA generated but validation failed or low confidence. Re-run validation."""

    def setup_method(self):
        self.data = _load_data_file("level4_disk_space_alert.json")
        self.alert_oid = ObjectId()
        self.alert_doc = _build_db_alert(self.data, self.alert_oid)
        # Build a minimal rca_results doc as it would appear in MongoDB
        self.rca_oid = ObjectId()
        raw_rca = self.data["supporting_docs"]["rca_result"]
        self.rca_doc = dict(raw_rca)
        self.rca_doc["_id"] = self.rca_oid
        self.rca_doc["alert_id"] = str(self.alert_oid)
        self.rca_doc["workflow_id"] = self.data["alert"]["sop_workflow_id"]
        self.rca_doc["created_at"] = "2026-04-25T13:00:00Z"

    def test_data_file_has_correct_retry_level(self):
        assert self.data["retry_level"] == "level4"
        assert self.data["expected_queue"] == "stage3_validate"

    def test_alert_has_rca_id(self):
        """Level 4 prerequisite: latest_effective_rca_id must be present."""
        assert self.data["alert"]["latest_effective_rca_id"] is not None

    def test_alert_status_is_rca_not_validated(self):
        assert self.data["alert"]["processing_status"] == "RCANotValidated"

    def test_supporting_doc_rca_provided(self):
        rca = self.data["supporting_docs"]["rca_result"]
        assert rca is not None
        assert rca["sop_id"] == "SOP_DISK_SPACE_FULL_LINUX"
        assert len(rca["triaging_results"]) == 3
        assert "root_cause" in rca
        assert "recommendation" in rca
        assert rca["is_active_latest"] is True

    def test_accepted_with_latest_effective_rca_id(self):
        results, *_ = _run_retry(self.alert_doc, "level4")
        assert results[0].accepted is True, f"Expected accepted=True but got: {results[0].reason}"

    def test_accepted_via_rca_results_collection(self):
        """Level 4 also accepts if rca_results has an active doc (fallback check)."""
        alert_no_rca_id = dict(self.alert_doc)
        alert_no_rca_id["latest_effective_rca_id"] = None
        results, *_ = _run_retry(alert_no_rca_id, "level4", rca_doc=self.rca_doc)
        assert results[0].accepted is True

    def test_rejected_without_any_rca(self):
        """Rejected when neither latest_effective_rca_id nor active rca_results exists."""
        alert_no_rca_id = dict(self.alert_doc)
        alert_no_rca_id["latest_effective_rca_id"] = None
        results, *_ = _run_retry(alert_no_rca_id, "level4", rca_doc=None)
        assert results[0].accepted is False
        reason = results[0].reason.lower()
        assert "rca" in reason

    def test_published_to_stage3_validate_queue(self):
        results, mock_publish, *_ = _run_retry(self.alert_doc, "level4")
        assert results[0].accepted is True
        mock_publish.assert_called_once()
        queue_name = mock_publish.call_args[0][0]
        assert queue_name == "stage3_validate", f"Expected stage3_validate but got: {queue_name}"

    def test_published_payload_has_retry_metadata(self):
        results, mock_publish, *_ = _run_retry(self.alert_doc, "level4")
        payload = mock_publish.call_args[0][1]
        assert payload["run_kind"] == "retry"
        assert payload["retry_level"] == "level4"
        assert payload["initiated_from_stage"] == "stage3_validate"

    def test_published_payload_preserves_sop_and_rca_fields(self):
        results, mock_publish, *_ = _run_retry(self.alert_doc, "level4")
        payload = mock_publish.call_args[0][1]
        assert payload.get("sop_workflow_id") == self.data["alert"]["sop_workflow_id"]
        assert payload.get("sop_id") == self.data["alert"]["sop_id"]
        assert payload.get("latest_effective_rca_id") == self.data["alert"]["latest_effective_rca_id"]

    def test_attempt_record_inserted_with_correct_level(self):
        results, _, mock_attempts, *_ = _run_retry(self.alert_doc, "level4")
        assert results[0].accepted is True
        attempt_doc = mock_attempts.return_value.insert_one.call_args[0][0]
        assert attempt_doc["retry_level"] == "level4"
        assert attempt_doc["state"] == "queued"

    def test_validation_results_soft_invalidated(self):
        """Level 4 must mark prior validation_results inactive."""
        results, _, _, mock_val, mock_rca, _ = _run_retry(self.alert_doc, "level4")
        assert results[0].accepted is True
        mock_val.return_value.update_many.assert_called_once()

    def test_rca_results_not_soft_invalidated(self):
        """Level 4 must NOT touch rca_results — only validation is re-run."""
        results, _, _, mock_val, mock_rca, _ = _run_retry(self.alert_doc, "level4")
        assert results[0].accepted is True
        mock_rca.return_value.update_many.assert_not_called()


# ---------------------------------------------------------------------------
# Cross-level: queue routing contract
# ---------------------------------------------------------------------------

class TestQueueRoutingContract:
    """Verifies the 4-level queue routing contract is honoured for all data files."""

    CASES = [
        ("level1_high_cpu_alert.json", "level1", "alert_ingest"),
        ("level2_memory_leak_alert.json", "level2", "stage1_identify"),
        ("level3_db_connection_pool_alert.json", "level3", "stage2_execute"),
        ("level4_disk_space_alert.json", "level4", "stage3_validate"),
    ]

    @pytest.mark.parametrize("filename,level,expected_queue", CASES)
    def test_correct_queue_for_each_level(self, filename, level, expected_queue):
        data = _load_data_file(filename)
        alert_oid = ObjectId()
        alert_doc = _build_db_alert(data, alert_oid)

        rca_doc = None
        if data["supporting_docs"].get("rca_result"):
            rca_doc = dict(data["supporting_docs"]["rca_result"])
            rca_doc["_id"] = ObjectId()
            rca_doc["alert_id"] = str(alert_oid)

        results, mock_publish, *_ = _run_retry(alert_doc, level, rca_doc=rca_doc)
        assert results[0].accepted is True, (
            f"Level {level}: expected accepted=True, got: {results[0].reason}"
        )
        actual_queue = mock_publish.call_args[0][0]
        assert actual_queue == expected_queue, (
            f"Level {level}: expected queue={expected_queue}, got {actual_queue}"
        )

    @pytest.mark.parametrize("filename,level,_", CASES)
    def test_data_file_retry_level_consistent(self, filename, level, _):
        data = _load_data_file(filename)
        assert data["retry_level"] == level, (
            f"{filename}: retry_level in file ({data['retry_level']}) != expected ({level})"
        )

    @pytest.mark.parametrize("filename,level,expected_queue", CASES)
    def test_data_file_expected_queue_consistent(self, filename, level, expected_queue):
        data = _load_data_file(filename)
        assert data["expected_queue"] == expected_queue, (
            f"{filename}: expected_queue ({data['expected_queue']}) != {expected_queue}"
        )


# ---------------------------------------------------------------------------
# Cross-level: soft-invalidation rules
# ---------------------------------------------------------------------------

class TestSoftInvalidationContract:
    """Verifies the correct soft-invalidation behaviour for each level."""

    def _run_level(self, filename: str, level: str):
        data = _load_data_file(filename)
        alert_oid = ObjectId()
        alert_doc = _build_db_alert(data, alert_oid)

        rca_doc = None
        if data["supporting_docs"].get("rca_result"):
            rca_doc = dict(data["supporting_docs"]["rca_result"])
            rca_doc["_id"] = ObjectId()
            rca_doc["alert_id"] = str(alert_oid)

        return _run_retry(alert_doc, level, rca_doc=rca_doc)

    def test_level1_clears_both_rca_and_validation(self):
        results, _, _, mock_val, mock_rca, _ = self._run_level(
            "level1_high_cpu_alert.json", "level1"
        )
        assert results[0].accepted is True
        mock_rca.return_value.update_many.assert_called_once()
        mock_val.return_value.update_many.assert_called_once()

    def test_level2_clears_both_rca_and_validation(self):
        results, _, _, mock_val, mock_rca, _ = self._run_level(
            "level2_memory_leak_alert.json", "level2"
        )
        assert results[0].accepted is True
        mock_rca.return_value.update_many.assert_called_once()
        mock_val.return_value.update_many.assert_called_once()

    def test_level3_clears_validation_only(self):
        results, _, _, mock_val, mock_rca, _ = self._run_level(
            "level3_db_connection_pool_alert.json", "level3"
        )
        assert results[0].accepted is True
        mock_val.return_value.update_many.assert_called_once()
        mock_rca.return_value.update_many.assert_not_called()

    def test_level4_clears_validation_only(self):
        results, _, _, mock_val, mock_rca, _ = self._run_level(
            "level4_disk_space_alert.json", "level4"
        )
        assert results[0].accepted is True
        mock_val.return_value.update_many.assert_called_once()
        mock_rca.return_value.update_many.assert_not_called()
