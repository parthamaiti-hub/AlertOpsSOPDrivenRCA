"""View retry data from MongoDB: attempts, stage events, and alert retry metadata.

Usage:
    uv run python scripts/check_retry_db.py                   # latest 20 retry attempts
    uv run python scripts/check_retry_db.py alert ALERT_ID    # all retries for one alert
    uv run python scripts/check_retry_db.py batch BATCH_ID    # full detail for one batch
    uv run python scripts/check_retry_db.py summary           # aggregate counts per level/state
"""

import sys
from datetime import datetime, timezone

from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
db = client["sop_alert_analytics"]

SEP = "-" * 70
WIDE = "=" * 70

# State → display label
STATE_LABELS = {
    "queued": "QUEUED",
    "running_stage1": "RUNNING stage1",
    "running_stage2": "RUNNING stage2",
    "running_stage3": "RUNNING stage3",
    "completed": "COMPLETED",
    "partially_completed": "PARTIAL",
    "failed": "FAILED",
}

LEVEL_QUEUE = {
    "level1": "alert_ingest",
    "level2": "stage1_identify",
    "level3": "stage2_execute",
    "level4": "stage3_validate",
}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _fmt_dt(val) -> str:
    if val is None:
        return "—"
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d %H:%M:%S UTC")
    return str(val)


def _duration(started, completed) -> str:
    if not started or not completed:
        return ""
    try:
        if isinstance(started, str):
            started = datetime.fromisoformat(started.replace("Z", "+00:00"))
        if isinstance(completed, str):
            completed = datetime.fromisoformat(completed.replace("Z", "+00:00"))
        diff = (completed - started).total_seconds()
        return f"  ({diff:.1f}s)"
    except Exception:
        return ""


def _state_tag(state: str) -> str:
    return STATE_LABELS.get(state, state.upper())


# ---------------------------------------------------------------------------
# Display functions
# ---------------------------------------------------------------------------

def _print_attempt(attempt: dict, include_events: bool = True):
    state = attempt.get("state", "")
    level = attempt.get("retry_level", "?")
    batch_id = attempt.get("batch_id", "?")
    alert_id = attempt.get("alert_id", "?")
    attempt_num = attempt.get("attempt_number", "?")
    triggered_queue = attempt.get("triggered_queue", LEVEL_QUEUE.get(level, "?"))
    requested_at = _fmt_dt(attempt.get("requested_at"))
    completed_at = _fmt_dt(attempt.get("completed_at"))
    dur = _duration(attempt.get("requested_at"), attempt.get("completed_at"))
    reason = attempt.get("reason") or ""
    error_summary = attempt.get("error_summary") or ""

    print(f"  batch_id        : {batch_id}")
    print(f"  alert_id        : {alert_id}")
    print(f"  attempt #       : {attempt_num}")
    print(f"  level           : {level}  →  queue: {triggered_queue}")
    print(f"  state           : {_state_tag(state)}")
    print(f"  requested_at    : {requested_at}")
    print(f"  completed_at    : {completed_at}{dur}")
    if reason:
        print(f"  reason          : {reason}")
    if error_summary:
        print(f"  error_summary   : {error_summary}")

    prior = attempt.get("prior_status_snapshot", {})
    if prior:
        print(f"  prior_status    : processing={prior.get('processing_status', '')}  "
              f"rca_id={prior.get('latest_effective_rca_id', '—')}")

    if include_events:
        events = list(db.retry_stage_events.find(
            {"batch_id": batch_id, "alert_id": alert_id},
            sort=[("started_at", 1)],
        ))
        if events:
            print(f"  stage events ({len(events)}):")
            for ev in events:
                stage = ev.get("stage", "?")
                status = ev.get("status", "?")
                started = _fmt_dt(ev.get("started_at"))
                finished = _fmt_dt(ev.get("completed_at"))
                dur_ev = _duration(ev.get("started_at"), ev.get("completed_at"))
                detail = ev.get("detail") or ""
                detail_str = f"  — {detail[:80]}" if detail else ""
                print(f"    [{status.upper():10}] {stage:<20}  {started}  →  {finished}{dur_ev}{detail_str}")
        else:
            print("  stage events    : (none)")


def _print_alert_retry_summary(alert: dict):
    """Print the retry-related fields from an alert document."""
    print(f"  alert_id               : {alert.get('_id', '?')}")
    print(f"  source_application     : {alert.get('source_application', '')}")
    print(f"  processing_status      : {alert.get('processing_status', '')}")
    print(f"  retry_in_progress      : {alert.get('retry_in_progress', False)}")
    print(f"  retry_attempt_count    : {alert.get('retry_attempt_count', 0)}")
    print(f"  latest_retry_level     : {alert.get('latest_retry_level') or '—'}")
    print(f"  latest_retry_batch_id  : {alert.get('latest_retry_batch_id') or '—'}")
    print(f"  latest_effective_rca_id: {alert.get('latest_effective_rca_id') or '—'}")
    print(f"  retry_requested_at     : {_fmt_dt(alert.get('retry_requested_at'))}")


# ---------------------------------------------------------------------------
# Mode: show latest N attempts
# ---------------------------------------------------------------------------

def show_recent(limit: int = 20):
    print(f"\n{WIDE}")
    print(f"RETRY ATTEMPTS  (latest {limit})")
    print(f"{WIDE}")

    attempts = list(
        db.alert_retry_attempts.find({}, sort=[("requested_at", -1)]).limit(limit)
    )
    if not attempts:
        print("  (no retry attempts found)")
        _print_db_counts()
        return

    for attempt in attempts:
        print(SEP)
        _print_attempt(attempt, include_events=True)

    print(SEP)
    _print_db_counts()


