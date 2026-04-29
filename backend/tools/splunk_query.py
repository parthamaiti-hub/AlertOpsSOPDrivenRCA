import random
from datetime import UTC, datetime, timedelta


def splunk_query(query: str, time_range: str = "1h") -> dict:
    """Stub Splunk SPL query. Returns mock log entries."""
    now = datetime.now(UTC)
    levels = ["ERROR", "WARN", "ERROR", "ERROR", "INFO"]
    messages = [
        "Connection timed out after 30000ms",
        "Thread pool exhausted - active=200, queued=45",
        "GC overhead limit exceeded",
        "Request processing failed: java.lang.OutOfMemoryError",
        "Health check passed",
        "Slow query detected: 12.3s execution time",
        "Connection pool exhausted, wait queue size=47",
        "CPU spike detected: 98.5% utilization",
    ]
    entries = []
    for i in range(random.randint(5, 12)):
        ts = now - timedelta(minutes=random.randint(1, 60))
        entries.append({
            "timestamp": ts.isoformat() + "Z",
            "level": random.choice(levels),
            "message": random.choice(messages),
            "source": f"prod-app-{random.randint(1, 5):02d}",
        })
    entries.sort(key=lambda x: x["timestamp"], reverse=True)
    return {
        "query": query,
        "time_range": time_range,
        "total_results": len(entries),
        "entries": entries,
    }
