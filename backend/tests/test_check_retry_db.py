"""Tests for scripts/check_retry_db.py.

Mocks the pymongo client so no live database connection is needed.
Tests cover each display mode: recent, alert, batch, summary.
"""
import importlib
import sys
import types
import uuid
from datetime import UTC, datetime
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from bson import ObjectId


# ---------------------------------------------------------------------------
# Module loader helper (re-imports script with mocked MongoClient each time)
# ---------------------------------------------------------------------------

def _load_script(mock_db: MagicMock) -> types.ModuleType:
    """Import check_retry_db with a mocked db object injected."""
    # Remove any cached import so module-level client init runs fresh
    sys.modules.pop("check_retry_db", None)
    sys.modules.pop("scripts.check_retry_db", None)

    import importlib.util
    import pathlib
    spec = importlib.util.spec_from_file_location(
        "check_retry_db",
        pathlib.Path(__file__).parent.parent.parent / "scripts" / "check_retry_db.py",
    )
    mod = importlib.util.module_from_spec(spec)

    with patch("pymongo.MongoClient", return_value=MagicMock()):
        spec.loader.exec_module(mod)

    # Inject the mock db directly
    mod.db = mock_db
    return mod


# ---------------------------------------------------------------------------
# Fixtures / test data builders
# ---------------------------------------------------------------------------

def _make_attempt(
    alert_id: str | None = None,
    batch_id: str | None = None,
    level: str = "level1",
    state: str = "completed",
    attempt_number: int = 1,
) -> dict:
    return {
        "_id": ObjectId(),
        "alert_id": alert_id or str(ObjectId()),
        "batch_id": batch_id or str(uuid.uuid4()),
        "retry_level": level,
        "attempt_number": attempt_number,
        "state": state,
        "triggered_queue": {"level1": "alert_ingest", "level2": "stage1_identify",
                            "level3": "stage2_execute", "level4": "stage3_validate"}[level],
        "reason": "manual retry",
        "requested_at": datetime(2026, 4, 25, 10, 0, 0, tzinfo=UTC),
        "completed_at": datetime(2026, 4, 25, 10, 1, 30, tzinfo=UTC),
        "prior_status_snapshot": {"processing_status": "SOPNotFound", "latest_effective_rca_id": None},
        "error_summary": None,
    }


def _make_event(batch_id: str, alert_id: str, stage: str = "stage1_identify",
                status: str = "completed") -> dict:
    return {
        "_id": ObjectId(),
        "batch_id": batch_id,
        "alert_id": alert_id,
        "stage": stage,
        "status": status,
        "started_at": datetime(2026, 4, 25, 10, 0, 5, tzinfo=UTC),
        "completed_at": datetime(2026, 4, 25, 10, 1, 0, tzinfo=UTC),
        "detail": "SOP identified: SOP_HIGH_CPU",
    }


def _make_alert_doc(alert_id: str, retry_count: int = 1, in_progress: bool = False) -> dict:
    return {
        "_id": ObjectId(alert_id),
        "source_application": "order-service",
        "processing_status": "completed",
        "retry_in_progress": in_progress,
        "retry_attempt_count": retry_count,
        "latest_retry_level": "level1",
        "latest_retry_batch_id": str(uuid.uuid4()),
        "latest_effective_rca_id": str(ObjectId()),
        "retry_requested_at": datetime(2026, 4, 25, 10, 0, 0, tzinfo=UTC),
    }


def _mock_collection(docs: list) -> MagicMock:
    """Return a MagicMock collection whose find() returns a list cursor."""
    col = MagicMock()
    cursor = MagicMock()
    cursor.__iter__ = MagicMock(return_value=iter(docs))
    cursor.limit = MagicMock(return_value=iter(docs))
    cursor.sort = MagicMock(return_value=iter(docs))
    col.find.return_value = cursor
    col.find_one.return_value = docs[0] if docs else None
    col.count_documents.return_value = len(docs)
    return col