# ---------------------------------------------------------------------------
# Mode: show all retries for one alert
# ---------------------------------------------------------------------------

def show_alert(alert_id: str):
    print(f"\n{WIDE}")
    print(f"RETRY HISTORY  alert_id={alert_id}")
    print(f"{WIDE}")

    # Alert document
    from bson import ObjectId
    try:
        oid = ObjectId(alert_id)
        alert = db.alerts.find_one({"_id": oid})
    except Exception:
        alert = None

    if alert:
        print("\n  --- Alert Metadata ---")
        _print_alert_retry_summary(alert)
    else:
        print(f"  WARNING: alert {alert_id} not found in alerts collection")

    # Attempts
    attempts = list(
        db.alert_retry_attempts.find(
            {"alert_id": alert_id}, sort=[("requested_at", -1)]
        )
    )

    print(f"\n  Attempts found: {len(attempts)}")
    for attempt in attempts:
        print(SEP)
        _print_attempt(attempt, include_events=True)

    if not attempts:
        print("  (no retry attempts for this alert)")

    print(SEP)


# ---------------------------------------------------------------------------
# Mode: show full detail for one batch
# ---------------------------------------------------------------------------

def show_batch(batch_id: str):
    print(f"\n{WIDE}")
    print(f"RETRY BATCH  batch_id={batch_id}")
    print(f"{WIDE}")

    attempts = list(
        db.alert_retry_attempts.find({"batch_id": batch_id}, sort=[("alert_id", 1)])
    )
    if not attempts:
        print(f"  (no attempts found for batch {batch_id})")
        return

    states = [a.get("state", "") for a in attempts]
    if all(s == "completed" for s in states):
        overall = "COMPLETED"
    elif any(s == "failed" for s in states) and any(s == "completed" for s in states):
        overall = "PARTIALLY COMPLETED"
    elif all(s == "failed" for s in states):
        overall = "FAILED"
    else:
        overall = "IN PROGRESS"

    level = attempts[0].get("retry_level", "?")
    print(f"  level        : {level}  ({LEVEL_QUEUE.get(level, '?')})")
    print(f"  alert count  : {len(attempts)}")
    print(f"  overall      : {overall}")

    for attempt in attempts:
        print(SEP)
        _print_attempt(attempt, include_events=True)

    print(SEP)


# ---------------------------------------------------------------------------
# Mode: summary stats
# ---------------------------------------------------------------------------

def show_summary():
    print(f"\n{WIDE}")
    print("RETRY SUMMARY")
    print(f"{WIDE}")

    total = db.alert_retry_attempts.count_documents({})
    print(f"\n  Total retry attempts : {total}")

    if total == 0:
        print("  (no retry data in database)")
        return

    # By level
    print(f"\n  By retry level:")
    for level in ("level1", "level2", "level3", "level4"):
        count = db.alert_retry_attempts.count_documents({"retry_level": level})
        print(f"    {level}  ({LEVEL_QUEUE[level]:<20}) : {count:>4}")

    # By state
    print(f"\n  By state:")
    for state in ("queued", "running_stage1", "running_stage2", "running_stage3",
                  "completed", "partially_completed", "failed"):
        count = db.alert_retry_attempts.count_documents({"state": state})
        if count > 0:
            print(f"    {_state_tag(state):<22} : {count:>4}")

    # Alerts with retries
    alerts_with_retries = db.alerts.count_documents({"retry_attempt_count": {"$gt": 0}})
    in_progress = db.alerts.count_documents({"retry_in_progress": True})
    print(f"\n  Alerts with retries  : {alerts_with_retries}")
    print(f"  Retries in progress  : {in_progress}")

    # Latest 5 batch IDs
    latest = list(
        db.alert_retry_attempts.aggregate([
            {"$sort": {"requested_at": -1}},
            {"$group": {"_id": "$batch_id", "level": {"$first": "$retry_level"},
                        "state": {"$first": "$state"},
                        "alert_count": {"$sum": 1},
                        "requested_at": {"$first": "$requested_at"}}},
            {"$sort": {"requested_at": -1}},
            {"$limit": 5},
        ])
    )
    if latest:
        print(f"\n  Latest 5 batches:")
        for b in latest:
            print(f"    {b['_id']}  level={b['level']}  state={_state_tag(b['state'])}  "
                  f"alerts={b['alert_count']}  at={_fmt_dt(b.get('requested_at'))}")

    # Stage events totals
    total_events = db.retry_stage_events.count_documents({})
    print(f"\n  Total stage events   : {total_events}")
    for status in ("completed", "failed", "running"):
        count = db.retry_stage_events.count_documents({"status": status})
        if count > 0:
            print(f"    {status:<12}: {count}")


def _print_db_counts():
    total = db.alert_retry_attempts.count_documents({})
    events = db.retry_stage_events.count_documents({})
    alerts_retried = db.alerts.count_documents({"retry_attempt_count": {"$gt": 0}})
    print(f"\n  DB totals: {total} attempt(s), {events} stage event(s), "
          f"{alerts_retried} alert(s) with retry history")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "recent":
        limit = int(args[1]) if len(args) > 1 else 20
        show_recent(limit)
    elif args[0] == "alert" and len(args) > 1:
        show_alert(args[1])
    elif args[0] == "batch" and len(args) > 1:
        show_batch(args[1])
    elif args[0] == "summary":
        show_summary()
    else:
        print(__doc__)
        sys.exit(1)
