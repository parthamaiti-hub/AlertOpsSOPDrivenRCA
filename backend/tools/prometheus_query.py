import random
from datetime import UTC, datetime, timedelta


def prometheus_query(query: str, step: str = "60s", duration: str = "1h", **kwargs) -> dict:
    """Stub Prometheus PromQL query. Returns mock time-series data."""
    now = datetime.now(UTC)
    step_seconds = int(step.rstrip("s"))
    dur_parts = duration.rstrip("h")
    dur_hours = int(dur_parts) if dur_parts.isdigit() else 1
    points_count = min((dur_hours * 3600) // step_seconds, 60)

    # Determine metric name from query
    metric_name = "unknown_metric"
    if "cpu" in query.lower():
        metric_name = "process_cpu_seconds_total"
        base_val, variance = 0.85, 0.15
    elif "memory" in query.lower() or "heap" in query.lower() or "jvm" in query.lower():
        metric_name = "jvm_memory_used_bytes"
        base_val, variance = 3.5e9, 0.5e9
    elif "http_request_duration" in query or "latency" in query.lower():
        metric_name = "http_request_duration_seconds"
        base_val, variance = 0.250, 0.150
    elif "db_pool" in query or "connection" in query.lower():
        metric_name = "db_pool_active_connections"
        base_val, variance = 180, 20
    elif "gc" in query.lower():
        metric_name = "jvm_gc_pause_seconds"
        base_val, variance = 0.05, 0.03
    elif "query_duration" in query.lower() or "db_query" in query.lower():
        metric_name = "db_query_duration_seconds"
        base_val, variance = 2.5, 1.5
    else:
        base_val, variance = 50, 10

    values = []
    for i in range(points_count):
        ts = now - timedelta(seconds=(points_count - i) * step_seconds)
        val = base_val + random.uniform(-variance, variance)
        values.append({"timestamp": ts.isoformat() + "Z", "value": round(val, 4)})

    return {
        "query": query,
        "metric_name": metric_name,
        "step": step,
        "duration": duration,
        "data_points": len(values),
        "values": values,
    }