# ---------------------------------------------------------------------------
# Helpers / formatting tests (no DB needed)
# ---------------------------------------------------------------------------

class TestFormatHelpers:
    def setup_method(self):
        self.mod = _load_script(MagicMock())

    def test_fmt_dt_none(self):
        assert self.mod._fmt_dt(None) == "—"

    def test_fmt_dt_datetime(self):
        dt = datetime(2026, 4, 25, 10, 30, 0, tzinfo=UTC)
        result = self.mod._fmt_dt(dt)
        assert "2026-04-25" in result
        assert "10:30:00" in result

    def test_fmt_dt_string_passthrough(self):
        assert self.mod._fmt_dt("some-string") == "some-string"

    def test_state_tag_known(self):
        assert self.mod._state_tag("completed") == "COMPLETED"
        assert self.mod._state_tag("failed") == "FAILED"
        assert self.mod._state_tag("running_stage1") == "RUNNING stage1"

    def test_state_tag_unknown_uppercases(self):
        assert self.mod._state_tag("custom_state") == "CUSTOM_STATE"

    def test_duration_calculates_seconds(self):
        start = datetime(2026, 4, 25, 10, 0, 0, tzinfo=UTC)
        end = datetime(2026, 4, 25, 10, 0, 45, tzinfo=UTC)
        result = self.mod._duration(start, end)
        assert "45.0s" in result

    def test_duration_none_start(self):
        assert self.mod._duration(None, datetime.now(UTC)) == ""

    def test_duration_none_end(self):
        assert self.mod._duration(datetime.now(UTC), None) == ""


# ---------------------------------------------------------------------------
# show_recent
# ---------------------------------------------------------------------------

class TestShowRecent:
    def _run(self, attempts: list, events: list | None = None) -> str:
        mock_db = MagicMock()
        events = events or []

        # find() with sort+limit chain
        cursor = MagicMock()
        cursor.limit.return_value = iter(attempts)
        sort_cursor = MagicMock()
        sort_cursor.limit = cursor.limit
        mock_db.alert_retry_attempts.find.return_value = sort_cursor

        mock_db.retry_stage_events.find.return_value = iter(events)
        mock_db.alert_retry_attempts.count_documents.return_value = len(attempts)
        mock_db.retry_stage_events.count_documents.return_value = len(events)
        mock_db.alerts.count_documents.return_value = 0

        mod = _load_script(mock_db)
        buf = StringIO()
        with patch("sys.stdout", buf):
            mod.show_recent(limit=20)
        return buf.getvalue()

    def test_empty_database_prints_no_attempts(self):
        out = self._run([])
        assert "no retry attempts found" in out

    def test_single_attempt_shown(self):
        alert_id = str(ObjectId())
        batch_id = str(uuid.uuid4())
        attempt = _make_attempt(alert_id=alert_id, batch_id=batch_id, level="level1")
        out = self._run([attempt])
        assert batch_id in out
        assert alert_id in out
        assert "level1" in out
        assert "alert_ingest" in out

    def test_completed_state_label(self):
        attempt = _make_attempt(state="completed")
        out = self._run([attempt])
        assert "COMPLETED" in out

    def test_failed_state_label(self):
        attempt = _make_attempt(state="failed")
        out = self._run([attempt])
        assert "FAILED" in out

    def test_stage_events_shown(self):
        alert_id = str(ObjectId())
        batch_id = str(uuid.uuid4())
        attempt = _make_attempt(alert_id=alert_id, batch_id=batch_id)
        event = _make_event(batch_id=batch_id, alert_id=alert_id)
        out = self._run([attempt], events=[event])
        assert "stage1_identify" in out
        assert "SOP identified" in out

    def test_db_counts_printed(self):
        attempt = _make_attempt()
        out = self._run([attempt])
        assert "DB totals" in out

    def test_all_four_levels_shown(self):
        attempts = [_make_attempt(level=f"level{i}") for i in range(1, 5)]
        out = self._run(attempts)
        for level in ("level1", "level2", "level3", "level4"):
            assert level in out


