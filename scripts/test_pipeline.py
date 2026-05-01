"""End-to-end pipeline test script.
Ingests sample alerts (structured JSON, text/RTF JSON, and plain .txt files),
waits for processing through all 3 stages, validates results including mapped SOP ID.

Usage:
    python scripts/test_pipeline.py [--base-url http://localhost:8000]

Alert file types:
  *.json  - structured alerts (POST /api/alerts) or text alerts with alert_text key (POST /api/alerts/text)
  *.txt   - plain text alerts (POST /api/alerts/text with file content as alert_text)
"""

import json
import pathlib
import sys
import time

import httpx

BASE_URL = "http://localhost:8000"
SAMPLE_DIR = pathlib.Path(__file__).parent.parent / "data" / "sample_alerts"
POLL_INTERVAL = 3
POLL_TIMEOUT = 120


def is_text_alert(data: dict) -> bool:
    """Return True if the alert payload is a text/RTF alert."""
    return "alert_text" in data and "source_application" not in data


def main():
    base = BASE_URL
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--base-url" and i + 2 < len(sys.argv):
            base = sys.argv[i + 2]

    client = httpx.Client(base_url=base, timeout=30)

    # Health check
    print("Checking API health...")
    resp = client.get("/api/health")
    assert resp.status_code == 200, f"Health check failed: {resp.status_code}"
    print("  OK")

    json_files = sorted(SAMPLE_DIR.glob("*.json"))
    txt_files = sorted(SAMPLE_DIR.glob("*.txt"))
    alert_files = json_files + txt_files
    if not alert_files:
        print("No sample alert files found in", SAMPLE_DIR)
        sys.exit(1)

    results = {}

    # Ingest all alerts
    print(f"\nIngesting {len(alert_files)} alerts...")
    for f in alert_files:
        if f.suffix == ".txt":
            # Plain text file: post raw content as alert_text
            content = f.read_text(encoding="utf-8")
            payload = {"alert_text": content, "raw_payload": {"filename": f.name}}
            resp = client.post("/api/alerts/text", json=payload)
            alert_type = "txt"
        else:
            alert_data = json.loads(f.read_text())
            text_alert = is_text_alert(alert_data)
            endpoint = "/api/alerts/text" if text_alert else "/api/alerts"
            alert_type = "text" if text_alert else "structured"
            resp = client.post(endpoint, json=alert_data)
        assert resp.status_code == 201, f"Failed to ingest {f.name}: {resp.status_code} {resp.text}"
        alert_id = resp.json()["alert_id"]
        results[f.name] = {"alert_id": alert_id, "alert_type": alert_type, "sop_id": None, "stages": {}}
        print(f"  {f.name} ({alert_type}) -> {alert_id}")

    # Poll for completion
    print("\nWaiting for pipeline processing...")
    terminal_statuses = {"completed", "pending_actions", "sop_workflow_processfailed", "rca_not_found", "sop_not_found"}

    for fname, info in results.items():
        alert_id = info["alert_id"]
        start = time.time()
        last_status = "ingested"

        while (time.time() - start) < POLL_TIMEOUT:
            resp = client.get(f"/api/alerts/{alert_id}")
            if resp.status_code == 200:
                doc = resp.json()
                status = doc.get("status", "")
                sop_id = doc.get("sop_id") or doc.get("sop_document_id") or None
                if sop_id:
                    info["sop_id"] = sop_id
                if status != last_status:
                    info["stages"][status] = True
                    last_status = status
                    sop_tag = f" [SOP: {sop_id}]" if sop_id else ""
                    print(f"  {fname}: {status}{sop_tag}")
                if status in terminal_statuses:
                    break
            time.sleep(POLL_INTERVAL)

        info["final_status"] = last_status
        if last_status not in terminal_statuses:
            info["stages"]["timeout"] = True
            print(f"  {fname}: TIMEOUT (last status: {last_status})")

    # Validate RCA results
    print("\nValidating RCA results...")
    for fname, info in results.items():
        alert_id = info["alert_id"]
        resp = client.get(f"/api/rca/{alert_id}")
        if resp.status_code == 200:
            rca = resp.json()
            checks = {
                "triaging_results": isinstance(rca.get("triaging_results"), list) and len(rca["triaging_results"]) > 0,
                "root_cause": bool(rca.get("root_cause")),
                "impact": bool(rca.get("impact")),
                "recommendation": bool(rca.get("recommendation")),
                "confidence_score": rca.get("confidence_score") is not None,
            }
            info["rca_checks"] = checks
            passed = all(checks.values())
            print(f"  {fname}: {'PASS' if passed else 'FAIL'} {checks}")
        else:
            info["rca_checks"] = {"error": resp.status_code}
            print(f"  {fname}: FAIL (RCA not found)")

    # Submit test feedback
    print("\nSubmitting test feedback...")
    for fname, info in results.items():
        alert_id = info["alert_id"]
        resp = client.post("/api/feedback", json={
            "alert_id": alert_id,
            "comment": f"Automated test feedback for {fname}",
            "confidence_score": 75,
        })
        info["feedback"] = resp.status_code == 201
        print(f"  {fname}: {'PASS' if resp.status_code == 201 else 'FAIL'}")

    # Check pending actions (steps skipped due to requires_approval=true)
    print("\nChecking pending actions (steps awaiting manual approval)...")
    for fname, info in results.items():
        alert_id = info["alert_id"]
        resp = client.get(f"/api/alerts/{alert_id}/pending-actions")
        if resp.status_code == 200:
            pending = resp.json()
            info["pending_actions"] = pending
            if pending:
                print(f"  {fname}: {len(pending)} step(s) pending manual approval:")
                for pa in pending:
                    print(f"    step {pa.get('step_id'):>3} [{pa.get('section',''):12}] tool={pa.get('tool',''):<20} action={pa.get('action','')[:60]}")
            else:
                print(f"  {fname}: no pending actions")
        else:
            info["pending_actions"] = []
            print(f"  {fname}: could not retrieve pending actions ({resp.status_code})")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  {'File':<40} {'Type':<12} {'SOP ID':<30} {'Result'}")
    print(f"  {'-'*38}  {'-'*10}  {'-'*28}  {'-'*6}")
    all_pass = True
    for fname, info in results.items():
        final_status = info.get("final_status", "")
        stages_ok = final_status in ("completed", "pending_actions")
        rca_ok = all(info.get("rca_checks", {}).values()) if isinstance(info.get("rca_checks"), dict) and "error" not in info.get("rca_checks", {}) else False
        fb_ok = info.get("feedback", False)
        pending = info.get("pending_actions", [])
        overall = stages_ok and rca_ok and fb_ok
        if not overall:
            all_pass = False
        sop_id = info.get("sop_id") or "N/A"
        alert_type = info.get("alert_type", "structured")
        detail = f"stages={'OK' if stages_ok else 'FAIL'}, rca={'OK' if rca_ok else 'FAIL'}, feedback={'OK' if fb_ok else 'FAIL'}"
        if pending:
            detail += f", pending={len(pending)} step(s)"
        status = "PASS" if overall else "FAIL"
        if overall and pending:
            status = "PASS*"
        print(f"  {fname:<40} {alert_type:<12} {sop_id:<30} {status}")
        print(f"  {'':40} {'':12} {detail}")
        if pending:
            for pa in pending:
                print(f"  {'':40} {'':12} PENDING step {pa.get('step_id'):>3} [{pa.get('section',''):12}] {pa.get('tool','')}: {pa.get('action','')[:50]}")

    print(f"\nOverall: {'ALL PASS' if all_pass else 'SOME FAILED'}")
    if any(info.get("pending_actions") for info in results.values()):
        print("* PASS* = pipeline completed but has steps awaiting manual approval")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
