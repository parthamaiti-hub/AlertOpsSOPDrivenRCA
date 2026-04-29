"""Run retry test documents for levels 1-4 and verify MongoDB records are created.

What this script does:
1. Loads all JSON files from data/retry_test_alerts/
2. Creates alerts via API (/api/alerts)
3. Submits retry for each alert via API (/api/retries)
4. Verifies MongoDB collections contain records:
   - alert_retry_attempts
   - retry_stage_events

Usage:
    uv run python scripts/test_retry_documents.py
    uv run python scripts/test_retry_documents.py --base-url http://localhost:8000
    uv run python scripts/test_retry_documents.py --mongo-uri mongodb://localhost:27017 --db sop_alert_analytics
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from dataclasses import dataclass

import httpx
from pymongo import MongoClient


DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_MONGO_URI = "mongodb://localhost:27017"
DEFAULT_DB = "sop_alert_analytics"
DATA_DIR = pathlib.Path(__file__).parent.parent / "data" / "retry_test_alerts"


@dataclass
class RetryRunResult:
    filename: str
    retry_level: str
    alert_id: str | None
    batch_id: str | None
    accepted: bool
    verify_attempt_doc: bool
    verify_stage_event_doc: bool
    reason: str


def load_retry_documents() -> list[tuple[str, dict]]:
    files = sorted(DATA_DIR.glob("*.json"))
    if not files:
        raise RuntimeError(f"No retry test files found in {DATA_DIR}")

    docs: list[tuple[str, dict]] = []
    for file in files:
        data = json.loads(file.read_text(encoding="utf-8"))
        if "alert" not in data or "retry_level" not in data:
            raise ValueError(f"Invalid retry test file format: {file.name}")
        docs.append((file.name, data))
    return docs


def create_alert(client: httpx.Client, payload: dict) -> str:
    response = client.post("/api/alerts", json=payload)
    response.raise_for_status()
    body = response.json()
    alert_id = body.get("alert_id")
    if not alert_id:
        raise RuntimeError(f"Missing alert_id in create_alert response: {body}")
    return alert_id


def submit_retry(client: httpx.Client, alert_id: str, retry_level: str, reason: str) -> dict:
    request_body = {
        "alert_ids": [alert_id],
        "retry_level": retry_level,
        "reason": reason,
    }
    response = client.post("/api/retries", json=request_body)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, list) or not body:
        raise RuntimeError(f"Unexpected retry response format: {body}")
    return body[0]


def verify_docs(
    db,
    alert_id: str,
    batch_id: str,
    retry_level: str,
    timeout_seconds: int = 8,
) -> tuple[bool, bool]:
    """Poll Mongo briefly for documents created by retry service."""
    deadline = time.time() + timeout_seconds
    attempts_ok = False
    events_ok = False

    while time.time() < deadline:
        attempt_doc = db.alert_retry_attempts.find_one(
            {
                "alert_id": alert_id,
                "batch_id": batch_id,
                "retry_level": retry_level,
            }
        )
        stage_doc = db.retry_stage_events.find_one(
            {
                "alert_id": alert_id,
                "batch_id": batch_id,
            }
        )

        attempts_ok = attempt_doc is not None
        events_ok = stage_doc is not None

        if attempts_ok and events_ok:
            return True, True
        time.sleep(0.25)

    return attempts_ok, events_ok


def run(base_url: str, mongo_uri: str, db_name: str) -> int:
    docs = load_retry_documents()
    client = httpx.Client(base_url=base_url, timeout=30)
    mongo = MongoClient(mongo_uri)
    db = mongo[db_name]

    print("=" * 72)
    print("Retry Document Test Runner")
    print("=" * 72)
    print(f"Base URL : {base_url}")
    print(f"Mongo URI: {mongo_uri}")
    print(f"DB Name  : {db_name}")
    print(f"Files    : {len(docs)}")

    # Sanity checks
    health = client.get("/api/health")
    if health.status_code != 200:
        print(f"ERROR: API health check failed ({health.status_code})")
        return 1

    try:
        db.command("ping")
    except Exception as ex:
        print(f"ERROR: MongoDB ping failed: {ex}")
        return 1

    results: list[RetryRunResult] = []

    for filename, doc in docs:
        retry_level = doc["retry_level"]
        alert_payload = dict(doc["alert"])
        reason = f"retry-doc-test::{filename}"

        print("\n" + "-" * 72)
        print(f"Processing: {filename}")
        print(f"Retry level: {retry_level}")

        try:
            alert_id = create_alert(client, alert_payload)
            print(f"Created alert: {alert_id}")

            retry_resp = submit_retry(client, alert_id, retry_level, reason)
            accepted = bool(retry_resp.get("accepted", False))
            batch_id = retry_resp.get("batch_id")
            reject_reason = retry_resp.get("reason") or ""
            print(f"Retry accepted: {accepted}")
            if batch_id:
                print(f"Batch ID: {batch_id}")
            if reject_reason:
                print(f"Retry reason: {reject_reason}")

            if accepted and batch_id:
                has_attempt, has_event = verify_docs(db, alert_id, batch_id, retry_level)
            else:
                has_attempt, has_event = False, False

            print(f"Mongo alert_retry_attempts doc: {'YES' if has_attempt else 'NO'}")
            print(f"Mongo retry_stage_events doc: {'YES' if has_event else 'NO'}")

            results.append(
                RetryRunResult(
                    filename=filename,
                    retry_level=retry_level,
                    alert_id=alert_id,
                    batch_id=batch_id,
                    accepted=accepted,
                    verify_attempt_doc=has_attempt,
                    verify_stage_event_doc=has_event,
                    reason=reject_reason,
                )
            )
        except Exception as ex:
            print(f"ERROR while processing {filename}: {ex}")
            results.append(
                RetryRunResult(
                    filename=filename,
                    retry_level=retry_level,
                    alert_id=None,
                    batch_id=None,
                    accepted=False,
                    verify_attempt_doc=False,
                    verify_stage_event_doc=False,
                    reason=str(ex),
                )
            )

    print("\n" + "=" * 72)
    print("RESULT SUMMARY")
    print("=" * 72)

    success_count = 0
    for r in results:
        ok = r.accepted and r.verify_attempt_doc and r.verify_stage_event_doc
        status = "PASS" if ok else "FAIL"
        print(
            f"[{status}] {r.filename} | {r.retry_level} | "
            f"accepted={r.accepted} | attempts_doc={r.verify_attempt_doc} | events_doc={r.verify_stage_event_doc}"
        )
        if not ok and r.reason:
            print(f"       reason: {r.reason}")
        if ok:
            success_count += 1

    total = len(results)
    print("-" * 72)
    print(f"Passed: {success_count}/{total}")

    # Also print current collection totals so user can immediately confirm visibility.
    total_attempt_docs = db.alert_retry_attempts.count_documents({})
    total_event_docs = db.retry_stage_events.count_documents({})
    print(f"Mongo totals: alert_retry_attempts={total_attempt_docs}, retry_stage_events={total_event_docs}")

    return 0 if success_count == total else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run retry document tests and verify MongoDB docs")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--mongo-uri", default=DEFAULT_MONGO_URI)
    parser.add_argument("--db", default=DEFAULT_DB)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    exit_code = run(args.base_url, args.mongo_uri, args.db)
    sys.exit(exit_code)