# ---------------------------------------------------------------------------
# show_alert
# ---------------------------------------------------------------------------

class TestShowAlert:
    def _run(self, alert_id: str, attempts: list, alert_doc: dict | None = None,
             events: list | None = None) -> str:
        mock_db = MagicMock()
        events = events or []

        mock_db.alerts.find_one.return_value = alert_doc
        mock_db.alert_retry_attempts.find.return_value = iter(attempts)
        mock_db.retry_stage_events.find.return_value = iter(events)

        mod = _load_script(mock_db)
        buf = StringIO()
        with patch("sys.stdout", buf):
            mod.show_alert(alert_id)
        return buf.getvalue()

    def test_alert_not_found_warning(self):
        bad_id = str(ObjectId())
        out = self._run(bad_id, attempts=[], alert_doc=None)
        assert "WARNING" in out or "not found" in out.lower()

    def test_alert_metadata_displayed(self):
        alert_id = str(ObjectId())
        alert_doc = _make_alert_doc(alert_id)
        out = self._run(alert_id, attempts=[], alert_doc=alert_doc)
        assert "order-service" in out
        assert "retry_attempt_count" in out or "1" in out

    def test_attempts_listed(self):
        alert_id = str(ObjectId())
        batch_id = str(uuid.uuid4())
        alert_doc = _make_alert_doc(alert_id)
        attempt = _make_attempt(alert_id=alert_id, batch_id=batch_id, level="level2")
        out = self._run(alert_id, attempts=[attempt], alert_doc=alert_doc)
        assert batch_id in out
        assert "level2" in out
        assert "stage1_identify" in out

    def test_no_attempts_message(self):
        alert_id = str(ObjectId())
        alert_doc = _make_alert_doc(alert_id, retry_count=0)
        out = self._run(alert_id, attempts=[], alert_doc=alert_doc)
        assert "no retry attempts" in out.lower()

    def test_stage_events_nested_under_attempt(self):
        alert_id = str(ObjectId())
        batch_id = str(uuid.uuid4())
        alert_doc = _make_alert_doc(alert_id)
        attempt = _make_attempt(alert_id=alert_id, batch_id=batch_id, level="level3")
        event = _make_event(batch_id=batch_id, alert_id=alert_id, stage="stage2_execute")
        out = self._run(alert_id, attempts=[attempt], alert_doc=alert_doc, events=[event])
        assert "stage2_execute" in out

    def test_multiple_attempts_for_same_alert(self):
        alert_id = str(ObjectId())
        alert_doc = _make_alert_doc(alert_id, retry_count=3)
        attempts = [
            _make_attempt(alert_id=alert_id, level="level1", attempt_number=1),
            _make_attempt(alert_id=alert_id, level="level2", attempt_number=2),
            _make_attempt(alert_id=alert_id, level="level2", attempt_number=3),
        ]
        out = self._run(alert_id, attempts=attempts, alert_doc=alert_doc)
        assert "level1" in out
        assert "level2" in out


# ---------------------------------------------------------------------------
# show_batch
# ---------------------------------------------------------------------------

class TestShowBatch:
    def _run(self, batch_id: str, attempts: list, events: list | None = None) -> str:
        mock_db = MagicMock()
        events = events or []

        mock_db.alert_retry_attempts.find.return_value = iter(attempts)
        mock_db.retry_stage_events.find.return_value = iter(events)

        mod = _load_script(mock_db)
        buf = StringIO()
        with patch("sys.stdout", buf):
            mod.show_batch(batch_id)
        return buf.getvalue()

    def test_batch_not_found(self):
        out = self._run("nonexistent-batch", attempts=[])
        assert "no attempts found" in out.lower()

    def test_overall_completed_all_complete(self):
        batch_id = str(uuid.uuid4())
        attempts = [
            _make_attempt(batch_id=batch_id, state="completed"),
            _make_attempt(batch_id=batch_id, state="completed"),
        ]
        out = self._run(batch_id, attempts=attempts)
        assert "COMPLETED" in out

    def test_overall_failed_all_failed(self):
        batch_id = str(uuid.uuid4())
        attempts = [_make_attempt(batch_id=batch_id, state="failed")]
        out = self._run(batch_id, attempts=attempts)
        assert "FAILED" in out

    def test_overall_partial_mixed(self):
        batch_id = str(uuid.uuid4())
        attempts = [
            _make_attempt(batch_id=batch_id, state="completed"),
            _make_attempt(batch_id=batch_id, state="failed"),
        ]
        out = self._run(batch_id, attempts=attempts)
        assert "PARTIAL" in out

    def test_overall_in_progress(self):
        batch_id = str(uuid.uuid4())
        attempts = [_make_attempt(batch_id=batch_id, state="running_stage2")]
        out = self._run(batch_id, attempts=attempts)
        assert "IN PROGRESS" in out

    def test_batch_shows_level_and_queue(self):
        batch_id = str(uuid.uuid4())
        attempts = [_make_attempt(batch_id=batch_id, level="level4", state="completed")]
        out = self._run(batch_id, attempts=attempts)
        assert "level4" in out
        assert "stage3_validate" in out

    def test_batch_alert_count_shown(self):
        batch_id = str(uuid.uuid4())
        attempts = [
            _make_attempt(batch_id=batch_id, state="completed"),
            _make_attempt(batch_id=batch_id, state="completed"),
            _make_attempt(batch_id=batch_id, state="failed"),
        ]
        out = self._run(batch_id, attempts=attempts)
        assert "3" in out


# ---------------------------------------------------------------------------
# show_summary
# ---------------------------------------------------------------------------

class TestShowSummary:
    def _build_mock_db(self, total_attempts: int = 5) -> MagicMock:
        mock_db = MagicMock()

        def count_docs(query=None):
            if not query:
                return total_attempts
            # Per-level counts
            level = query.get("retry_level")
            if level:
                return {"level1": 2, "level2": 1, "level3": 1, "level4": 1}.get(level, 0)
            # Per-state counts
            state = query.get("state")
            if state:
                return {"completed": 3, "failed": 2}.get(state, 0)
            # Alert fields
            if "$gt" in str(query):
                return 3  # alerts_with_retries
            if "retry_in_progress" in query:
                return 1  # in_progress
            return 0

        mock_db.alert_retry_attempts.count_documents.side_effect = count_docs
        mock_db.alerts.count_documents.side_effect = count_docs
        mock_db.retry_stage_events.count_documents.side_effect = count_docs

        # Aggregate for latest batches
        batch_id = str(uuid.uuid4())
        mock_db.alert_retry_attempts.aggregate.return_value = iter([
            {
                "_id": batch_id,
                "level": "level1",
                "state": "completed",
                "alert_count": 2,
                "requested_at": datetime(2026, 4, 25, 10, 0, 0, tzinfo=UTC),
            }
        ])

        return mock_db

    def test_empty_summary(self):
        mock_db = MagicMock()
        mock_db.alert_retry_attempts.count_documents.return_value = 0
        mod = _load_script(mock_db)
        buf = StringIO()
        with patch("sys.stdout", buf):
            mod.show_summary()
        out = buf.getvalue()
        assert "no retry data" in out.lower()

    def test_total_attempts_shown(self):
        mock_db = self._build_mock_db(total_attempts=5)
        mod = _load_script(mock_db)
        buf = StringIO()
        with patch("sys.stdout", buf):
            mod.show_summary()
        out = buf.getvalue()
        assert "5" in out
        assert "Total retry attempts" in out

    def test_all_four_levels_listed(self):
        mock_db = self._build_mock_db()
        mod = _load_script(mock_db)
        buf = StringIO()
        with patch("sys.stdout", buf):
            mod.show_summary()
        out = buf.getvalue()
        for level in ("level1", "level2", "level3", "level4"):
            assert level in out

    def test_queue_names_shown_in_summary(self):
        mock_db = self._build_mock_db()
        mod = _load_script(mock_db)
        buf = StringIO()
        with patch("sys.stdout", buf):
            mod.show_summary()
        out = buf.getvalue()
        assert "alert_ingest" in out
        assert "stage1_identify" in out
        assert "stage2_execute" in out
        assert "stage3_validate" in out

    def test_latest_batches_shown(self):
        mock_db = self._build_mock_db()
        mod = _load_script(mock_db)
        buf = StringIO()
        with patch("sys.stdout", buf):
            mod.show_summary()
        out = buf.getvalue()
        assert "Latest" in out and "batch" in out.lower()

    def test_alerts_with_retries_shown(self):
        mock_db = self._build_mock_db()
        mod = _load_script(mock_db)
        buf = StringIO()
        with patch("sys.stdout", buf):
            mod.show_summary()
        out = buf.getvalue()
        assert "Alerts with retries" in out


# ---------------------------------------------------------------------------
# Integration: all four retry level data files produce correct output
# ---------------------------------------------------------------------------

class TestAllFourLevelsOutput:
    """Loads the 4 test data files and verifies check_retry_db correctly displays each."""

    LEVEL_QUEUE = {
        "level1": "alert_ingest",
        "level2": "stage1_identify",
        "level3": "stage2_execute",
        "level4": "stage3_validate",
    }

    @pytest.mark.parametrize("level,queue", [
        ("level1", "alert_ingest"),
        ("level2", "stage1_identify"),
        ("level3", "stage2_execute"),
        ("level4", "stage3_validate"),
    ])
    def test_attempt_display_for_level(self, level: str, queue: str):
        alert_id = str(ObjectId())
        batch_id = str(uuid.uuid4())
        attempt = _make_attempt(alert_id=alert_id, batch_id=batch_id, level=level, state="queued")

        mock_db = MagicMock()
        mock_db.alert_retry_attempts.find.return_value = iter([attempt])
        mock_db.retry_stage_events.find.return_value = iter([])
        mock_db.alert_retry_attempts.count_documents.return_value = 1
        mock_db.retry_stage_events.count_documents.return_value = 0
        mock_db.alerts.count_documents.return_value = 0

        cursor = MagicMock()
        cursor.limit.return_value = iter([attempt])
        sort_cursor = MagicMock()
        sort_cursor.limit = cursor.limit
        mock_db.alert_retry_attempts.find.return_value = sort_cursor

        mod = _load_script(mock_db)
        buf = StringIO()
        with patch("sys.stdout", buf):
            mod.show_recent(limit=20)
        out = buf.getvalue()

        assert level in out, f"Expected {level} in output"
        assert queue in out, f"Expected {queue} in output"
        assert "QUEUED" in out
        assert batch_id in out
        assert alert_id in out

    @pytest.mark.parametrize("level,queue", [
        ("level1", "alert_ingest"),
        ("level2", "stage1_identify"),
        ("level3", "stage2_execute"),
        ("level4", "stage3_validate"),
    ])
    def test_batch_display_for_level(self, level: str, queue: str):
        batch_id = str(uuid.uuid4())
        attempt = _make_attempt(batch_id=batch_id, level=level, state="completed")

        mock_db = MagicMock()
        mock_db.alert_retry_attempts.find.return_value = iter([attempt])
        mock_db.retry_stage_events.find.return_value = iter([])

        mod = _load_script(mock_db)
        buf = StringIO()
        with patch("sys.stdout", buf):
            mod.show_batch(batch_id)
        out = buf.getvalue()

        assert level in out
        assert queue in out
        assert "COMPLETED" in out
